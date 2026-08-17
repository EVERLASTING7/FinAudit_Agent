[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$OrganizationName,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9A-Z]{18}$')]
    [string]$OrganizationUscc,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9A-Z-]{8,32}$')]
    [string]$OrganizationTaxNumber,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9._@-]{3,64}$')]
    [string]$AdminUsername,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$AdminDisplayName,

    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,39}$')]
    [string]$ProjectName = 'finaudit-local',

    [ValidateRange(1024, 65535)]
    [int]$HttpsPort = 8443,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$')]
    [string]$ImageRevision = 'dev'
)

$ErrorActionPreference = 'Stop'
$markerName = '.finaudit-local-runtime.json'
$secretNames = @(
    'secret_key',
    'database_url',
    'redis_url',
    'celery_broker_url',
    'celery_result_backend',
    'postgres_password',
    'redis_password',
    'redis_config',
    'minio_root_user',
    'minio_root_password',
    'minio_access_key',
    'minio_secret_key',
    'minio_worker_access_key',
    'minio_worker_secret_key',
    'llm_api_key',
    'embedding_api_key',
    'metrics_internal_token',
    'auth_jwt_private_key',
    'auth_jwt_public_keyring',
    'bootstrap_admin_password',
    'tls_certificate',
    'tls_private_key'
)

function Assert-SafeDotEnvValue([string]$Name, [string]$Value, [int]$MaximumLength) {
    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value.Length -gt $MaximumLength -or
        $Value -cne $Value.Trim() -or
        $Value -match '[\r\n"''#$\\]'
    ) {
        throw "$Name contains characters that cannot be written safely to the local Compose profile."
    }
}

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
    $encoding = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllLines($Path, $Lines, $encoding)
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
                $healthResponse = $client.GetAsync("https://localhost:$Port/health").GetAwaiter().GetResult()
                $readyResponse = $client.GetAsync(
                    "https://localhost:$Port/health/dependencies"
                ).GetAwaiter().GetResult()
                if ($healthResponse.IsSuccessStatusCode -and $readyResponse.IsSuccessStatusCode) {
                    $payload = $readyResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult() |
                        ConvertFrom-Json
                    $readiness = $payload.data
                    $failedRequired = @(
                        $readiness.dependencies |
                            Where-Object { $_.required -eq $true -and $_.status -cne 'ok' }
                    )
                    if ($readiness.status -ceq 'ok' -and $failedRequired.Count -eq 0) {
                        return
                    }
                }
            }
            catch {
                # 服务启动期间连接失败是预期状态；到达总超时后统一失败。
            }
            Start-Sleep -Seconds 2
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
    throw 'The local stack did not reach dependency-ready state within 180 seconds.'
}

Assert-SafeDotEnvValue 'OrganizationName' $OrganizationName 120
Assert-SafeDotEnvValue 'AdminDisplayName' $AdminDisplayName 120

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
$backendDockerfile = Join-Path $projectRoot 'backend\Dockerfile'
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'The local application data directory is unavailable.'
}
$runtimeBase = [IO.Path]::GetFullPath((Join-Path $localAppData 'FinAuditAgent\runtime'))
$runtimeDirectory = [IO.Path]::GetFullPath((Join-Path $runtimeBase $ProjectName))
if (-not (Test-IsExactChild $runtimeBase $runtimeDirectory)) {
    throw 'The managed runtime directory escaped its approved local application data root.'
}
if ($runtimeDirectory.StartsWith($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Runtime secrets must stay outside the repository.'
}
if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is unavailable.'
}
$null = Invoke-Docker @('info', '--format', '{{.ServerVersion}}') 'Docker Engine is unavailable.'
$backendImage = "finaudit-backend-local:$ImageRevision"
$null = Invoke-Docker @(
    'build',
    '--file',
    $backendDockerfile,
    '--tag',
    $backendImage,
    $projectRoot
) 'The Backend image build failed.'

