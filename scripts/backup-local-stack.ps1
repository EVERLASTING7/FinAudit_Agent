[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,39}$')]
    [string]$ProjectName = 'finaudit-local',

    [string]$BackupDirectory
)

$ErrorActionPreference = 'Stop'
$markerName = '.finaudit-local-runtime.json'
$authoritativeTables = @(
    'organizations',
    'users',
    'knowledge_bases',
    'files',
    'async_jobs',
    'contracts',
    'contract_fields',
    'invoices',
    'suppliers',
    'contract_invoices',
    'audit_tasks',
    'audit_risks',
    'audit_reports',
    'policy_documents',
    'document_chunks',
    'qa_queries',
    'operation_logs'
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

function Get-DatabaseCounts([string[]]$ComposeArguments) {
    $counts = [ordered]@{}
    foreach ($table in $authoritativeTables) {
        $value = Invoke-Docker (
            $ComposeArguments + @(
                'exec',
                '-T',
                'postgresql',
                'psql',
                '--username=finaudit',
                '--dbname=finaudit',
                '--tuples-only',
                '--no-align',
                '--command',
                "SELECT COUNT(*) FROM public.$table;"
            )
        ) "Unable to count PostgreSQL table $table."
        $parsed = 0L
        if (-not [long]::TryParse($value.Trim(), [ref]$parsed)) {
            throw "PostgreSQL returned an invalid row count for $table."
        }
        $counts[$table] = $parsed
    }
    return $counts
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
                # 备份结束后的服务恢复期间连接失败是预期状态。
            }
            Start-Sleep -Seconds 2
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
    throw 'The local stack did not recover dependency readiness after backup.'
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'The local application data directory is unavailable.'
}
$runtimeBase = [IO.Path]::GetFullPath((Join-Path $localAppData 'FinAuditAgent\runtime'))
$runtimeDirectory = [IO.Path]::GetFullPath((Join-Path $runtimeBase $ProjectName))
if (-not (Test-IsExactChild $runtimeBase $runtimeDirectory)) {
    throw 'The managed runtime directory escaped its approved root.'
}
$runtimeMarkerPath = Join-Path $runtimeDirectory $markerName
$composeEnvPath = Join-Path $runtimeDirectory 'compose.env'
if (
    -not (Test-Path -LiteralPath $runtimeMarkerPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $composeEnvPath -PathType Leaf)
) {
    throw 'No managed running FinAudit local stack exists for this project name.'
}
$runtimeMarker = Get-Content -LiteralPath $runtimeMarkerPath -Raw | ConvertFrom-Json
if (
    $runtimeMarker.schemaVersion -cne 'finaudit-local-runtime-v1' -or
    $runtimeMarker.projectName -cne $ProjectName
) {
    throw 'The runtime ownership marker is invalid.'
}

