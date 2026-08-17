[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BackupDirectory,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,39}$')]
    [string]$TargetProjectName,

    [ValidateRange(1024, 65535)]
    [int]$HttpsPort = 9443
)

$ErrorActionPreference = 'Stop'
$markerName = '.finaudit-local-runtime.json'
$secretNames = @(
    'secret_key', 'database_url', 'redis_url', 'celery_broker_url',
    'celery_result_backend', 'postgres_password', 'redis_password', 'redis_config',
    'minio_root_user', 'minio_root_password', 'minio_access_key', 'minio_secret_key',
    'minio_worker_access_key', 'minio_worker_secret_key', 'llm_api_key',
    'embedding_api_key', 'metrics_internal_token', 'auth_jwt_private_key',
    'auth_jwt_public_keyring', 'bootstrap_admin_password', 'tls_certificate',
    'tls_private_key'
)

function Invoke-Docker([string[]]$Arguments, [string]$FailureMessage) {
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorPreference
    }
    if ($exitCode -ne 0) {
        throw $FailureMessage
    }
    return (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
}

function Test-IsExactChild([string]$Parent, [string]$Child) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $childFull = [IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith(
        $parentFull + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Write-Utf8File([string]$Path, [string[]]$Lines) {
    [IO.File]::WriteAllLines($Path, $Lines, [Text.UTF8Encoding]::new($false))
}

function ConvertFrom-GateOutput([string]$Output) {
    $result = @{}
    foreach ($line in ($Output -split '\r?\n')) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') {
            $result[$Matches[1]] = $Matches[2]
        }
    }
    return $result
}

function Get-DatabaseCounts([string[]]$ComposeArguments, [string[]]$Tables) {
    $counts = @{}
    foreach ($table in $Tables) {
        if ($table -notmatch '^[a-z][a-z0-9_]{0,62}$') {
            throw 'The backup manifest contains an invalid table name.'
        }
        $value = Invoke-Docker (
            $ComposeArguments + @(
                'exec', '-T', 'postgresql', 'psql', '--username=finaudit',
                '--dbname=finaudit', '--tuples-only', '--no-align', '--command',
                "SELECT COUNT(*) FROM public.$table;"
            )
        ) "Unable to count restored PostgreSQL table $table."
        $parsed = 0L
        if (-not [long]::TryParse($value.Trim(), [ref]$parsed)) {
            throw "PostgreSQL returned an invalid row count for $table."
        }
        $counts[$table] = $parsed
    }
    return $counts
}

function Wait-ContainerHealthy([string]$ContainerId, [string]$ServiceName) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $status = Invoke-Docker @(
            'inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}',
            $ContainerId
        ) "Unable to inspect $ServiceName health."
        if ($status -ceq 'healthy') {
            return
        }
        if ($status -ceq 'unhealthy') {
            throw "$ServiceName became unhealthy during restore."
        }
        Start-Sleep -Seconds 2
    }
    throw "$ServiceName did not become healthy during restore."
}

function Wait-LocalReadiness([int]$Port) {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.ServerCertificateCustomValidationCallback =
        [Net.Http.HttpClientHandler]::DangerousAcceptAnyServerCertificateValidator
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(5)
    try {
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            try {
                $response = $client.GetAsync(
                    "https://localhost:$Port/health/dependencies"
                ).GetAwaiter().GetResult()
                if ($response.IsSuccessStatusCode) {
                    $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() |
                        ConvertFrom-Json
                    $readiness = $payload.data
                    $failed = @(
                        $readiness.dependencies |
                            Where-Object { $_.required -eq $true -and $_.status -cne 'ok' }
                    )
                    if ($readiness.status -ceq 'ok' -and $failed.Count -eq 0) {
                        return
                    }
                }
            }
            catch {
                # 新恢复栈启动期间连接失败是预期状态。
            }
            Start-Sleep -Seconds 2
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
    throw 'The restored stack did not reach dependency-ready state.'
}

if (-not [IO.Path]::IsPathFullyQualified($BackupDirectory)) {
    throw 'BackupDirectory must be an absolute path.'
}
$backupFullPath = [IO.Path]::GetFullPath($BackupDirectory)
$manifestPath = Join-Path $backupFullPath 'manifest.json'
if (
    -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $backupFullPath '.finaudit-backup-incomplete'))
) {
    throw 'The backup is incomplete or missing its manifest.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -cne 'finaudit-local-authoritative-backup-v1') {
    throw 'The backup manifest schema is unsupported.'
}
$sourceProjectName = [string]$manifest.sourceProjectName
if (
    $sourceProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,39}$' -or
    $TargetProjectName -ceq $sourceProjectName
) {
    throw 'Restore requires a new project name distinct from the source project.'
}
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
if (
    (Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$manifest.composeSha256).ToLowerInvariant()
) {
    throw 'The current Compose profile differs from the profile recorded by the backup.'
}
$databaseDumpPath = Join-Path $backupFullPath ([string]$manifest.database.file)
$minioArchivePath = Join-Path $backupFullPath ([string]$manifest.minio.file)
if (
    -not (Test-Path -LiteralPath $databaseDumpPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $minioArchivePath -PathType Leaf)
) {
    throw 'The backup payload is incomplete.'
}
if (
    (Get-FileHash -LiteralPath $databaseDumpPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$manifest.database.sha256).ToLowerInvariant() -or
    (Get-FileHash -LiteralPath $minioArchivePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$manifest.minio.sha256).ToLowerInvariant()
) {
    throw 'A backup payload hash does not match the manifest.'
}

