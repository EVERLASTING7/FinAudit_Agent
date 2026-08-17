[CmdletBinding()]
param(
    [string]$BackendPythonPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$backendRoot = Join-Path $projectRoot 'backend'
$backendTests = Join-Path $backendRoot 'tests'

if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $backendRoot '.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}

$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw "Backend Python executable does not exist: $backendPython"
}

$pluginPath = Join-Path $backendTests 'gate_b_zero_socket_plugin.py'
$testPaths = @(
    'tests/unit/test_ai_strict_json.py',
    'tests/unit/test_ai_policy_companion.py',
    'tests/unit/test_ai_policy_resolver.py',
    'tests/unit/test_ai_network_policy.py',
    'tests/unit/test_ai_retry_policy.py',
    'tests/unit/test_ai_response_boundary.py',
    'tests/unit/test_ai_events.py',
    'tests/unit/test_ai_event_sink.py',
    'tests/unit/test_cr011_stage1_boundaries.py'
)
if (-not (Test-Path -LiteralPath $pluginPath -PathType Leaf)) {
    throw 'CR-011 zero-socket pytest plugin is missing.'
}
foreach ($relativePath in $testPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $backendRoot $relativePath) -PathType Leaf)) {
        throw "Required CR-011 Stage1 test is missing: $relativePath"
    }
}

$environmentNames = @(
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
    'PYTEST_ADDOPTS',
    'PYTEST_PLUGINS',
    'PYTHONPATH',
    'FINAUDIT_CR011_GATE_B_STAGE1'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [pscustomobject]@{
        Present = Test-Path "Env:$name"
        Value = [System.Environment]::GetEnvironmentVariable($name, 'Process')
    }
}

try {
    [System.Environment]::SetEnvironmentVariable(
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
        '1',
        'Process'
    )
    [System.Environment]::SetEnvironmentVariable('PYTEST_ADDOPTS', $null, 'Process')
    [System.Environment]::SetEnvironmentVariable('PYTEST_PLUGINS', $null, 'Process')
    [System.Environment]::SetEnvironmentVariable('PYTHONPATH', $backendTests, 'Process')
    [System.Environment]::SetEnvironmentVariable(
        'FINAUDIT_CR011_GATE_B_STAGE1',
        '1',
        'Process'
    )

    Push-Location $backendRoot
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = @(
                & $backendPython -m pytest `
                    --confcutdir (Join-Path $backendTests 'unit') `
                    -p gate_b_zero_socket_plugin `
                    --strict-markers -q -ra @testPaths 2>&1
            )
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        Pop-Location
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

$outputText = ($output | ForEach-Object { $_.ToString() }) -join [System.Environment]::NewLine
if ($exitCode -ne 0) {
    $output | ForEach-Object { $_.ToString() }
    throw "CR-011 Gate B Stage1 tests failed with exit code $exitCode."
}
if ($outputText -notmatch '(?m)^CR011_ZERO_SOCKET_GUARD=PASS\r?$') {
    throw 'CR-011 Gate B Stage1 did not prove the zero-socket guard.'
}
if ($outputText -notmatch '(?m)^CR011_ZERO_SOCKET_ATTEMPTS=0\r?$') {
    throw 'CR-011 Gate B Stage1 observed a socket attempt.'
}
$collectedMatch = [regex]::Match(
    $outputText,
    '(?m)^CR011_GATE_B_STAGE1_COLLECTED=(\d+)\r?$'
)
$executedMatch = [regex]::Match(
    $outputText,
    '(?m)^CR011_GATE_B_STAGE1_EXECUTED=(\d+)\r?$'
)
if (
    -not $collectedMatch.Success -or
    -not $executedMatch.Success -or
    [int]$collectedMatch.Groups[1].Value -le 0 -or
    $collectedMatch.Groups[1].Value -ne $executedMatch.Groups[1].Value
) {
    throw 'CR-011 Gate B Stage1 did not execute every collected test.'
}
if ($outputText -match '(?i)\b(skipped|xfailed|xpassed)\b') {
    throw 'CR-011 Gate B Stage1 cannot pass with skipped or xfail results.'
}

$output | ForEach-Object { $_.ToString() }
'CR011_GATE_B_STAGE1=PASS'
'CR011_GATE_B=BLOCKED_DUAL_DRAFT202012_ENGINES'
'CR011_GATE_B_SCHEMA_ENGINES=0/2'
'CR011_PROVIDER_NETWORK=NOT_RUN'
'CR011_PERSISTENT_RUNTIME=NOT_AUTHORIZED'
'CR011_PRODUCTION=NOT_AUTHORIZED'
