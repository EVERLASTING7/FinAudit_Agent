[CmdletBinding()]
param([string]$BackendPythonPath)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$corePath = Join-Path $projectRoot 'scripts/verify-cr011-r5-gate-c.py'
$verifierPath = Join-Path $projectRoot 'scripts/verify-cr011-r5-gate-c.ps1'
$wheelhouse = Join-Path $projectRoot 'build/cr011-gate-b-dependencies/python-wheelhouse'
$childPowerShell = (Get-Command powershell -CommandType Application -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}
$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
foreach ($path in @($backendPython, $corePath, $verifierPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Gate C anti-forgery file is missing: $path"
    }
}

$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-cr011-r5-anti-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Gate C anti-forgery temporary path escaped the system temporary directory.'
}
[void](New-Item -ItemType Directory -Path $tempRoot)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$completedCases = 0

function Invoke-Captured {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = 0
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Lines = [string[]]@($output | ForEach-Object { $_.ToString().TrimEnd("`r") })
    }
}

function Assert-FailsClosed {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][object]$Result
    )

    if ($Result.ExitCode -eq 0) {
        throw "$Name unexpectedly passed."
    }
    foreach ($trusted in @(
            'CR011_R5_GATE_C=PASS',
            'CR011_R5_GATE_C_PREFLIGHT=PASS',
            'CR011_R5_GATE_C_ARTIFACTS=PASS',
            'CR011_R5_FOCUSED_COVERAGE=PASS'
        )) {
        if ($Result.Lines -ccontains $trusted) {
            throw "$Name emitted trusted PASS evidence after failure."
        }
    }
    $script:completedCases += 1
}

function Write-Child {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Body
    )

    $path = Join-Path $tempRoot $Name
    [System.IO.File]::WriteAllText($path, $Body, $utf8NoBom)
    return $path
}

function Write-Evidence {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Lines
    )

    $path = Join-Path $tempRoot $Name
    [System.IO.File]::WriteAllText($path, (($Lines -join "`n") + "`n"), $utf8NoBom)
    return $path
}

function Invoke-MarkerChild {
    param([Parameter(Mandatory)][string]$ChildPath)

    Invoke-Captured -FilePath $backendPython -Arguments @(
        '-I', $corePath, 'run-child', '--cwd', $tempRoot, '--exact',
        '--expected', 'CR011_R5_TEST_CHILD=ONE',
        '--expected', 'CR011_R5_TEST_CHILD=TWO',
        '--', $childPowerShell, '-NoProfile', '-NonInteractive',
        '-ExecutionPolicy', 'Bypass', '-File', $ChildPath
    )
}

try {
    $missingCache = Invoke-Captured -FilePath $childPowerShell -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $verifierPath,
        '-BackendPythonPath', $backendPython,
        '-WheelhousePath', (Join-Path $tempRoot 'missing-wheelhouse')
    )
    Assert-FailsClosed -Name 'missing offline verified cache' -Result $missingCache

    $driftedWheelhouse = Join-Path $tempRoot 'drifted-wheelhouse'
    [void](New-Item -ItemType Directory -Path $driftedWheelhouse)
    Get-ChildItem -LiteralPath $wheelhouse -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $driftedWheelhouse
    }
    $driftPath = Join-Path $driftedWheelhouse 'attrs-26.1.0-py3-none-any.whl'
    $bytes = [System.IO.File]::ReadAllBytes($driftPath)
    $bytes[$bytes.Length - 1] = $bytes[$bytes.Length - 1] -bxor 1
    [System.IO.File]::WriteAllBytes($driftPath, $bytes)
    $hashDrift = Invoke-Captured -FilePath $backendPython -Arguments @(
        '-I', $corePath, 'preflight', '--project-root', $projectRoot,
        '--wheelhouse', $driftedWheelhouse
    )
    Assert-FailsClosed -Name 'offline cache hash drift' -Result $hashDrift

    $resourceSet = Invoke-Captured -FilePath $backendPython -Arguments @(
        '-I', $corePath, 'resource-set-selftest', '--source-root', (Join-Path $projectRoot 'backend')
    )
    if (
        $resourceSet.ExitCode -ne 0 -or $resourceSet.Lines.Count -ne 1 -or
        $resourceSet.Lines[0] -cne 'CR011_R5_RESOURCE_SET_CASEFOLD_NEGATIVES=2/2'
    ) {
        throw 'Case-insensitive source/wheel JSON resource-set negatives failed.'
    }
    $completedCases += 2

    $missingMarker = Write-Child -Name 'missing-marker.ps1' -Body @'