if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $timestamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $BackupDirectory = Join-Path $localAppData "FinAuditAgent\backups\$ProjectName\$timestamp"
}
if (-not [IO.Path]::IsPathFullyQualified($BackupDirectory)) {
    throw 'BackupDirectory must be an absolute path.'
}
$backupFullPath = [IO.Path]::GetFullPath($BackupDirectory)
if ($backupFullPath.StartsWith($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backups must stay outside the repository.'
}
if ($backupFullPath.Contains(',')) {
    throw 'BackupDirectory cannot contain a comma because Docker mount syntax would be ambiguous.'
}
if (Test-Path -LiteralPath $backupFullPath) {
    throw 'BackupDirectory already exists; backups never overwrite prior evidence.'
}
$null = New-Item -ItemType Directory -Path $backupFullPath
Write-Utf8File (Join-Path $backupFullPath '.finaudit-backup-incomplete') @(
    'finaudit-local-authoritative-backup-v1'
)

$composeArguments = @(
    'compose',
    '--project-name',
    $ProjectName,
    '--env-file',
    $composeEnvPath,
    '--file',
    $composePath
)
$runningServices = Invoke-Docker ($composeArguments + @('ps', '--services', '--status', 'running')) `
    'Unable to inspect the local Compose stack.'
$requiredRunning = @(
    'postgresql', 'redis', 'minio', 'qdrant', 'clamav', 'backend', 'worker',
    'dispatcher', 'maintenance', 'frontend'
)
foreach ($service in $requiredRunning) {
    if ($service -notin ($runningServices -split '\r?\n')) {
        throw "The local stack is not ready for backup because $service is not running."
    }
}

$composeEnv = @{}
foreach ($line in (Get-Content -LiteralPath $composeEnvPath)) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') {
        $composeEnv[$Matches[1]] = $Matches[2]
    }
}
$imageRevision = [string]$composeEnv['FINAUDIT_IMAGE_REVISION']
$httpsPort = 0
if (
    [string]::IsNullOrWhiteSpace($imageRevision) -or
    -not [int]::TryParse([string]$composeEnv['FINAUDIT_HTTPS_PORT'], [ref]$httpsPort)
) {
    throw 'The managed Compose environment is invalid.'
}
$backendImage = "finaudit-backend-local:$imageRevision"
$databaseDumpPath = Join-Path $backupFullPath 'postgresql.dump'
$minioArchivePath = Join-Path $backupFullPath 'minio-data.tar.gz'
$postgresContainerId = $null
$backupError = $null
$stackQuiesced = $false
try {
    $null = Invoke-Docker (
        $composeArguments + @('stop', 'frontend', 'backend', 'worker', 'dispatcher', 'maintenance')
    ) 'Unable to quiesce local application writers.'
    $stackQuiesced = $true
    $databaseRows = Get-DatabaseCounts $composeArguments

    $postgresContainerId = Invoke-Docker ($composeArguments + @('ps', '--quiet', 'postgresql')) `
        'Unable to identify the PostgreSQL container.'
    if ([string]::IsNullOrWhiteSpace($postgresContainerId)) {
        throw 'The PostgreSQL container identity is empty.'
    }
    $null = Invoke-Docker (
        $composeArguments + @(
            'exec',
            '-T',
            'postgresql',
            'pg_dump',
            '--username=finaudit',
            '--dbname=finaudit',
            '--format=custom',
            '--no-owner',
            '--no-privileges',
            '--file=/tmp/finaudit-authoritative.dump'
        )
    ) 'PostgreSQL backup failed.'
    $null = Invoke-Docker @(
        'cp',
        "${postgresContainerId}:/tmp/finaudit-authoritative.dump",
        $databaseDumpPath
    ) 'Unable to copy the PostgreSQL backup out of the container.'
    $null = Invoke-Docker (
        $composeArguments + @(
            'exec', '-T', 'postgresql', 'rm', '-f', '/tmp/finaudit-authoritative.dump'
        )
    ) 'Unable to remove the exact temporary PostgreSQL dump.'

    $null = Invoke-Docker ($composeArguments + @('stop', 'minio')) `
        'Unable to stop MinIO for a consistent volume snapshot.'
    $minioVolume = Invoke-Docker @(
        'volume',
        'ls',
        '--filter',
        "label=com.docker.compose.project=$ProjectName",
        '--filter',
        'label=com.docker.compose.volume=minio_data',
        '--format',
        '{{.Name}}'
    ) 'Unable to identify the MinIO volume.'
    if ([string]::IsNullOrWhiteSpace($minioVolume) -or $minioVolume -match '\r?\n') {
        throw 'The MinIO volume identity is ambiguous.'
    }
    $backupMount = $backupFullPath.Replace('\', '/')
    $archiveOutput = Invoke-Docker @(
        'run',
        '--rm',
        '--user',
        '0:0',
        '--network',
        'none',
        '--read-only',
        '--cap-drop',
        'ALL',
        '--security-opt',
        'no-new-privileges:true',
        '--mount',
        "type=volume,src=$minioVolume,dst=/volume,readonly",
        '--mount',
        "type=bind,src=$backupMount,dst=/backup",
        '--env',
        'FINAUDIT_VOLUME_ARCHIVE_MODE=create',
        '--env',
        'FINAUDIT_VOLUME_ROOT=/volume',
        '--env',
        'FINAUDIT_VOLUME_ARCHIVE=/backup/minio-data.tar.gz',
        $backendImage,
        'python',
        '/app/scripts/local_volume_archive.py'
    ) 'MinIO volume backup failed.'
    $archiveGate = ConvertFrom-GateOutput $archiveOutput
    if ($archiveGate['LOCAL_VOLUME_ARCHIVE'] -cne 'PASS') {
        throw 'MinIO volume backup did not return a PASS gate.'
    }

    $databaseHash = (Get-FileHash -LiteralPath $databaseDumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $minioHash = (Get-FileHash -LiteralPath $minioArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($minioHash -cne ([string]$archiveGate['LOCAL_ARCHIVE_SHA256']).ToLowerInvariant()) {
        throw 'The copied MinIO archive hash does not match the archive helper result.'
    }
    $manifest = [ordered]@{
        schemaVersion = 'finaudit-local-authoritative-backup-v1'
        backupId = [Guid]::NewGuid().ToString('D')
        createdAtUtc = [DateTimeOffset]::UtcNow.ToString('O')
        sourceProjectName = $ProjectName
        composeSha256 = (Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash.ToLowerInvariant()
        includesSecrets = $false
        database = [ordered]@{
            file = 'postgresql.dump'
            sha256 = $databaseHash
            bytes = (Get-Item -LiteralPath $databaseDumpPath).Length
            rows = $databaseRows
        }
        minio = [ordered]@{
            file = 'minio-data.tar.gz'
            sha256 = $minioHash
            bytes = (Get-Item -LiteralPath $minioArchivePath).Length
            volumeSha256 = ([string]$archiveGate['LOCAL_VOLUME_SHA256']).ToLowerInvariant()
            fileCount = [long]$archiveGate['LOCAL_VOLUME_FILES']
            contentBytes = [long]$archiveGate['LOCAL_VOLUME_BYTES']
        }
        derivedState = [ordered]@{
            redis = 'excluded-rebuild-on-restore'
            qdrant = 'excluded-rebuild-on-restore'
            clamavDefinitions = 'excluded-rehydrate-from-pinned-image'
        }
    }
    Write-Utf8File (Join-Path $backupFullPath 'manifest.json') @(
        ($manifest | ConvertTo-Json -Depth 8)
    )
    Remove-Item -LiteralPath (Join-Path $backupFullPath '.finaudit-backup-incomplete')
}
catch {
    $backupError = $_
}
finally {
    if ($null -ne $postgresContainerId) {
        try {
            $null = Invoke-Docker (
                $composeArguments + @(
                    'exec', '-T', 'postgresql', 'rm', '-f', '/tmp/finaudit-authoritative.dump'
                )
            ) 'Unable to clean the exact temporary PostgreSQL dump.'
        }
        catch {
            if ($null -eq $backupError) {
                $backupError = $_
            }
        }
    }
    if ($stackQuiesced) {
        try {
            $null = Invoke-Docker ($composeArguments + @('up', '--detach')) `
                'Unable to restart the local stack after backup.'
            Wait-LocalReadiness $httpsPort
        }
        catch {
            if ($null -eq $backupError) {
                $backupError = $_
            }
        }
    }
}
if ($null -ne $backupError) {
    throw $backupError
}

Write-Output 'LOCAL_STACK_BACKUP=PASS'
Write-Output "LOCAL_STACK_BACKUP_DIRECTORY=$backupFullPath"
Write-Output 'LOCAL_STACK_BACKUP_POSTGRESQL=INCLUDED'
Write-Output 'LOCAL_STACK_BACKUP_MINIO=INCLUDED'
Write-Output 'LOCAL_STACK_BACKUP_SECRETS=EXCLUDED'
Write-Output 'LOCAL_STACK_BACKUP_REDIS=REBUILD_ON_RESTORE'
Write-Output 'LOCAL_STACK_BACKUP_QDRANT=REBUILD_ON_RESTORE'
Write-Output 'LOCAL_STACK_BACKUP_CLAMAV=REHYDRATE_FROM_PINNED_IMAGE'
