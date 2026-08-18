[CmdletBinding()]
param(
    [string]$BackendPythonPath,
    [string]$DockerPath,
    [string]$Image = 'postgres:16-alpine',
    [ValidateSet('Full', 'Retrieval', 'Audit', 'Contract', 'File', 'AI', 'LiveAI', 'LiveEmbedding')]
    [string]$Scope = 'Full'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($Image) -or
    $Image.Length -gt 255 -or
    $Image -notmatch '^[\x21-\x7e]+$' -or
    $Image.StartsWith('-')) {
    throw 'PostgreSQL image reference is invalid.'
}

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$backendRoot = Join-Path $projectRoot 'backend'

if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $backendRoot '.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}
$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw 'Backend Python executable is missing.'
}

if ([string]::IsNullOrWhiteSpace($DockerPath)) {
    $DockerPath = (Get-Command docker -ErrorAction Stop).Source
}
elseif (-not [System.IO.Path]::IsPathRooted($DockerPath)) {
    $DockerPath = Join-Path $projectRoot $DockerPath
}
$docker = [System.IO.Path]::GetFullPath($DockerPath)
if (-not (Test-Path -LiteralPath $docker -PathType Leaf)) {
    throw 'Docker executable is missing.'
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    [pscustomobject]@{
        ExitCode = $exitCode
        Output = [string[]]@($output | ForEach-Object { $_.ToString() })
    }
}

function Test-DockerObjectIsAbsent {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$ObjectReference
    )

    $messages = @(
        $Result.Output |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($Result.ExitCode -eq 0 -or $messages.Count -ne 1) {
        return $false
    }

    $escapedObjectReference = [regex]::Escape($ObjectReference)
    $message = $messages[0]
    return $message -match (
        '^Error(?: response from daemon)?: No such (?:object|container): ' +
        $escapedObjectReference + '$'
    )
}

$pythonPreflightSentinel = 'FINAUDIT_POSTGRESQL_PYTHON_PREFLIGHT_V1'
$pythonPreflight = Invoke-ExternalCommand -FilePath $backendPython -Arguments @(
    '-I', '-c',
    (
        'import sys; import alembic, psycopg, pytest, sqlalchemy; ' +
        'assert sys.version_info[:2] == (3, 10); ' +
        "print('$pythonPreflightSentinel')"
    )
)
if ($pythonPreflight.ExitCode -ne 0 -or
    $pythonPreflight.Output.Count -ne 1 -or
    $pythonPreflight.Output[0].Trim() -cne $pythonPreflightSentinel) {
    throw 'Backend Python preflight failed.'
}

function New-RandomHex {
    param([ValidateRange(16, 128)][int]$ByteCount = 32)

    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

$serverResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
    'version', '--format', '{{.Server.Version}}'
)
if ($serverResult.ExitCode -ne 0) {
    throw 'Docker daemon is not available; this explicit gate never starts it.'
}

$imageResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
    'image', 'inspect', $Image, '--format', '{{.Id}}'
)
$resolvedImageId = $null
$imageIds = @(
    $imageResult.Output |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if ($imageResult.ExitCode -eq 0 -and
    $imageIds.Count -eq 1 -and
    $imageIds[0] -match '^sha256:[0-9a-f]{64}$') {
    $resolvedImageId = $imageIds[0]
}
else {
    # Docker Desktop 29.x may list a cached tag while its first tag-based inspect
    # transiently reports it missing. Resolve only the unique local immutable ID;
    # never pull or accept a truncated/ambiguous identity.
    $listedImageResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
        'image', 'ls', '--no-trunc', '--format', '{{.ID}}', $Image
    )
    $listedImageIds = @(
        $listedImageResult.Output |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    if ($listedImageResult.ExitCode -ne 0 -or
        $listedImageIds.Count -ne 1 -or
        $listedImageIds[0] -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'Cached PostgreSQL 16 image is missing. This gate never pulls images.'
    }
    $resolvedImageResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
        'image', 'inspect', $listedImageIds[0], '--format', '{{.Id}}'
    )
    $resolvedOutputs = @(
        $resolvedImageResult.Output |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($resolvedImageResult.ExitCode -ne 0 -or
        $resolvedOutputs.Count -ne 1 -or
        $resolvedOutputs[0] -cne $listedImageIds[0]) {
        throw 'Cached PostgreSQL 16 image identity could not be verified.'
    }
    $resolvedImageId = $listedImageIds[0]
}

$runId = [System.Guid]::NewGuid().ToString('N')
$containerName = "finaudit-pg16-current-head-$runId"
$purposeLabel = 'com.finaudit.test-purpose=postgresql-current-head'
$runLabel = "com.finaudit.run-id=$runId"
$databaseName = 'finaudit_base005_test'
$databaseUser = 'finaudit_test'
$databasePassword = New-RandomHex
$containerId = $null
$runAttempted = $false
$serverVersion = $null
$testOutputs = [System.Collections.Generic.List[string]]::new()
$testDatabaseUrlWasPresent = Test-Path Env:TEST_DATABASE_URL
$testDatabaseUrl = if ($testDatabaseUrlWasPresent) {
    [System.Environment]::GetEnvironmentVariable('TEST_DATABASE_URL', 'Process')
}
else {
    $null
}
$confirmationWasPresent = Test-Path Env:FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS
$confirmation = if ($confirmationWasPresent) {
    [System.Environment]::GetEnvironmentVariable(
        'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS',
        'Process'
    )
}
else {
    $null
}

try {
    $postgresPasswordWasPresent = Test-Path Env:POSTGRES_PASSWORD
    $postgresPassword = if ($postgresPasswordWasPresent) {
        [System.Environment]::GetEnvironmentVariable('POSTGRES_PASSWORD', 'Process')
    }
    else {
        $null
    }
    try {
        [System.Environment]::SetEnvironmentVariable(
            'POSTGRES_PASSWORD', $databasePassword, 'Process'
        )
        $runAttempted = $true
        $runResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
            'run', '--pull', 'never', '--rm', '--detach',
            '--label', $purposeLabel,
            '--label', $runLabel,
            '--name', $containerName,
            '--env', "POSTGRES_USER=$databaseUser",
            '--env', 'POSTGRES_PASSWORD',
            '--env', "POSTGRES_DB=$databaseName",
            '--publish', '127.0.0.1::5432',
            '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,size=1g',
            $resolvedImageId
        )
    }
    finally {
        if ($postgresPasswordWasPresent) {
            [System.Environment]::SetEnvironmentVariable(
                'POSTGRES_PASSWORD', $postgresPassword, 'Process'
            )
        }
        else {
            [System.Environment]::SetEnvironmentVariable('POSTGRES_PASSWORD', $null, 'Process')
        }
    }
    if ($runResult.ExitCode -ne 0 -or $runResult.Output.Count -ne 1) {
        throw 'Failed to create the isolated PostgreSQL 16 container.'
    }
    $runContainerId = $runResult.Output[0].Trim()
    if ($runContainerId -notmatch '^[0-9a-f]{64}$') {
        throw 'Docker returned an invalid container identity.'
    }
    $containerId = $runContainerId

    $ready = $false
    $deadline = [System.DateTimeOffset]::UtcNow.AddSeconds(60)
    while ([System.DateTimeOffset]::UtcNow -lt $deadline) {
        $readyResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
            'exec', $containerId, 'pg_isready', '-U', $databaseUser, '-d', $databaseName
        )
        if ($readyResult.ExitCode -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw 'The isolated PostgreSQL 16 container did not become ready.'
    }

    $versionResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
        'exec', $containerId, 'psql', '-U', $databaseUser, '-d', $databaseName,
        '-Atc', 'SHOW server_version_num'
    )
    if ($versionResult.ExitCode -ne 0 -or $versionResult.Output.Count -ne 1) {
        throw 'Could not verify the PostgreSQL server version.'
    }
    $serverVersionNumber = 0
    if (-not [int]::TryParse($versionResult.Output[0].Trim(), [ref]$serverVersionNumber) -or
        $serverVersionNumber -lt 160000 -or $serverVersionNumber -ge 170000) {
        throw 'The cached image is not PostgreSQL major version 16.'
    }
    $serverVersion = $versionResult.Output[0].Trim()

    $commentResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
        'exec', $containerId, 'psql', '-U', $databaseUser, '-d', 'postgres',
        '-v', 'ON_ERROR_STOP=1', '-c',
        "COMMENT ON DATABASE $databaseName IS 'finaudit:disposable-migration-test'"
    )
    if ($commentResult.ExitCode -ne 0) {
        throw 'Could not mark the isolated database as disposable.'
    }

    $portResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
        'port', $containerId, '5432/tcp'
    )
    if ($portResult.ExitCode -ne 0 -or $portResult.Output.Count -ne 1 -or
        $portResult.Output[0].Trim() -notmatch '^127\.0\.0\.1:(?<port>[0-9]{1,5})$') {
        throw 'Docker did not bind PostgreSQL to one random IPv4 loopback port.'
    }
    $hostPort = [int]$Matches.port
    if ($hostPort -lt 1 -or $hostPort -gt 65535) {
        throw 'Docker returned an invalid PostgreSQL host port.'
    }

    $databaseUrl = (
        "postgresql+psycopg://${databaseUser}:${databasePassword}" +
        "@127.0.0.1:${hostPort}/${databaseName}"
    )
    [System.Environment]::SetEnvironmentVariable('TEST_DATABASE_URL', $databaseUrl, 'Process')
    [System.Environment]::SetEnvironmentVariable(
        'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS',
        'RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE',
        'Process'
    )

    Push-Location $backendRoot
    try {
        $testTargets = if ($Scope -eq 'Retrieval') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip',
                'tests/integration/database/test_knowledge_runtime.py'
            )
        }
        elseif ($Scope -eq 'Audit') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip',
                'tests/integration/database/test_audit_runtime_migration.py',
                'tests/integration/database/test_audit_management_runtime.py'
            )
        }
        elseif ($Scope -eq 'Contract') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip',
                'tests/integration/database/test_contract_extraction_management.py'
            )
        }
        elseif ($Scope -eq 'File') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip',
                'tests/integration/database/test_file_intake_service.py',
                'tests/integration/database/test_file_job_executor.py'
            )
        }
        elseif ($Scope -eq 'AI') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip',
                'tests/integration/database/test_migrations.py::test_ai_generated_fact_columns_and_constraints_round_trip',
                'tests/integration/database/test_migrations.py::test_currency_neutral_ai_cost_migration_preserves_v1_and_guards_v2',
                'tests/integration/database/test_ai_call_audit_runtime.py',
                'tests/integration/database/test_live_ai_extraction_runtime.py'
            )
        }
        elseif ($Scope -eq 'LiveAI') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip'
            )
        }
        elseif ($Scope -eq 'LiveEmbedding') {
            @(
                'tests/integration/database/test_migrations.py::test_current_base005_migration_round_trip'
            )
        }
        else {
            @('tests/integration/database')
        }
        $runCount = if ($Scope -eq 'Full') { 2 } else { 1 }
        foreach ($runNumber in 1..$runCount) {
            $testArguments = @('-m', 'pytest') + $testTargets + @('-q')
            $testResult = Invoke-ExternalCommand -FilePath $backendPython -Arguments $testArguments
            foreach ($line in $testResult.Output) {
                $testOutputs.Add(
                    ($line -replace [regex]::Escape($databasePassword), '[REDACTED]')
                )
            }
            if ($testResult.ExitCode -ne 0) {
                $testOutputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
                throw "PostgreSQL current-head verification failed on run $runNumber."
            }
            $testOutputs.Add("POSTGRESQL_CURRENT_HEAD_RUN=$runNumber status=ok")
        }
        if ($Scope -eq 'LiveAI') {
            $liveSmoke = Invoke-ExternalCommand -FilePath $backendPython -Arguments @(
                '-I', (Join-Path $projectRoot 'scripts/smoke_live_minimax_contract.py')
            )
            foreach ($line in $liveSmoke.Output) {
                $testOutputs.Add(
                    ($line -replace [regex]::Escape($databasePassword), '[REDACTED]')
                )
            }
            if ($liveSmoke.ExitCode -ne 0) {
                $testOutputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
                throw 'Live AI contract smoke failed.'
            }
        }
        elseif ($Scope -eq 'LiveEmbedding') {
            $liveSmoke = Invoke-ExternalCommand -FilePath $backendPython -Arguments @(
                '-I', (Join-Path $projectRoot 'scripts/smoke_live_bailian_embedding.py')
            )
            foreach ($line in $liveSmoke.Output) {
                $testOutputs.Add(
                    ($line -replace [regex]::Escape($databasePassword), '[REDACTED]')
                )
            }
            if ($liveSmoke.ExitCode -ne 0) {
                $testOutputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
                throw 'Live Bailian embedding smoke failed.'
            }
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($testDatabaseUrlWasPresent) {
        [System.Environment]::SetEnvironmentVariable(
            'TEST_DATABASE_URL', $testDatabaseUrl, 'Process'
        )
    }
    else {
        [System.Environment]::SetEnvironmentVariable('TEST_DATABASE_URL', $null, 'Process')
    }
    if ($confirmationWasPresent) {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS', $confirmation, 'Process'
        )
    }
    else {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS', $null, 'Process'
        )
    }

    if ($runAttempted) {
        $cleanupReference = if ([string]::IsNullOrWhiteSpace($containerId)) {
            $containerName
        }
        else {
            $containerId
        }
        $identityResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
            'inspect', $cleanupReference, '--format', '{{.Id}}|{{json .Config.Labels}}'
        )
        if ($identityResult.ExitCode -ne 0) {
            $existenceResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
                'inspect', $cleanupReference, '--format', '{{.Id}}'
            )
            if ($existenceResult.ExitCode -eq 0) {
                throw 'Could not verify the isolated PostgreSQL container labels.'
            }
            if (-not (
                Test-DockerObjectIsAbsent `
                    -Result $existenceResult `
                    -ObjectReference $cleanupReference
            )) {
                throw 'Could not confirm that the isolated PostgreSQL container is absent.'
            }
        }
        elseif ($identityResult.Output.Count -ne 1 -or
            $identityResult.Output[0].Trim() -notmatch '^(?<id>[0-9a-f]{64})\|(?<labels>\{.*\})$') {
            throw 'Docker returned an invalid cleanup identity.'
        }
        else {
            $resolvedContainerId = $Matches.id
            $labels = $Matches.labels | ConvertFrom-Json
            if ((-not [string]::IsNullOrWhiteSpace($containerId) -and
                    $resolvedContainerId -ne $containerId) -or
                $labels.'com.finaudit.test-purpose' -ne 'postgresql-current-head' -or
                $labels.'com.finaudit.run-id' -ne $runId) {
                throw 'Refusing to clean up a container whose identity or labels changed.'
            }
            $removeResult = Invoke-ExternalCommand -FilePath $docker -Arguments @(
                'rm', '--force', $resolvedContainerId
            )
            if ($removeResult.ExitCode -ne 0) {
                throw 'Failed to remove the isolated PostgreSQL test container.'
            }
        }
    }
}

$testOutputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
"POSTGRESQL_IMAGE=$Image"
"POSTGRESQL_IMAGE_ID=$resolvedImageId"
"POSTGRESQL_SERVER_VERSION_NUM=$serverVersion"
"POSTGRESQL_SCOPE=$Scope"
'POSTGRESQL_CURRENT_HEAD=PASS'
