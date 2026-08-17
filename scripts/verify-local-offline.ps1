[CmdletBinding()]
param(
    [string]$BackendPythonPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)

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

$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules') -PathType Container)) {
    throw 'Frontend node_modules is missing; this offline gate never installs dependencies.'
}

$requiredScripts = @(
    'scripts/verify-baseline.ps1',
    'scripts/test-verify-baseline.ps1',
    'scripts/verify-git-governance.ps1',
    'scripts/test-verify-git-governance.ps1',
    'scripts/verify-remote-branch-protection-fixture.py',
    'scripts/test-verify-remote-branch-protection-fixture.ps1',
    'scripts/verify-test-assets.ps1',
    'scripts/test-verify-test-assets.ps1',
    'scripts/verify-postgresql-current-head.ps1',
    'scripts/test-verify-postgresql-current-head.ps1'
)
foreach ($relativePath in $requiredScripts) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath) -PathType Leaf)) {
        throw "Required offline gate is missing: $relativePath"
    }
}

$results = [System.Collections.Generic.List[object]]::new()
$totalStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

function Invoke-OfflineStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = @(& $FilePath @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        Pop-Location
        $stopwatch.Stop()
    }

    if ($exitCode -ne 0) {
        throw "Local offline quality gate failed at '$Name' with exit code $exitCode."
    }

    [pscustomobject]@{
        Name = $Name
        ElapsedMilliseconds = $stopwatch.ElapsedMilliseconds
        Output = [string[]]@($output | ForEach-Object { $_.ToString() })
    }
}

function Add-OfflineStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    $results.Add(
        (Invoke-OfflineStep -Name $Name -FilePath $FilePath -Arguments $Arguments `
                -WorkingDirectory $WorkingDirectory)
    )
}

Add-OfflineStep -Name 'baseline-positive' -FilePath $childPowerShell -WorkingDirectory $projectRoot `
    -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/verify-baseline.ps1'), '-RootPath', $projectRoot
    )
Add-OfflineStep -Name 'baseline-negative' -FilePath $childPowerShell -WorkingDirectory $projectRoot `
    -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/test-verify-baseline.ps1')
    )
Add-OfflineStep -Name 'git-governance-positive' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/verify-git-governance.ps1'),
        '-VersionTag', 'v0.1.0'
    )
Add-OfflineStep -Name 'git-governance-negative' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/test-verify-git-governance.ps1')
    )
Add-OfflineStep -Name 'branch-protection-fixture' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/test-verify-remote-branch-protection-fixture.ps1'),
        '-BackendPythonPath', $backendPython
    )
Add-OfflineStep -Name 'test-assets-positive' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/verify-test-assets.ps1'), '-ProjectRoot', $projectRoot
    )
Add-OfflineStep -Name 'test-assets-negative' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/test-verify-test-assets.ps1'),
        '-ProjectRoot', $projectRoot
    )
Add-OfflineStep -Name 'postgres-current-head-negative' -FilePath $childPowerShell `
    -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $projectRoot 'scripts/test-verify-postgresql-current-head.ps1')
    )

$testDatabaseUrlWasPresent = Test-Path Env:TEST_DATABASE_URL
$testDatabaseUrl = if ($testDatabaseUrlWasPresent) {
    [System.Environment]::GetEnvironmentVariable('TEST_DATABASE_URL', 'Process')
}
else {
    $null
}
try {
    [System.Environment]::SetEnvironmentVariable('TEST_DATABASE_URL', $null, 'Process')
    Add-OfflineStep -Name 'backend-pytest' -FilePath $backendPython -WorkingDirectory $backendRoot `
        -Arguments @('-m', 'pytest')
}
finally {
    if ($testDatabaseUrlWasPresent) {
        [System.Environment]::SetEnvironmentVariable(
            'TEST_DATABASE_URL',
            $testDatabaseUrl,
            'Process'
        )
    }
}

Add-OfflineStep -Name 'backend-ruff-check' -FilePath $backendPython -WorkingDirectory $backendRoot `
    -Arguments @('-m', 'ruff', 'check', 'app', 'alembic/versions', 'tests')
Add-OfflineStep -Name 'backend-ruff-format' -FilePath $backendPython -WorkingDirectory $backendRoot `
    -Arguments @('-m', 'ruff', 'format', '--check', 'app', 'alembic/versions', 'tests')
Add-OfflineStep -Name 'backend-mypy' -FilePath $backendPython -WorkingDirectory $backendRoot `
    -Arguments @('-m', 'mypy', 'app')
Add-OfflineStep -Name 'backend-pip-check' -FilePath $backendPython -WorkingDirectory $backendRoot `
    -Arguments @('-m', 'pip', 'check')

$offlineQualityFlagWasPresent = Test-Path Env:FINAUDIT_LOCAL_OFFLINE_QUALITY
$offlineQualityFlag = if ($offlineQualityFlagWasPresent) {
    [System.Environment]::GetEnvironmentVariable('FINAUDIT_LOCAL_OFFLINE_QUALITY', 'Process')
}
else {
    $null
}
try {
    [System.Environment]::SetEnvironmentVariable(
        'FINAUDIT_LOCAL_OFFLINE_QUALITY',
        '1',
        'Process'
    )
    Add-OfflineStep -Name 'frontend-typecheck' -FilePath $npm -WorkingDirectory $frontendRoot `
        -Arguments @('run', 'typecheck')
    Add-OfflineStep -Name 'frontend-test' -FilePath $npm -WorkingDirectory $frontendRoot `
        -Arguments @('test', '--', '--run')
    Add-OfflineStep -Name 'frontend-build' -FilePath $npm -WorkingDirectory $frontendRoot `
        -Arguments @('run', 'build')
}
finally {
    if ($offlineQualityFlagWasPresent) {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_LOCAL_OFFLINE_QUALITY',
            $offlineQualityFlag,
            'Process'
        )
    }
    else {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_LOCAL_OFFLINE_QUALITY',
            $null,
            'Process'
        )
    }
}

$totalStopwatch.Stop()
foreach ($result in $results) {
    "LOCAL_OFFLINE_STEP=$($result.Name) status=ok elapsed_ms=$($result.ElapsedMilliseconds)"
    $result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
}

'POSTGRESQL_CURRENT_HEAD=NOT_RUN (TEST_DATABASE_URL intentionally unset)'
'DOCKER_COMPOSE_RUNTIME=NOT_RUN'
'BROWSER_E2E=NOT_RUN'
'PROVIDER_NETWORK=NOT_RUN'
'LOOPBACK_NETWORK_STACK=RUN (isolated expected-failure unit test only)'
'REMOTE_BRANCH_PROTECTION=NOT_RUN (hosting service not queried)'
'PRODUCTION=NOT_RUN'
"LOCAL_OFFLINE_TOTAL_MS=$($totalStopwatch.ElapsedMilliseconds)"
'LOCAL_OFFLINE_QUALITY=PASS'