'CR011_R5_TEST_CHILD=ONE'
'@
    Assert-FailsClosed -Name 'missing marker' -Result (Invoke-MarkerChild $missingMarker)

    $duplicateMarker = Write-Child -Name 'duplicate-marker.ps1' -Body @'
'CR011_R5_TEST_CHILD=ONE'
'CR011_R5_TEST_CHILD=ONE'
'CR011_R5_TEST_CHILD=TWO'
'@
    Assert-FailsClosed -Name 'duplicate marker' -Result (Invoke-MarkerChild $duplicateMarker)

    $outOfOrder = Write-Child -Name 'out-of-order.ps1' -Body @'
'CR011_R5_TEST_CHILD=TWO'
'CR011_R5_TEST_CHILD=ONE'
'@
    Assert-FailsClosed -Name 'out-of-order marker' -Result (Invoke-MarkerChild $outOfOrder)

    $nonzero = Write-Child -Name 'nonzero.ps1' -Body @'
'CR011_R5_TEST_CHILD=ONE'
'CR011_R5_TEST_CHILD=TWO'
'CR011_R5_GATE_C=PASS'
exit 7
'@
    Assert-FailsClosed -Name 'nonzero child with forged PASS' -Result (Invoke-MarkerChild $nonzero)

    $forgedFinal = Write-Child -Name 'forged-final.ps1' -Body @'
'CR011_R5_TEST_CHILD=ONE'
'CR011_R5_TEST_CHILD=TWO'
'CR011_R5_GATE_C=PASS'
'@
    Assert-FailsClosed -Name 'child-forged outer PASS' -Result (Invoke-MarkerChild $forgedFinal)

    $poisonSafe = Write-Child -Name 'poison-safe.ps1' -Body @'
