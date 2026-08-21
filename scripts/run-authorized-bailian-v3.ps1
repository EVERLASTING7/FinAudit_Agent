param([switch]$PreflightOnly)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$runnerPath = Join-Path $projectRoot 'scripts\run_live_bailian_synthetic_benchmark.py'
$postgresImage = 'sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777'
$qdrantImage = 'sha256:2e8646f963a64a21b3e3f851719e17668644d1ed386285064c2548a52d16ede8'
$runId = [Guid]::NewGuid().ToString('N')
$databaseName = "finaudit_bailian_v3_$($runId.Substring(0, 12))_test"
$postgresName = "finaudit-bailian-v3-pg-$($runId.Substring(0, 12))"
$qdrantName = "finaudit-bailian-v3-qdrant-$($runId.Substring(0, 12))"
$postgresPassword = 'finaudit-v3-disposable-password'
$label = 'finaudit.live-benchmark-v3=1'
$runLabel = "finaudit.live-benchmark-v3.run=$runId"
$runnerResult = $null
$runnerExitCode = 1
$runnerStderrPresent = $false
$cleanupContainerCount = -1
$cleanupNetworkCount = -1
$postgresCreated = $false
$qdrantCreated = $false

$managedEnvironmentNames = @(
    'DATABASE_URL',
    'TEST_DATABASE_URL',
    'TEST_QDRANT_URL',
    'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS',
    'FINAUDIT_LIVE_BAILIAN_SYNTHETIC_BENCHMARK',
    'FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY',
    'EMBEDDING_API_KEY'
)
$priorEnvironment = @{}
foreach ($name in $managedEnvironmentNames) {
    $priorEnvironment[$name] = [pscustomobject]@{
        Present = Test-Path "Env:$name"
        Value = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
}

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'AUTHORIZED_BAILIAN_V3_DOCKER_FAILED'
    }
    return @($output)
}

function Get-PublishedPort {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [Parameter(Mandatory = $true)][string]$ContainerPort
    )

    $lines = @(Invoke-Docker -Arguments @('port', $Container, $ContainerPort))
    if ($lines.Count -ne 1 -or $lines[0] -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'AUTHORIZED_BAILIAN_V3_PORT_INVALID'
    }
    return [int]$Matches[1]
}

function Restore-ManagedEnvironment {
    foreach ($name in $managedEnvironmentNames) {
        $prior = $priorEnvironment[$name]
        [Environment]::SetEnvironmentVariable(
            $name,
            $(if ($prior.Present) { $prior.Value } else { $null }),
            'Process'
        )
    }
}

