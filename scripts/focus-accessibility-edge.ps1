[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ProfilePath
)

$ErrorActionPreference = 'Stop'
$resolvedProfile = [IO.Path]::GetFullPath($ProfilePath)
$resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (
    -not $resolvedProfile.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
    -not ([IO.Path]::GetFileName($resolvedProfile)).StartsWith(
        'finaudit-browser-gate-',
        [StringComparison]::Ordinal
    )
) {
    throw 'Accessibility Edge profile is outside the dedicated system temp scope.'
}

if (-not ('FinAuditAccessibilityEdge.Native' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace FinAuditAccessibilityEdge {
    public static class Native {
        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassName(IntPtr hWnd, StringBuilder className, int maxCount);

        [DllImport("user32.dll")]
        private static extern bool ShowWindowAsync(IntPtr hWnd, int command);

        [DllImport("user32.dll")]
        private static extern bool BringWindowToTop(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        public static IntPtr[] FindEdgeWindows(int[] processIds) {
            var allowed = new HashSet<int>(processIds);
            var windows = new List<IntPtr>();
            EnumWindows((window, _) => {
                if (!IsWindowVisible(window)) return true;
                uint processId;
                GetWindowThreadProcessId(window, out processId);
                if (!allowed.Contains((int)processId)) return true;
                var className = new StringBuilder(128);
                GetClassName(window, className, className.Capacity);
                if (className.ToString() == "Chrome_WidgetWin_1") windows.Add(window);
                return true;
            }, IntPtr.Zero);
            return windows.ToArray();
        }

        public static bool Focus(IntPtr window) {
            ShowWindowAsync(window, 9);
            BringWindowToTop(window);
            SetForegroundWindow(window);
            return GetForegroundWindow() == window;
        }
    }
}
'@
}

$allProcesses = @(Get-CimInstance Win32_Process)
$ownedIds = [Collections.Generic.HashSet[int]]::new()
foreach ($process in $allProcesses) {
    if (
        $process.Name -ceq 'msedge.exe' -and
        -not [string]::IsNullOrEmpty($process.CommandLine) -and
        $process.CommandLine.IndexOf($resolvedProfile, [StringComparison]::OrdinalIgnoreCase) -ge 0
    ) {
        [void]$ownedIds.Add([int]$process.ProcessId)
    }
}
if ($ownedIds.Count -eq 0) {
    throw 'No Edge process is bound to the accessibility profile.'
}
do {
    $added = $false
    foreach ($process in $allProcesses) {
        if (
            $ownedIds.Contains([int]$process.ParentProcessId) -and
            -not $ownedIds.Contains([int]$process.ProcessId)
        ) {
            [void]$ownedIds.Add([int]$process.ProcessId)
            $added = $true
        }
    }
} while ($added)

$windows = @([FinAuditAccessibilityEdge.Native]::FindEdgeWindows(@($ownedIds)))
if ($windows.Count -ne 1) {
    throw "Expected one accessibility Edge window, found $($windows.Count)."
}
if (-not [FinAuditAccessibilityEdge.Native]::Focus($windows[0])) {
    Start-Sleep -Milliseconds 300
    if (-not [FinAuditAccessibilityEdge.Native]::Focus($windows[0])) {
        throw 'The accessibility Edge window could not become the Windows foreground window.'
    }
}

[ordered]@{
    schema_version = 'finaudit-accessibility-edge-focus-v1'
    owned_process_count = $ownedIds.Count
    window_handle = $windows[0].ToInt64()
} | ConvertTo-Json -Compress