foreach ($name in @(
    'PYTHONPATH', 'HTTPS_PROXY', 'AI_POLICY_FILE', 'APP_ENV', 'SECRET_KEY',
    'MINIO_SECRET_KEY', 'METRICS_INTERNAL_TOKEN', 'CR011_R5_ARBITRARY_SENTINEL'
)) {
    if ([System.Environment]::GetEnvironmentVariable($name, 'Process')) { exit 9 }
}
'CR011_R5_TEST_CHILD=ONE'
'CR011_R5_TEST_CHILD=TWO'
'@
    $poisonedNames = @(
        'PYTHONPATH', 'HTTPS_PROXY', 'AI_POLICY_FILE', 'APP_ENV', 'SECRET_KEY',
        'MINIO_SECRET_KEY', 'METRICS_INTERNAL_TOKEN', 'CR011_R5_ARBITRARY_SENTINEL'
    )
    $previous = @{}
    foreach ($name in $poisonedNames) {
        $previous[$name] = [pscustomobject]@{
            Present = Test-Path "Env:$name"
            Value = [System.Environment]::GetEnvironmentVariable($name, 'Process')
        }
        [System.Environment]::SetEnvironmentVariable($name, 'Z:\forbidden-poison', 'Process')
    }
    try {
        $poisonResult = Invoke-MarkerChild $poisonSafe
    }
    finally {
        foreach ($name in $poisonedNames) {
            $saved = $previous[$name]
            [System.Environment]::SetEnvironmentVariable(
                $name,
                $(if ($saved.Present) { $saved.Value } else { $null }),
                'Process'
            )
        }
    }
    if (
        $poisonResult.ExitCode -ne 0 -or $poisonResult.Lines.Count -ne 2 -or
        $poisonResult.Lines[0] -cne 'CR011_R5_TEST_CHILD=ONE' -or
        $poisonResult.Lines[1] -cne 'CR011_R5_TEST_CHILD=TWO'
    ) {
        throw 'Environment poisoning crossed the strict child boundary.'
    }
    $completedCases += 1

    $manifest = Invoke-Captured -FilePath $backendPython -Arguments @(
        '-I', $corePath, 'focused-manifest'
    )
    $manifestCountMatch = if ($manifest.Lines.Count -ge 1) {
        [regex]::Match($manifest.Lines[0], '^CR011_R5_FOCUSED_MANIFEST_COUNT=([1-9][0-9]*)$')
    }
    else {
        [regex]::Match('', 'x')
    }
    if ($manifest.ExitCode -ne 0 -or -not $manifestCountMatch.Success) {
        throw 'Focused manifest could not be loaded for anti-forgery tests.'
    }
    $focusedCount = [int]$manifestCountMatch.Groups[1].Value
    if ($focusedCount -lt 2 -or $manifest.Lines.Count -ne $focusedCount + 2) {
        throw 'Focused manifest is too small or internally inconsistent.'
    }
    $focusedHash = $manifest.Lines[1].Substring('CR011_R5_FOCUSED_MANIFEST_SHA256='.Length)
    $nodeIds = [string[]]@(
        $manifest.Lines[2..($manifest.Lines.Count - 1)] | ForEach-Object {
            if ($_ -cnotmatch '^CR011_R5_FOCUSED_NODEID=') {
                throw 'Focused manifest nodeid marker is invalid.'
            }
            $_.Substring('CR011_R5_FOCUSED_NODEID='.Length)
        }
    )
    $validCollect = Write-Evidence -Name 'focused-valid-collect.txt' `
        -Lines (@($nodeIds) + "${focusedCount} tests collected in 0.01s")
    $validProgress = ('.' * $focusedCount) -join ''
    $validResult = Write-Evidence -Name 'focused-valid-result.txt' `
        -Lines @("${validProgress} [100%]", "${focusedCount} passed in 0.01s")
    $validEvidence = Invoke-Captured -FilePath $backendPython -Arguments @(
        '-I', $corePath, 'verify-focused-evidence',
        '--collected-output', $validCollect, '--result-output', $validResult
    )
    $validExpected = @(
        "CR011_R5_FOCUSED_MANIFEST=${focusedCount}/${focusedCount}",
        "CR011_R5_FOCUSED_MANIFEST_SHA256=${focusedHash}",
        "CR011_R5_FOCUSED_TESTS=${focusedCount}_PASSED",
        'CR011_R5_FOCUSED_SKIP_XFAIL_XPASS=0',
        'CR011_R5_FOCUSED_COVERAGE=PASS'
    )
    if (
        $validEvidence.ExitCode -ne 0 -or $validEvidence.Lines.Count -ne $validExpected.Count -or
        (Compare-Object -ReferenceObject $validExpected -DifferenceObject $validEvidence.Lines `
                -SyncWindow 0 -CaseSensitive)
    ) {
        throw 'Focused manifest positive control failed.'
    }

    $deletedCollect = Write-Evidence -Name 'focused-deleted-collect.txt' `
        -Lines (@($nodeIds[1..($nodeIds.Count - 1)]) + "$($focusedCount - 1) tests collected in 0.01s")
    Assert-FailsClosed -Name 'focused nodeid deletion' -Result (
        Invoke-Captured -FilePath $backendPython -Arguments @(
            '-I', $corePath, 'verify-focused-evidence',
            '--collected-output', $deletedCollect, '--result-output', $validResult
        )
    )

    $renamedNodeIds = [string[]]@($nodeIds)
    $renamedNodeIds[0] = $renamedNodeIds[0] + '_RENAMED'
    $renamedCollect = Write-Evidence -Name 'focused-renamed-collect.txt' `
        -Lines (@($renamedNodeIds) + "${focusedCount} tests collected in 0.01s")
    Assert-FailsClosed -Name 'focused nodeid rename' -Result (
        Invoke-Captured -FilePath $backendPython -Arguments @(
            '-I', $corePath, 'verify-focused-evidence',
            '--collected-output', $renamedCollect, '--result-output', $validResult
        )
    )

    $forgedCount = $focusedCount + 1
    $forgedProgress = ('.' * $forgedCount) -join ''
    $forgedResult = Write-Evidence -Name 'focused-forged-count.txt' `
        -Lines @("${forgedProgress} [100%]", "${forgedCount} passed in 0.01s")
    Assert-FailsClosed -Name 'focused forged pass count' -Result (
        Invoke-Captured -FilePath $backendPython -Arguments @(
            '-I', $corePath, 'verify-focused-evidence',
            '--collected-output', $validCollect, '--result-output', $forgedResult
        )
    )
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
        if (-not $resolvedTempRoot.StartsWith(
                $tempBase,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            throw 'Refusing to remove a Gate C anti-forgery path outside the temporary root.'
        }
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}

if ($completedCases -ne 13) {
    throw "Gate C anti-forgery coverage mismatch: $completedCases/13."
}
$global:LASTEXITCODE = 0
'CR011_R5_GATE_C_NEGATIVE_CASES=13/13'
'CR011_R5_GATE_C_ANTI_FORGERY=PASS'