$createdRuntime = $false
$stagingDirectory = $null
try {
    if (-not (Test-Path -LiteralPath $runtimeDirectory)) {
        $null = New-Item -ItemType Directory -Path $runtimeBase -Force
        $stagingDirectory = [IO.Path]::GetFullPath(
            (Join-Path $runtimeBase "$ProjectName.initializing.$([Guid]::NewGuid().ToString('N'))")
        )
        if (-not (Test-IsExactChild $runtimeBase $stagingDirectory)) {
            throw 'The staging directory escaped its approved local application data root.'
        }
        $null = New-Item -ItemType Directory -Path $stagingDirectory

        $mountSource = $stagingDirectory.Replace('\', '/')
        $null = Invoke-Docker @(
            'run',
            '--rm',
            '--user',
            '0:0',
            '--mount',
            "type=bind,src=$mountSource,dst=/runtime",
            '--env',
            'FINAUDIT_RUNTIME_SECRET_DIR=/runtime',
            $backendImage,
            'python',
            '/app/scripts/generate_local_runtime_secrets.py'
        ) 'Local runtime secret generation failed.'

        foreach ($secretName in $secretNames) {
            if (-not (Test-Path -LiteralPath (Join-Path $stagingDirectory $secretName) -PathType Leaf)) {
                throw 'The generated local runtime secret set is incomplete.'
            }
        }
        $marker = [ordered]@{
            schemaVersion = 'finaudit-local-runtime-v1'
            projectName = $ProjectName
            organizationName = $OrganizationName
            organizationUscc = $OrganizationUscc
            organizationTaxNumber = $OrganizationTaxNumber
            adminUsername = $AdminUsername
            adminDisplayName = $AdminDisplayName
            createdAtUtc = [DateTimeOffset]::UtcNow.ToString('O')
            secretFileCount = $secretNames.Count
        }
        Write-Utf8File (Join-Path $stagingDirectory $markerName) @(
            ($marker | ConvertTo-Json -Depth 3)
        )
        Move-Item -LiteralPath $stagingDirectory -Destination $runtimeDirectory
        $stagingDirectory = $null
        $createdRuntime = $true
    }

    $markerPath = Join-Path $runtimeDirectory $markerName
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw 'The runtime directory is not owned by the FinAudit local stack manager.'
    }
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if (
        $marker.schemaVersion -cne 'finaudit-local-runtime-v1' -or
        $marker.projectName -cne $ProjectName -or
        $marker.organizationName -cne $OrganizationName -or
        $marker.organizationUscc -cne $OrganizationUscc -or
        $marker.organizationTaxNumber -cne $OrganizationTaxNumber -or
        $marker.adminUsername -cne $AdminUsername -or
        $marker.adminDisplayName -cne $AdminDisplayName
    ) {
        throw 'The requested bootstrap identity differs from the existing managed runtime.'
    }
    foreach ($secretName in $secretNames) {
        if (-not (Test-Path -LiteralPath (Join-Path $runtimeDirectory $secretName) -PathType Leaf)) {
            throw 'The managed local runtime secret set is incomplete.'
        }
    }
    $runtimeMount = $runtimeDirectory.Replace('\', '/')
    $containerSecretPaths = @($secretNames | ForEach-Object { "/runtime/$_" })
    $null = Invoke-Docker (@(
        'run',
        '--rm',
        '--user',
        '0:0',
        '--network',
        'none',
        '--mount',
        "type=bind,src=$runtimeMount,dst=/runtime",
        $backendImage,
        'sh',
        '-c',
        'chown 0:10001 "$@" && chmod 0440 "$@" && chown 999:1000 /runtime/redis_config /runtime/redis_password && chmod 0400 /runtime/redis_config /runtime/redis_password',
        'finaudit-secret-permissions'
    ) + $containerSecretPaths) 'Unable to apply local runtime secret permissions.'

    $composeEnvPath = Join-Path $runtimeDirectory 'compose.env'
    $temporaryEnvPath = Join-Path $runtimeDirectory 'compose.env.tmp'
    $runtimeForCompose = $runtimeDirectory.Replace('\', '/')
    Write-Utf8File $temporaryEnvPath @(
        "FINAUDIT_RUNTIME_DIR=$runtimeForCompose",
        "FINAUDIT_HTTPS_PORT=$HttpsPort",
        "FINAUDIT_IMAGE_REVISION=$ImageRevision",
        "BOOTSTRAP_ORGANIZATION_NAME=$OrganizationName",
        "BOOTSTRAP_ORGANIZATION_USCC=$OrganizationUscc",
        "BOOTSTRAP_ORGANIZATION_TAX_NUMBER=$OrganizationTaxNumber",
        "BOOTSTRAP_ADMIN_USERNAME=$AdminUsername",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME=$AdminDisplayName"
    )
    Move-Item -LiteralPath $temporaryEnvPath -Destination $composeEnvPath -Force

    $composeArguments = @(
        'compose',
        '--project-name',
        $ProjectName,
        '--env-file',
        $composeEnvPath,
        '--file',
        $composePath
    )
    $null = Invoke-Docker ($composeArguments + @('config', '--quiet')) `
        'The local Compose profile is invalid.'
    $null = Invoke-Docker (
        $composeArguments + @(
            'rm', '--force', '--stop', 'migrate', 'minio-bootstrap',
            'qdrant-bootstrap', 'admin-bootstrap', 'redis'
        )
    ) 'Unable to reset the local one-shot initialization containers.'
    $null = Invoke-Docker ($composeArguments + @('up', '--detach', '--build')) `
        'The local Compose stack failed to start.'
    Wait-LocalReadiness $HttpsPort
}
catch {
    if ($null -ne $stagingDirectory -and (Test-Path -LiteralPath $stagingDirectory)) {
        $resolvedStaging = [IO.Path]::GetFullPath(
            (Resolve-Path -LiteralPath $stagingDirectory).Path
        )
        if (
            (Test-IsExactChild $runtimeBase $resolvedStaging) -and
            ([IO.Path]::GetFileName($resolvedStaging)).StartsWith(
                "$ProjectName.initializing.",
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
        }
    }
    throw
}

Write-Output 'LOCAL_STACK_START=PASS'
Write-Output "LOCAL_STACK_URL=https://localhost:$HttpsPort"
Write-Output "LOCAL_STACK_ADMIN_USERNAME=$AdminUsername"
Write-Output "LOCAL_STACK_RUNTIME_DIR=$runtimeDirectory"
$restoredProperty = $marker.PSObject.Properties['restoredFromBackupId']
if ($null -eq $restoredProperty) {
    Write-Output "LOCAL_STACK_INITIAL_PASSWORD_FILE=$(Join-Path $runtimeDirectory 'bootstrap_admin_password')"
}
else {
    Write-Output 'LOCAL_STACK_INITIAL_PASSWORD_FILE=UNAVAILABLE_AFTER_RESTORE'
}
Write-Output "LOCAL_STACK_RUNTIME_CREATED=$($createdRuntime.ToString().ToUpperInvariant())"
Write-Output 'LOCAL_STACK_AI_PROVIDER=DISABLED'
Write-Output 'LOCAL_STACK_SCANNER=CLAMAV_LOCAL'
