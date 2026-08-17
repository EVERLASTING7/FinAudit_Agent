[CmdletBinding()]
param(
    [string]$BackendPythonPath,
    [string]$NodePath,
    [string]$ProjectRootPath,
    [string]$PythonSitePath,
    [string]$NodeModulesPath,
    [string]$PackageLockPath,
    [string]$NodeValidatorPath,
    [string]$NodeGuardPath,
    [string]$NegativeVectorFixturePath,
    [ValidateSet('draft202012', 'always-true')]
    [string]$SchemaMode = 'draft202012'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-NodeCaptured {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    if (@($Arguments | Where-Object { $_.Contains('"') }).Count -ne 0) {
        throw 'CR-011 Gate B refuses a quoted Node process argument.'
    }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Executable
    $startInfo.Arguments = @(
        $Arguments | ForEach-Object { '"' + $_ + '"' }
    ) -join ' '
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw 'CR-011 Gate B could not start the Node process.'
        }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRootPath)) {
    $ProjectRootPath = Join-Path $PSScriptRoot '..'
}
$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath $ProjectRootPath).Path
)
$childPowerShell = (Get-Command powershell -CommandType Application -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}
$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw "Backend Python executable does not exist: $backendPython"
}

if ([string]::IsNullOrWhiteSpace($NodePath)) {
    $NodePath = (Get-Command node -CommandType Application -ErrorAction Stop).Source
}
$nodeExecutable = [System.IO.Path]::GetFullPath($NodePath)
if (-not (Test-Path -LiteralPath $nodeExecutable -PathType Leaf)) {
    throw "Node executable does not exist: $nodeExecutable"
}

$harnessPath = Join-Path $projectRoot 'scripts/verify-cr011-gate-b.py'
if (-not (Test-Path -LiteralPath $harnessPath -PathType Leaf)) {
    throw 'CR-011 Gate B harness is missing.'
}
$stage1VerifierPath = Join-Path $projectRoot 'scripts/verify-cr011-gate-b-stage1.ps1'
$stage1NegativePath = Join-Path $projectRoot 'scripts/test-verify-cr011-gate-b-stage1.ps1'
$nodeSelfTestPath = Join-Path $projectRoot 'scripts/cr011-gate-b-node/test-validator.cjs'
if (-not (Test-Path -LiteralPath $stage1VerifierPath -PathType Leaf)) {
    throw 'CR-011 Gate B Stage1 verifier is missing.'
}
if (-not (Test-Path -LiteralPath $stage1NegativePath -PathType Leaf)) {
    throw 'CR-011 Gate B Stage1 negative verifier is missing.'
}
if (-not (Test-Path -LiteralPath $nodeSelfTestPath -PathType Leaf)) {
    throw 'CR-011 Gate B Node validator self-test is missing.'
}

$arguments = @(
    '-I',
    $harnessPath,
    '--project-root',
    $projectRoot,
    '--node-path',
    $nodeExecutable,
    '--schema-mode',
    $SchemaMode
)
$optionalPaths = [ordered]@{
    '--python-site' = $PythonSitePath
    '--node-modules' = $NodeModulesPath
    '--package-lock' = $PackageLockPath
    '--node-validator' = $NodeValidatorPath
    '--node-guard' = $NodeGuardPath
    '--negative-vector-fixture' = $NegativeVectorFixturePath
}
foreach ($entry in $optionalPaths.GetEnumerator()) {
    if (-not [string]::IsNullOrWhiteSpace($entry.Value)) {
        $resolvedValue = $entry.Value
        if (-not [System.IO.Path]::IsPathRooted($resolvedValue)) {
            $resolvedValue = Join-Path $projectRoot $resolvedValue
        }
        $arguments += $entry.Key
        $arguments += [System.IO.Path]::GetFullPath($resolvedValue)
    }
}

