[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 4173,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$PostgresImage = 'postgres:16-alpine',
    [ValidateSet('Report', 'FileUpload', 'FinancialLoop', 'SupplementaryAgreement')]
    [string]$Mode = 'Report',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$RedisImage = 'redis:7.4.9-alpine'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backendRoot = Join-Path $projectRoot 'backend'
$pythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe'
$startMinioPath = Join-Path $projectRoot 'scripts\start-local-minio.ps1'
$stopMinioPath = Join-Path $projectRoot 'scripts\stop-local-minio.ps1'
$fileUploadMode = $Mode -ceq 'FileUpload'
$financialLoopMode = $Mode -ceq 'FinancialLoop'
$supplementaryMode = $Mode -ceq 'SupplementaryAgreement'
$workerMode = $fileUploadMode -or $financialLoopMode
$gateSlug = if ($financialLoopMode) {
    'financial-loop-browser'
}
elseif ($fileUploadMode) {
    'file-upload-browser'
}
elseif ($supplementaryMode) {
    'supplementary-agreement-browser'
}
else {
    'report-browser'
}
$databaseName = if ($financialLoopMode) {
    'finaudit_financial_loop_browser_test'
}
elseif ($fileUploadMode) {
    'finaudit_file_upload_browser_test'
}
elseif ($supplementaryMode) {
    'finaudit_supplementary_agreement_browser_test'
}
else {
    'finaudit_report_browser_test'
}
$databaseUser = 'finaudit_test'
$runId = [Guid]::NewGuid().ToString('N')
$containerName = "finaudit-$gateSlug-pg-$runId"
$containerId = $null
$redisContainerName = "finaudit-$gateSlug-redis-$runId"
$redisContainerId = $null
$minioStarted = $false
$browserExitCode = $null
$managedNames = @(
    'DATABASE_URL',
    'TEST_DATABASE_URL',
    'FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS',
    'FINAUDIT_BROWSER_GATE',
    'FINAUDIT_BROWSER_PORT',
    'FINAUDIT_BROWSER_PUBLIC_ORIGIN',
    'FINAUDIT_BROWSER_REDIS_URL',
    'FINAUDIT_BROWSER_REDIS_RESULT_URL',
    'FINAUDIT_BROWSER_SCANNER_PORT'
)
$previous = @{}

function Protect-Value([string]$Value) {
    $protected = [Security.SecureString]::new()
    foreach ($character in $Value.ToCharArray()) {
        $protected.AppendChar($character)
    }
    $protected.MakeReadOnly()
    $protected
}

function Reveal-Value([Security.SecureString]$Value) {
    [Net.NetworkCredential]::new('', $Value).Password
}

function Restore-ManagedEnvironment {
    foreach ($name in $managedNames) {
        $value = $previous[$name]
        if ($null -eq $value) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -LiteralPath "Env:$name" -Value (Reveal-Value $value)
        }
    }
}

function New-HexSecret([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function Invoke-Docker([string[]]$Arguments) {
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorPreference
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output | ForEach-Object { "$_" })
    }
}

function Resolve-CachedImageId([string]$Image, [string]$DisplayName) {
    $direct = Invoke-Docker @('image', 'inspect', $Image, '--format', '{{.Id}}')
    $directIds = @(
        $direct.Output |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -cmatch '^sha256:[0-9a-f]{64}$' } |
            Sort-Object -Unique
    )
    if (
        $direct.ExitCode -eq 0 -and
        $direct.Output.Count -eq 1 -and
        $directIds.Count -eq 1
    ) {
        return $directIds[0]
    }

    $listed = Invoke-Docker @('image', 'ls', '--no-trunc', '--format', '{{.ID}}', $Image)
    $listedIds = @(
        $listed.Output |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -cmatch '^sha256:[0-9a-f]{64}$' } |
            Sort-Object -Unique
    )
    if ($listed.ExitCode -ne 0 -or $listedIds.Count -ne 1) {
        throw "The cached $DisplayName image identity could not be verified; this gate never pulls images."
    }

    $resolvedId = $listedIds[0]
    $verified = Invoke-Docker @('image', 'inspect', $resolvedId, '--format', '{{.Id}}')
    if (
        $verified.ExitCode -ne 0 -or
        $verified.Output.Count -ne 1 -or
        $verified.Output[0].Trim() -cne $resolvedId
    ) {
        throw "The cached $DisplayName image identity could not be verified; this gate never pulls images."
    }
    return $resolvedId
}