$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'The local application data directory is unavailable.'
}
$runtimeBase = [IO.Path]::GetFullPath((Join-Path $localAppData 'FinAuditAgent\runtime'))
$sourceRuntime = [IO.Path]::GetFullPath((Join-Path $runtimeBase $sourceProjectName))
$targetRuntime = [IO.Path]::GetFullPath((Join-Path $runtimeBase $TargetProjectName))
if (
    -not (Test-IsExactChild $runtimeBase $sourceRuntime) -or
    -not (Test-IsExactChild $runtimeBase $targetRuntime) -or
    (Test-Path -LiteralPath $targetRuntime)
) {
    throw 'The source runtime is invalid or the target runtime already exists.'
}
$sourceMarkerPath = Join-Path $sourceRuntime $markerName
$sourceEnvPath = Join-Path $sourceRuntime 'compose.env'
if (
    -not (Test-Path -LiteralPath $sourceMarkerPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $sourceEnvPath -PathType Leaf)
) {
    throw 'The source runtime secrets are unavailable; they are intentionally excluded from backups.'
}
$sourceMarker = Get-Content -LiteralPath $sourceMarkerPath -Raw | ConvertFrom-Json
if (
    $sourceMarker.schemaVersion -cne 'finaudit-local-runtime-v1' -or
    $sourceMarker.projectName -cne $sourceProjectName
) {
    throw 'The source runtime ownership marker is invalid.'
}
foreach ($secretName in $secretNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRuntime $secretName) -PathType Leaf)) {
        throw 'The source runtime secret set is incomplete.'
    }
}

$existingContainers = Invoke-Docker @(
    'ps', '--all', '--filter', "label=com.docker.compose.project=$TargetProjectName", '--quiet'
) 'Unable to inspect the target Compose project.'
$existingVolumes = Invoke-Docker @(
    'volume', 'ls', '--filter', "label=com.docker.compose.project=$TargetProjectName", '--quiet'
) 'Unable to inspect the target Compose volumes.'
if (-not [string]::IsNullOrWhiteSpace($existingContainers + $existingVolumes)) {
    throw 'The target Compose project already owns containers or volumes.'
}

$sourceEnv = @{}
foreach ($line in (Get-Content -LiteralPath $sourceEnvPath)) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') {
        $sourceEnv[$Matches[1]] = $Matches[2]
    }
}
$imageRevision = [string]$sourceEnv['FINAUDIT_IMAGE_REVISION']
if ([string]::IsNullOrWhiteSpace($imageRevision)) {
    throw 'The source Compose environment is invalid.'
}
$backendImage = "finaudit-backend-local:$imageRevision"

