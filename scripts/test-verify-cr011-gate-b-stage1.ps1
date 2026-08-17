[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$verifierPath = Join-Path $projectRoot 'scripts/verify-cr011-gate-b-stage1.ps1'
$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$missingPython = Join-Path (
    [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
) ('finaudit-missing-cr011-python-' + [System.Guid]::NewGuid().ToString('N') + '.exe')

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $output = @(
        & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $verifierPath -BackendPythonPath $missingPython 2>&1
    )
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$outputText = ($output | ForEach-Object { $_.ToString() }) -join [System.Environment]::NewLine
if ($exitCode -eq 0) {
    throw 'A missing Backend Python executable unexpectedly passed the CR-011 Stage1 gate.'
}
if ($outputText -match '(?m)^CR011_GATE_B_STAGE1=PASS\r?$') {
    throw 'The failed CR-011 Stage1 gate emitted a PASS marker.'
}

$global:LASTEXITCODE = 0
'CR011_GATE_B_STAGE1_NEGATIVE_CASES=PASS'