foreach ($name in $managedNames) {
    $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    $previous[$name] = if ($null -eq $item) { $null } else { Protect-Value $item.Value }
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'The Backend virtual environment is missing.'
    }
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is unavailable.'
    }
    $dockerReady = Invoke-Docker @('version', '--format', '{{.Server.Version}}')
    if ($dockerReady.ExitCode -ne 0) {
        throw 'Docker daemon is unavailable.'
    }
    $postgresImageId = Resolve-CachedImageId $PostgresImage 'PostgreSQL 16'
    if ($workerMode) {
        $redisImageId = Resolve-CachedImageId $RedisImage 'Redis'
    }

    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
    }
    catch {
        throw 'The requested browser gate port is unavailable.'
    }
    finally {
        $listener.Stop()
    }

    $scannerListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $scannerListener.Start()
        $scannerPort = ([Net.IPEndPoint]$scannerListener.LocalEndpoint).Port
    }
    finally {
        $scannerListener.Stop()
    }

    if (-not $supplementaryMode) {
        . $startMinioPath
        $minioStarted = $true
    }

    if ($workerMode) {
        $redisPassword = New-HexSecret 32
        $redisPasswordItem = Get-Item -LiteralPath 'Env:REDIS_PASSWORD' -ErrorAction SilentlyContinue
        $previousRedisPassword = if ($null -eq $redisPasswordItem) {
            $null
        }
        else {
            Protect-Value $redisPasswordItem.Value
        }
        try {
            $env:REDIS_PASSWORD = $redisPassword
            $redisCreated = Invoke-Docker @(
                'run', '--pull', 'never', '--rm', '--detach',
                '--label', "com.finaudit.test-purpose=$gateSlug-gate",
                '--label', "com.finaudit.run-id=$runId",
                '--name', $redisContainerName,
                '--env', 'REDIS_PASSWORD',
                '--publish', '127.0.0.1::6379',
                $redisImageId,
                'sh', '-c', 'exec redis-server --requirepass "$REDIS_PASSWORD"'
            )
        }
        finally {
            if ($null -eq $previousRedisPassword) {
                Remove-Item -LiteralPath 'Env:REDIS_PASSWORD' -ErrorAction SilentlyContinue
            }
            else {
                $env:REDIS_PASSWORD = Reveal-Value $previousRedisPassword
            }
        }
        if (
            $redisCreated.ExitCode -ne 0 -or
            $redisCreated.Output.Count -ne 1 -or
            $redisCreated.Output[0].Trim() -notmatch '^[0-9a-f]{64}$'
        ) {
            throw 'Failed to create the disposable Redis container.'
        }
        $redisContainerId = $redisCreated.Output[0].Trim()
        $redisReady = $false
        $redisDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $redisDeadline) {
            $redisProbe = Invoke-Docker @(
                'exec', $redisContainerId, 'sh', '-c',
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'
            )
            if ($redisProbe.ExitCode -eq 0 -and ($redisProbe.Output -join '').Trim() -ceq 'PONG') {
                $redisReady = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $redisReady) {
            throw 'The disposable Redis container did not become ready.'
        }
        $redisBinding = Invoke-Docker @('port', $redisContainerId, '6379/tcp')
        if (
            $redisBinding.ExitCode -ne 0 -or
            $redisBinding.Output.Count -ne 1 -or
            $redisBinding.Output[0].Trim() -notmatch '^127\.0\.0\.1:(?<port>[0-9]{1,5})$'
        ) {
            throw 'Docker did not bind Redis to one IPv4 loopback port.'
        }
        $redisPort = [int]$Matches.port
        $env:FINAUDIT_BROWSER_REDIS_URL = "redis://:$redisPassword@127.0.0.1:$redisPort/0"
        $env:FINAUDIT_BROWSER_REDIS_RESULT_URL = "redis://:$redisPassword@127.0.0.1:$redisPort/1"
        $env:FINAUDIT_BROWSER_SCANNER_PORT = "$scannerPort"
    }

    $databasePassword = New-HexSecret 32
    $passwordItem = Get-Item -LiteralPath 'Env:POSTGRES_PASSWORD' -ErrorAction SilentlyContinue
    $previousPassword = if ($null -eq $passwordItem) {
        $null
    }
    else {
        Protect-Value $passwordItem.Value
    }
    try {
        $env:POSTGRES_PASSWORD = $databasePassword
        $created = Invoke-Docker @(
            'run', '--pull', 'never', '--rm', '--detach',
            '--label', "com.finaudit.test-purpose=$gateSlug-gate",
            '--label', "com.finaudit.run-id=$runId",
            '--name', $containerName,
            '--env', "POSTGRES_USER=$databaseUser",
            '--env', 'POSTGRES_PASSWORD',
            '--env', "POSTGRES_DB=$databaseName",
            '--publish', '127.0.0.1::5432',
            '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,size=1g',
            $postgresImageId
        )
    }
    finally {
        if ($null -eq $previousPassword) {
            Remove-Item -LiteralPath 'Env:POSTGRES_PASSWORD' -ErrorAction SilentlyContinue
        }
        else {
            $env:POSTGRES_PASSWORD = Reveal-Value $previousPassword
        }
    }
    if ($created.ExitCode -ne 0 -or $created.Output.Count -ne 1) {
        throw 'Failed to create the disposable PostgreSQL container.'
    }
    $candidateId = $created.Output[0].Trim()
    if ($candidateId -notmatch '^[0-9a-f]{64}$') {
        throw 'Docker returned an invalid PostgreSQL container identity.'
    }
    $containerId = $candidateId

    $ready = $false
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $probe = Invoke-Docker @(
            'exec', $containerId, 'pg_isready',
            '-U', $databaseUser, '-d', $databaseName
        )
        if ($probe.ExitCode -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw 'The disposable PostgreSQL container did not become ready.'
    }

    $comment = Invoke-Docker @(
        'exec', $containerId, 'psql', '-U', $databaseUser, '-d', 'postgres',
        '-v', 'ON_ERROR_STOP=1', '-c',
        "COMMENT ON DATABASE $databaseName IS 'finaudit:disposable-migration-test'"
    )
    if ($comment.ExitCode -ne 0) {
        throw 'The disposable database marker could not be written.'
    }
    $binding = Invoke-Docker @('port', $containerId, '5432/tcp')
    if (
        $binding.ExitCode -ne 0 -or
        $binding.Output.Count -ne 1 -or
        $binding.Output[0].Trim() -notmatch '^127\.0\.0\.1:(?<port>[0-9]{1,5})$'
    ) {
        throw 'Docker did not bind PostgreSQL to one IPv4 loopback port.'
    }
    $databasePort = [int]$Matches.port
    $databaseUrl = (
        "postgresql+psycopg://${databaseUser}:${databasePassword}" +
        "@127.0.0.1:${databasePort}/${databaseName}"
    )
    $env:DATABASE_URL = $databaseUrl
    $env:TEST_DATABASE_URL = $databaseUrl
    $env:FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS = 'RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE'
    $env:FINAUDIT_BROWSER_GATE = if ($financialLoopMode) {
        'RUN_DISPOSABLE_FINANCIAL_LOOP_BROWSER_V1'
    }
    elseif ($fileUploadMode) {
        'RUN_DISPOSABLE_FILE_UPLOAD_BROWSER_V1'
    }
    elseif ($supplementaryMode) {
        'RUN_DISPOSABLE_SUPPLEMENTARY_AGREEMENT_BROWSER_V1'
    }
    else {
        'RUN_DISPOSABLE_REPORT_BROWSER_V1'
    }
    $env:FINAUDIT_BROWSER_PORT = "$Port"
    $env:FINAUDIT_BROWSER_PUBLIC_ORIGIN = "http://127.0.0.1:$Port"

    Push-Location $backendRoot
    try {
        & $pythonPath -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw 'Alembic did not reach current head.'
        }
        & $pythonPath -m tests.manual_financial_read_browser
        $browserExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($browserExitCode -ne 0) {
        throw 'The browser gate application exited unsuccessfully.'
    }
}
finally {
    Restore-ManagedEnvironment
    $cleanupFailures = [Collections.Generic.List[string]]::new()
    if ($null -ne $containerId) {
        $identity = Invoke-Docker @(
            'inspect', $containerId, '--format', '{{.Id}}|{{json .Config.Labels}}'
        )
        if ($identity.ExitCode -eq 0) {
            if (
                $identity.Output.Count -ne 1 -or
                $identity.Output[0].Trim() -notmatch '^(?<id>[0-9a-f]{64})\|(?<labels>\{.*\})$'
            ) {
                $cleanupFailures.Add('postgres_identity_invalid')
            }
            else {
                $resolvedContainerId = $Matches.id
                try {
                    $labels = $Matches.labels | ConvertFrom-Json
                    if (
                        $resolvedContainerId -cne $containerId -or
                        $labels.'com.finaudit.test-purpose' -cne "$gateSlug-gate" -or
                        $labels.'com.finaudit.run-id' -cne $runId
                    ) {
                        $cleanupFailures.Add('postgres_identity_changed')
                    }
                    else {
                        $removed = Invoke-Docker @(
                            'rm', '--force', '--volumes', $resolvedContainerId
                        )
                        if ($removed.ExitCode -ne 0) {
                            $cleanupFailures.Add('postgres_remove_failed')
                        }
                    }
                }
                catch {
                    $cleanupFailures.Add('postgres_identity_invalid')
                }
            }
        }
        else {
            $exists = Invoke-Docker @('inspect', $containerId, '--format', '{{.Id}}')
            if ($exists.ExitCode -eq 0) {
                $cleanupFailures.Add('postgres_identity_unverified')
            }
        }
    }
    if ($null -ne $redisContainerId) {
        $redisIdentity = Invoke-Docker @(
            'inspect', $redisContainerId, '--format', '{{.Id}}|{{json .Config.Labels}}'
        )
        if ($redisIdentity.ExitCode -eq 0) {
            if (
                $redisIdentity.Output.Count -ne 1 -or
                $redisIdentity.Output[0].Trim() -notmatch '^(?<id>[0-9a-f]{64})\|(?<labels>\{.*\})$'
            ) {
                $cleanupFailures.Add('redis_identity_invalid')
            }
            else {
                $resolvedRedisContainerId = $Matches.id
                try {
                    $redisLabels = $Matches.labels | ConvertFrom-Json
                    if (
                        $resolvedRedisContainerId -cne $redisContainerId -or
                        $redisLabels.'com.finaudit.test-purpose' -cne "$gateSlug-gate" -or
                        $redisLabels.'com.finaudit.run-id' -cne $runId
                    ) {
                        $cleanupFailures.Add('redis_identity_changed')
                    }
                    else {
                        $redisRemoved = Invoke-Docker @(
                            'rm', '--force', '--volumes', $resolvedRedisContainerId
                        )
                        if ($redisRemoved.ExitCode -ne 0) {
                            $cleanupFailures.Add('redis_remove_failed')
                        }
                    }
                }
                catch {
                    $cleanupFailures.Add('redis_identity_invalid')
                }
            }
        }
        else {
            $redisExists = Invoke-Docker @('inspect', $redisContainerId, '--format', '{{.Id}}')
            if ($redisExists.ExitCode -eq 0) {
                $cleanupFailures.Add('redis_identity_unverified')
            }
        }
    }
    if ($minioStarted) {
        try {
            . $stopMinioPath
        }
        catch {
            $cleanupFailures.Add('minio_stop_failed')
        }
    }
    if ($cleanupFailures.Count -gt 0) {
        throw "Browser gate cleanup failed: $($cleanupFailures -join ',')"
    }
}

if ($supplementaryMode) {
    Write-Output "POSTGRESQL_IMAGE_ID=$postgresImageId"
    Write-Output 'SUPPLEMENTARY_AGREEMENT_BROWSER_GATE=PASS'
}
elseif ($financialLoopMode) {
    Write-Output "POSTGRESQL_IMAGE_ID=$postgresImageId"
    Write-Output "REDIS_IMAGE_ID=$redisImageId"
    Write-Output 'FINANCIAL_LOOP_BROWSER_GATE=PASS'
}
elseif ($fileUploadMode) {
    Write-Output "POSTGRESQL_IMAGE_ID=$postgresImageId"
    Write-Output "REDIS_IMAGE_ID=$redisImageId"
    Write-Output 'FILE_UPLOAD_BROWSER_GATE=PASS'
}
else {
    Write-Output "POSTGRESQL_IMAGE_ID=$postgresImageId"
    Write-Output 'REPORT_BROWSER_GATE=PASS'
}