$stagingRuntime = [IO.Path]::GetFullPath(
    (Join-Path $runtimeBase "$TargetProjectName.initializing.$([Guid]::NewGuid().ToString('N'))")
)
$composeArguments = $null
$restoreCreated = $false
try {
    $null = New-Item -ItemType Directory -Path $stagingRuntime
    foreach ($secretName in $secretNames) {
        Copy-Item -LiteralPath (Join-Path $sourceRuntime $secretName) `
            -Destination (Join-Path $stagingRuntime $secretName)
    }
    $stagingMount = $stagingRuntime.Replace('\', '/')
    $containerSecretPaths = @($secretNames | ForEach-Object { "/runtime/$_" })
    $null = Invoke-Docker (@(
        'run', '--rm', '--user', '0:0', '--network', 'none',
        '--mount', "type=bind,src=$stagingMount,dst=/runtime",
        $backendImage, 'sh', '-c',
        'chown 0:10001 "$@" && chmod 0440 "$@" && chown 999:1000 /runtime/redis_config /runtime/redis_password && chmod 0400 /runtime/redis_config /runtime/redis_password',
        'finaudit-secret-permissions'
    ) + $containerSecretPaths) 'Unable to apply restored runtime secret permissions.'
    $targetMarker = [ordered]@{
        schemaVersion = 'finaudit-local-runtime-v1'
        projectName = $TargetProjectName
        organizationName = [string]$sourceMarker.organizationName
        organizationUscc = [string]$sourceMarker.organizationUscc
        organizationTaxNumber = [string]$sourceMarker.organizationTaxNumber
        adminUsername = [string]$sourceMarker.adminUsername
        adminDisplayName = [string]$sourceMarker.adminDisplayName
        createdAtUtc = [DateTimeOffset]::UtcNow.ToString('O')
        secretFileCount = $secretNames.Count
        restoredFromBackupId = [string]$manifest.backupId
    }
    Write-Utf8File (Join-Path $stagingRuntime $markerName) @(
        ($targetMarker | ConvertTo-Json -Depth 4)
    )
    $targetForCompose = $targetRuntime.Replace('\', '/')
    Write-Utf8File (Join-Path $stagingRuntime 'compose.env') @(
        "FINAUDIT_RUNTIME_DIR=$targetForCompose",
        "FINAUDIT_HTTPS_PORT=$HttpsPort",
        "FINAUDIT_IMAGE_REVISION=$imageRevision",
        "BOOTSTRAP_ORGANIZATION_NAME=$($sourceMarker.organizationName)",
        "BOOTSTRAP_ORGANIZATION_USCC=$($sourceMarker.organizationUscc)",
        "BOOTSTRAP_ORGANIZATION_TAX_NUMBER=$($sourceMarker.organizationTaxNumber)",
        "BOOTSTRAP_ADMIN_USERNAME=$($sourceMarker.adminUsername)",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME=$($sourceMarker.adminDisplayName)"
    )
    Move-Item -LiteralPath $stagingRuntime -Destination $targetRuntime
    $restoreCreated = $true
    $targetEnvPath = Join-Path $targetRuntime 'compose.env'
    $composeArguments = @(
        'compose', '--project-name', $TargetProjectName, '--env-file', $targetEnvPath,
        '--file', $composePath
    )
    $null = Invoke-Docker ($composeArguments + @('config', '--quiet')) `
        'The restore Compose profile is invalid.'
    $null = Invoke-Docker (
        $composeArguments + @('create', 'postgresql', 'redis', 'minio', 'qdrant')
    ) 'Unable to create the isolated restore data services.'

    $minioVolume = Invoke-Docker @(
        'volume', 'ls', '--filter', "label=com.docker.compose.project=$TargetProjectName",
        '--filter', 'label=com.docker.compose.volume=minio_data', '--format', '{{.Name}}'
    ) 'Unable to identify the isolated restore MinIO volume.'
    if ([string]::IsNullOrWhiteSpace($minioVolume) -or $minioVolume -match '\r?\n') {
        throw 'The isolated restore MinIO volume identity is ambiguous.'
    }
    $backupMount = $backupFullPath.Replace('\', '/')
    $archiveOutput = Invoke-Docker @(
        'run', '--rm', '--user', '0:0', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--mount', "type=volume,src=$minioVolume,dst=/volume",
        '--mount', "type=bind,src=$backupMount,dst=/backup,readonly",
        '--env', 'FINAUDIT_VOLUME_ARCHIVE_MODE=extract',
        '--env', 'FINAUDIT_VOLUME_ROOT=/volume',
        '--env', 'FINAUDIT_VOLUME_ARCHIVE=/backup/minio-data.tar.gz',
        $backendImage, 'python', '/app/scripts/local_volume_archive.py'
    ) 'Unable to restore the MinIO volume archive.'
    $archiveGate = ConvertFrom-GateOutput $archiveOutput
    if (
        $archiveGate['LOCAL_VOLUME_ARCHIVE'] -cne 'PASS' -or
        ([string]$archiveGate['LOCAL_VOLUME_SHA256']).ToLowerInvariant() -cne
            ([string]$manifest.minio.volumeSha256).ToLowerInvariant() -or
        [long]$archiveGate['LOCAL_VOLUME_FILES'] -ne [long]$manifest.minio.fileCount -or
        [long]$archiveGate['LOCAL_VOLUME_BYTES'] -ne [long]$manifest.minio.contentBytes
    ) {
        throw 'The restored MinIO volume does not match the authoritative backup.'
    }

    $null = Invoke-Docker ($composeArguments + @('up', '--detach', 'postgresql')) `
        'Unable to start the isolated restore PostgreSQL service.'
    $postgresContainerId = Invoke-Docker ($composeArguments + @('ps', '--quiet', 'postgresql')) `
        'Unable to identify the isolated restore PostgreSQL container.'
    Wait-ContainerHealthy $postgresContainerId 'PostgreSQL'
    $null = Invoke-Docker @(
        'cp', $databaseDumpPath,
        "${postgresContainerId}:/tmp/finaudit-authoritative.dump"
    ) 'Unable to copy the PostgreSQL backup into the isolated restore container.'
    $null = Invoke-Docker (
        $composeArguments + @(
            'exec', '-T', 'postgresql', 'pg_restore', '--username=finaudit',
            '--dbname=finaudit', '--no-owner', '--no-privileges', '--exit-on-error',
            '/tmp/finaudit-authoritative.dump'
        )
    ) 'PostgreSQL restore failed.'
    $null = Invoke-Docker (
        $composeArguments + @(
            'exec', '-T', 'postgresql', 'rm', '-f', '/tmp/finaudit-authoritative.dump'
        )
    ) 'Unable to remove the exact temporary PostgreSQL restore payload.'

    $tableNames = @($manifest.database.rows.PSObject.Properties.Name)
    $restoredCounts = Get-DatabaseCounts $composeArguments $tableNames
    foreach ($tableName in $tableNames) {
        if ([long]$restoredCounts[$tableName] -ne [long]$manifest.database.rows.$tableName) {
            throw "The restored PostgreSQL row count differs for $tableName."
        }
    }

    $null = Invoke-Docker ($composeArguments + @('up', '--detach')) `
        'Unable to start the isolated restored application stack.'
    Wait-LocalReadiness $HttpsPort
}
catch {
    $restoreError = $_
    if ($null -ne $composeArguments) {
        try {
            $null = Invoke-Docker ($composeArguments + @('down', '--volumes', '--remove-orphans')) `
                'Unable to remove the failed isolated restore stack.'
        }
        catch {
            # 保留原始恢复错误；下方只删除经精确归属验证的新建运行目录。
        }
    }
    if ($restoreCreated -and (Test-Path -LiteralPath $targetRuntime)) {
        $resolvedTarget = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $targetRuntime).Path)
        $targetMarkerPath = Join-Path $resolvedTarget $markerName
        if (
            (Test-IsExactChild $runtimeBase $resolvedTarget) -and
            ([IO.Path]::GetFileName($resolvedTarget)) -ceq $TargetProjectName -and
            (Test-Path -LiteralPath $targetMarkerPath -PathType Leaf)
        ) {
            $ownedMarker = Get-Content -LiteralPath $targetMarkerPath -Raw | ConvertFrom-Json
            if (
                $ownedMarker.projectName -ceq $TargetProjectName -and
                $ownedMarker.restoredFromBackupId -ceq [string]$manifest.backupId
            ) {
                Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
            }
        }
    }
    elseif (Test-Path -LiteralPath $stagingRuntime) {
        $resolvedStaging = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $stagingRuntime).Path)
        if (
            (Test-IsExactChild $runtimeBase $resolvedStaging) -and
            ([IO.Path]::GetFileName($resolvedStaging)).StartsWith(
                "$TargetProjectName.initializing.",
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
        }
    }
    throw $restoreError
}

Write-Output 'LOCAL_STACK_RESTORE=PASS'
Write-Output "LOCAL_STACK_RESTORE_PROJECT=$TargetProjectName"
Write-Output "LOCAL_STACK_RESTORE_URL=https://localhost:$HttpsPort"
Write-Output "LOCAL_STACK_RESTORE_RUNTIME_DIR=$targetRuntime"
Write-Output 'LOCAL_STACK_RESTORE_POSTGRESQL=VERIFIED_ROW_COUNTS'
Write-Output 'LOCAL_STACK_RESTORE_MINIO=VERIFIED_VOLUME_DIGEST'
Write-Output 'LOCAL_STACK_RESTORE_REDIS=REBUILT'
Write-Output 'LOCAL_STACK_RESTORE_QDRANT=REBUILT'
Write-Output 'LOCAL_STACK_RESTORE_CLAMAV=REHYDRATED_FROM_PINNED_IMAGE'
Write-Output 'LOCAL_STACK_RESTORE_PASSWORD=USE_EXISTING_SOURCE_ADMIN_PASSWORD'