$environmentNames = @(
    'ALL_PROXY',
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'NO_PROXY',
    'NODE_EXTRA_CA_CERTS',
    'NODE_OPTIONS',
    'NODE_PATH',
    'NPM_CONFIG_CACHE',
    'NPM_CONFIG_PREFIX',
    'NPM_CONFIG_PROXY',
    'NPM_CONFIG_HTTPS_PROXY',
    'PYTHONHOME',
    'PYTHONINSPECT',
    'PYTHONPATH',
    'PYTHONSTARTUP',
    'PYTHONUSERBASE',
    'PYTHONWARNINGS'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [pscustomobject]@{
        Present = Test-Path "Env:$name"
        Value = [System.Environment]::GetEnvironmentVariable($name, 'Process')
    }
}

try {
    foreach ($name in $environmentNames) {
        [System.Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $stage1Output = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $stage1VerifierPath -BackendPythonPath $backendPython 2>&1
        )
        $stage1ExitCode = $LASTEXITCODE
        if ($stage1ExitCode -ne 0) {
            throw "CR-011 Gate B Stage1 failed with exit code $stage1ExitCode."
        }
        $stage1Lines = @($stage1Output | ForEach-Object { $_.ToString().TrimEnd("`r") })
        foreach ($marker in @(
            'CR011_ZERO_SOCKET_GUARD=PASS',
            'CR011_ZERO_SOCKET_ATTEMPTS=0',
            'CR011_GATE_B_STAGE1=PASS',
            'CR011_GATE_B=BLOCKED_DUAL_DRAFT202012_ENGINES',
            'CR011_GATE_B_SCHEMA_ENGINES=0/2'
        )) {
            if (@($stage1Lines | Where-Object { $_ -ceq $marker }).Count -ne 1) {
                throw "CR-011 Gate B Stage1 evidence is missing or duplicated: $marker"
            }
        }
        if ($stage1Lines -ccontains 'CR011_GATE_B=PASS') {
            throw 'CR-011 Gate B Stage1 emitted an unauthorized full PASS marker.'
        }
        $collectedLines = @(
            $stage1Lines | Where-Object { $_ -cmatch '^CR011_GATE_B_STAGE1_COLLECTED=\d+$' }
        )
        $executedLines = @(
            $stage1Lines | Where-Object { $_ -cmatch '^CR011_GATE_B_STAGE1_EXECUTED=\d+$' }
        )
        if ($collectedLines.Count -ne 1 -or $executedLines.Count -ne 1) {
            throw 'CR-011 Gate B Stage1 test counts are missing or duplicated.'
        }
        $stage1Collected = [int]($collectedLines[0] -replace '^.*=', '')
        $stage1Executed = [int]($executedLines[0] -replace '^.*=', '')
        if ($stage1Collected -le 0 -or $stage1Collected -ne $stage1Executed) {
            throw 'CR-011 Gate B Stage1 did not execute every collected test.'
        }

        $stage1NegativeOutput = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $stage1NegativePath 2>&1
        )
        $stage1NegativeExitCode = $LASTEXITCODE
        $stage1NegativeLines = @(
            $stage1NegativeOutput | ForEach-Object { $_.ToString().TrimEnd("`r") }
        )
        if (
            $stage1NegativeExitCode -ne 0 -or
            $stage1NegativeLines.Count -ne 1 -or
            $stage1NegativeLines[0] -cne 'CR011_GATE_B_STAGE1_NEGATIVE_CASES=PASS'
        ) {
            throw 'CR-011 Gate B Stage1 negative boundary failed.'
        }

        $nodeVersion = Invoke-NodeCaptured `
            -Executable $nodeExecutable `
            -Arguments @('--version') `
            -WorkingDirectory $projectRoot
        if (
            $nodeVersion.ExitCode -ne 0 -or
            $nodeVersion.Stderr -cne '' -or
            $nodeVersion.Stdout -cnotmatch '^v20\.19\.0\r?\n$'
        ) {
            throw 'CR-011 Gate B requires the exact Node v20.19.0 runtime.'
        }
        $expectedNodeSelfTestSha256 = `
            'f153003c8b64bb857eaaf592b0c5742b2a26d1c058bcd33b1b7fdb0ccfaa5b12'
        $nodeSelfTestSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $nodeSelfTestPath
        ).Hash.ToLowerInvariant()
        if ($nodeSelfTestSha256 -cne $expectedNodeSelfTestSha256) {
            throw 'CR-011 Gate B Node validator self-test identity mismatch.'
        }
        $nodeSelfTest = Invoke-NodeCaptured `
            -Executable $nodeExecutable `
            -Arguments @($nodeSelfTestPath) `
            -WorkingDirectory $projectRoot
        if (
            $nodeSelfTest.ExitCode -ne 0 -or
            $nodeSelfTest.Stderr -cne '' -or
            $nodeSelfTest.Stdout -cnotmatch '^CR011_NODE_VALIDATOR_SELF_TEST=PASS\r?\n$'
        ) {
            throw 'CR-011 Gate B Node validator self-test failed.'
        }

        $output = @(& $backendPython @arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}
finally {
    foreach ($name in $environmentNames) {
        $previous = $previousEnvironment[$name]
        [System.Environment]::SetEnvironmentVariable(
            $name,
            $(if ($previous.Present) { $previous.Value } else { $null }),
            'Process'
        )
    }
}

if ($exitCode -ne 0) {
    throw "CR-011 Gate B harness failed with exit code $exitCode."
}
$lines = @($output | ForEach-Object { $_.ToString().TrimEnd("`r") })
$expectedHarnessLines = @(
    'CR011_GATE_B_HARNESS=PASS',
    'CR011_GATE_B_CASES=27/27',
    'CR011_GATE_B_NEGATIVE_VECTORS=25/25',
    'CR011_GATE_B_PYTHON_SCHEMA_CALLS=20',
    'CR011_GATE_B_NODE_SCHEMA_CALLS=20',
    'CR011_GATE_B_PYTHON_ENGINE=jsonschema@4.26.0-draft202012',
    'CR011_GATE_B_NODE_ENGINE=ajv@8.20.0-draft2020',
    'CR011_ZERO_SOCKET_GUARD=PASS',
    'CR011_ZERO_SOCKET_ATTEMPTS=0'
)
if ($lines.Count -ne $expectedHarnessLines.Count) {
    throw 'CR-011 Gate B harness emitted an unexpected evidence line count.'
}
for ($index = 0; $index -lt $expectedHarnessLines.Count; $index += 1) {
    if ($lines[$index] -cne $expectedHarnessLines[$index]) {
        throw 'CR-011 Gate B harness emitted unexpected or out-of-order evidence.'
    }
}

$stage1Evidence = @(
    'CR011_GATE_B_STAGE1=PASS',
    "CR011_GATE_B_STAGE1_COLLECTED=$stage1Collected",
    "CR011_GATE_B_STAGE1_EXECUTED=$stage1Executed",
    'CR011_GATE_B_STAGE1_ZERO_SOCKET_ATTEMPTS=0',
    'CR011_GATE_B_STAGE1_NEGATIVE_CASES=PASS'
)
$finalEvidence = @($stage1Evidence) + @(
    'CR011_NODE_VALIDATOR_SELF_TEST=PASS'
) + @($lines) + @(
    'CR011_GATE_B=PASS',
    'CR011_GATE_B_SCHEMA_ENGINES=2/2',
    'CR011_PROVIDER_NETWORK=NOT_RUN',
    'CR011_PERSISTENT_RUNTIME=NOT_AUTHORIZED',
    'CR011_PRODUCTION=NOT_AUTHORIZED'
)
if ($finalEvidence.Count -ne 20) {
    throw 'CR-011 Gate B final evidence line count is not the fixed 20-line contract.'
}
$finalEvidence | ForEach-Object { $_ }