try {
    $existingContainers = @(& docker ps -aq --filter 'label=finaudit.live-benchmark-v3=1')
    $existingNetworks = @(& docker network ls -q --filter 'label=finaudit.live-benchmark-v3=1')
    if ($LASTEXITCODE -ne 0 -or $existingContainers.Count -ne 0 -or $existingNetworks.Count -ne 0) {
        throw 'AUTHORIZED_BAILIAN_V3_PREEXISTING_RESOURCES'
    }
    $postgresTagId = (& docker image inspect postgres:16-alpine --format '{{.Id}}').Trim()
    $qdrantTagId = (& docker image inspect qdrant/qdrant:v1.10.0 --format '{{.Id}}').Trim()
    if ($postgresTagId -ne $postgresImage -or $qdrantTagId -ne $qdrantImage) {
        throw 'AUTHORIZED_BAILIAN_V3_IMAGE_DRIFT'
    }

    $null = Invoke-Docker -Arguments @(
        'run', '--detach', '--pull', 'never',
        '--name', $postgresName,
        '--label', $label,
        '--label', $runLabel,
        '--publish', '127.0.0.1::5432',
        '--tmpfs', '/var/lib/postgresql/data:rw,noexec,nosuid,size=1073741824',
        '--env', "POSTGRES_PASSWORD=$postgresPassword",
        '--env', "POSTGRES_DB=$databaseName",
        $postgresImage
    )
    $postgresCreated = $true
    $null = Invoke-Docker -Arguments @(
        'run', '--detach', '--pull', 'never',
        '--name', $qdrantName,
        '--label', $label,
        '--label', $runLabel,
        '--publish', '127.0.0.1::6333',
        '--tmpfs', '/qdrant/storage:rw,noexec,nosuid,size=536870912',
        $qdrantImage
    )
    $qdrantCreated = $true

    $postgresReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        & docker exec $postgresName pg_isready -U postgres -d $databaseName *> $null
        if ($LASTEXITCODE -eq 0) {
            $postgresReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $postgresReady) {
        throw 'AUTHORIZED_BAILIAN_V3_POSTGRES_NOT_READY'
    }
    $postgresPort = Get-PublishedPort -Container $postgresName -ContainerPort '5432/tcp'
    $qdrantPort = Get-PublishedPort -Container $qdrantName -ContainerPort '6333/tcp'

    $qdrantReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:$qdrantPort/healthz" -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                $qdrantReady = $true
                break
            }
        }
        catch {
        }
        Start-Sleep -Seconds 1
    }
    if (-not $qdrantReady) {
        throw 'AUTHORIZED_BAILIAN_V3_QDRANT_NOT_READY'
    }

    $databaseUrl = (
        "postgresql+psycopg://postgres:$postgresPassword@127.0.0.1:$postgresPort/$databaseName"
    )
    $env:DATABASE_URL = $databaseUrl
    $env:TEST_DATABASE_URL = $databaseUrl
    $env:TEST_QDRANT_URL = "http://127.0.0.1:$qdrantPort"
    $env:FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS = 'RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE'
    $env:FINAUDIT_LIVE_BAILIAN_SYNTHETIC_BENCHMARK = 'RUN_BAILIAN_V3_AUTHORIZED_20260820'
    $env:FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY = 'REUSE_REPOSITORY_BAILIAN_KEY'
    $env:EMBEDDING_API_KEY = ''

    & $backendPython -m alembic -c (Join-Path $projectRoot 'backend\alembic.ini') upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw 'AUTHORIZED_BAILIAN_V3_MIGRATION_FAILED'
    }
    $null = Invoke-Docker -Arguments @(
        'exec', $postgresName,
        'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1',
        '-c', "COMMENT ON DATABASE $databaseName IS 'finaudit:disposable-migration-test';"
    )

    if ($PreflightOnly) {
        $runnerExitCode = 0
        $runnerResult = [ordered]@{
            status = 'preflight_passed'
            provider_request_count = 0
            input_tokens = 0
            billed_cost_microunits = 0
        }
    }
    else {
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $backendPython
        $startInfo.Arguments = '"' + $runnerPath + '"'
        $startInfo.WorkingDirectory = $projectRoot
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw 'AUTHORIZED_BAILIAN_V3_RUNNER_START_FAILED'
        }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $runnerExitCode = $process.ExitCode
        $runnerStderrPresent = [bool]$stderr
        if (-not $stdout.Trim()) {
            throw 'AUTHORIZED_BAILIAN_V3_RUNNER_OUTPUT_INVALID'
        }
        $runnerResult = $stdout.Trim() | ConvertFrom-Json
    }
}
finally {
    Restore-ManagedEnvironment
    if ($qdrantCreated) {
        & docker rm --force $qdrantName *> $null
    }
    if ($postgresCreated) {
        & docker rm --force $postgresName *> $null
    }
    $cleanupContainerCount = @(& docker ps -aq --filter "label=finaudit.live-benchmark-v3.run=$runId").Count
    $cleanupNetworkCount = @(& docker network ls -q --filter "label=finaudit.live-benchmark-v3.run=$runId").Count
}

$wrapperResult = [ordered]@{
    schema_version = 'authorized-bailian-v3-wrapper-result-v1'
    run_id = $runId
    preflight_only = [bool]$PreflightOnly
    runner_exit_code = $runnerExitCode
    runner_stderr_present = $runnerStderrPresent
    runner_result = $runnerResult
    cleanup_container_count = $cleanupContainerCount
    cleanup_network_count = $cleanupNetworkCount
    managed_environment_residual_count = @(
        $managedEnvironmentNames | Where-Object {
            $prior = $priorEnvironment[$_]
            $currentPresent = Test-Path "Env:$_"
            $currentValue = [Environment]::GetEnvironmentVariable($_, 'Process')
            $currentPresent -ne $prior.Present -or $currentValue -ne $prior.Value
        }
    ).Count
}
Write-Output ($wrapperResult | ConvertTo-Json -Depth 8 -Compress)
if (
    $runnerExitCode -ne 0 -or
    $cleanupContainerCount -ne 0 -or
    $cleanupNetworkCount -ne 0 -or
    $wrapperResult.managed_environment_residual_count -ne 0
) {
    exit 1
}
