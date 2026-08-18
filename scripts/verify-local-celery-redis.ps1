[CmdletBinding()]
param(
    [string]$BackendPythonPath,
    [string]$DockerPath,
    [string]$Image = 'redis:7.4.9-alpine'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path)
$backendRoot = Join-Path $projectRoot 'backend'
$python = if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    Join-Path $backendRoot '.venv\Scripts\python.exe'
} else {
    [IO.Path]::GetFullPath($BackendPythonPath)
}
$docker = if ([string]::IsNullOrWhiteSpace($DockerPath)) {
    (Get-Command docker -ErrorAction Stop).Source
} else {
    [IO.Path]::GetFullPath($DockerPath)
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Backend Python executable is missing.'
}
if (-not (Test-Path -LiteralPath $docker -PathType Leaf)) {
    throw 'Docker executable is missing.'
}
if ([string]::IsNullOrWhiteSpace($Image) -or $Image.StartsWith('-') -or $Image -notmatch '^[\x21-\x7e]+$') {
    throw 'Redis image reference is invalid.'
}

function Invoke-CommandResult([string]$FilePath, [string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Output = [string[]]@($output | ForEach-Object { $_.ToString() })
    }
}

$server = Invoke-CommandResult $docker @('version', '--format', '{{.Server.Version}}')
if ($server.ExitCode -ne 0 -or $server.Output.Count -ne 1) {
    throw 'Docker daemon is not available; this gate never starts it.'
}
$imageIdentity = Invoke-CommandResult $docker @('image', 'inspect', $Image, '--format', '{{.Id}}')
if ($imageIdentity.ExitCode -ne 0 -or $imageIdentity.Output.Count -ne 1) {
    throw 'Cached Redis image is missing; this gate never pulls images.'
}

$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $bytes = New-Object byte[] 32
    $random.GetBytes($bytes)
}
finally {
    $random.Dispose()
}
$password = ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
$runId = [Guid]::NewGuid().ToString('N')
$containerName = "finaudit-celery-redis-$runId"
$runLabel = "com.finaudit.run-id=$runId"
$purposeLabel = 'com.finaudit.test-purpose=celery-redis'
$containerId = $null
$priorPassword = [Environment]::GetEnvironmentVariable('REDIS_PASSWORD', 'Process')
$priorBrokerUrl = [Environment]::GetEnvironmentVariable('TEST_CELERY_BROKER_URL', 'Process')
$priorConfirmation = [Environment]::GetEnvironmentVariable(
    'FINAUDIT_ALLOW_LOCAL_CELERY_REDIS_TEST',
    'Process'
)
$priorRuntimeUrl = [Environment]::GetEnvironmentVariable('FINAUDIT_TEST_REDIS_URL', 'Process')
$priorRuntimeConfirmation = [Environment]::GetEnvironmentVariable(
    'FINAUDIT_TEST_REDIS_CONFIRMATION',
    'Process'
)

try {
    [Environment]::SetEnvironmentVariable('REDIS_PASSWORD', $password, 'Process')
    $created = Invoke-CommandResult $docker @(
        'run', '--pull', 'never', '--rm', '--detach',
        '--label', $purposeLabel, '--label', $runLabel,
        '--name', $containerName,
        '--env', 'REDIS_PASSWORD',
        '--publish', '127.0.0.1::6379',
        $Image,
        'sh', '-c', 'exec redis-server --requirepass "$REDIS_PASSWORD"'
    )
    if ($created.ExitCode -ne 0 -or $created.Output.Count -ne 1 -or $created.Output[0].Trim() -notmatch '^[0-9a-f]{64}$') {
        throw 'Failed to create the isolated Redis container.'
    }
    $containerId = $created.Output[0].Trim()

    $ready = $false
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $ping = Invoke-CommandResult $docker @(
            'exec', $containerId, 'sh', '-c',
            'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'
        )
        if ($ping.ExitCode -eq 0 -and ($ping.Output -join '').Trim() -ceq 'PONG') {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        throw 'The isolated Redis container did not become ready.'
    }

    $portResult = Invoke-CommandResult $docker @(
        'port', $containerId, '6379/tcp'
    )
    if ($portResult.ExitCode -ne 0 -or $portResult.Output.Count -ne 1 -or $portResult.Output[0] -notmatch '^127\.0\.0\.1:(?<port>[0-9]{1,5})$') {
        throw 'Docker returned an unsafe Redis loopback port binding.'
    }
    $port = [int]$Matches.port
    if ($port -lt 1 -or $port -gt 65535) {
        throw 'Docker returned an invalid Redis port.'
    }
    $brokerUrl = "redis://:$password@127.0.0.1:$port/0"
    [Environment]::SetEnvironmentVariable('TEST_CELERY_BROKER_URL', $brokerUrl, 'Process')
    [Environment]::SetEnvironmentVariable('FINAUDIT_TEST_REDIS_URL', $brokerUrl, 'Process')
    [Environment]::SetEnvironmentVariable(
        'FINAUDIT_TEST_REDIS_CONFIRMATION',
        'ALLOW_LOCAL_REDIS_RUNTIME_CONTROL_TEST',
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'FINAUDIT_ALLOW_LOCAL_CELERY_REDIS_TEST',
        'isolated-loopback-redis',
        'Process'
    )

    Push-Location -LiteralPath $backendRoot
    try {
        $test = Invoke-CommandResult $python @(
            '-m', 'pytest',
            'tests/integration/broker/test_real_celery_redis.py',
            'tests/integration/broker/test_ai_runtime_control_redis.py'
        )
    }
    finally {
        Pop-Location
    }
    $test.Output | Write-Output
    if ($test.ExitCode -ne 0) {
        throw 'The real Celery/Redis integration test failed.'
    }

    "CELERY_REDIS_IMAGE_ID=$($imageIdentity.Output[0].Trim())"
    "CELERY_REDIS_SERVER=$($server.Output[0].Trim())"
    'CELERY_REDIS_BROKER_TRANSPORT=PASS'
}
finally {
    [Environment]::SetEnvironmentVariable('TEST_CELERY_BROKER_URL', $priorBrokerUrl, 'Process')
    [Environment]::SetEnvironmentVariable('FINAUDIT_TEST_REDIS_URL', $priorRuntimeUrl, 'Process')
    [Environment]::SetEnvironmentVariable(
        'FINAUDIT_TEST_REDIS_CONFIRMATION',
        $priorRuntimeConfirmation,
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'FINAUDIT_ALLOW_LOCAL_CELERY_REDIS_TEST',
        $priorConfirmation,
        'Process'
    )
    [Environment]::SetEnvironmentVariable('REDIS_PASSWORD', $priorPassword, 'Process')
    if ($null -ne $containerId -and $containerId -match '^[0-9a-f]{64}$') {
        $identity = Invoke-CommandResult $docker @(
            'inspect', $containerId, '--format', '{{.Id}}|{{json .Config.Labels}}'
        )
        if ($identity.ExitCode -eq 0) {
            if ($identity.Output.Count -ne 1 -or
                $identity.Output[0].Trim() -notmatch '^(?<id>[0-9a-f]{64})\|(?<labels>\{.*\})$') {
                throw 'Docker returned an invalid Redis cleanup identity.'
            }
            $resolvedContainerId = $Matches.id
            $labels = $Matches.labels | ConvertFrom-Json
            if ($resolvedContainerId -ne $containerId -or
                $labels.'com.finaudit.test-purpose' -ne 'celery-redis' -or
                $labels.'com.finaudit.run-id' -ne $runId) {
                throw 'Refusing to clean up a Redis container whose identity or labels changed.'
            }
            $removed = Invoke-CommandResult $docker @(
                'rm', '--force', '--volumes', $resolvedContainerId
            )
            if ($removed.ExitCode -ne 0) {
                throw 'Failed to remove the isolated Redis test container.'
            }
        }
        else {
            $exists = Invoke-CommandResult $docker @(
                'inspect', $containerId, '--format', '{{.Id}}'
            )
            if ($exists.ExitCode -eq 0) {
                throw 'Could not verify the isolated Redis container labels.'
            }
        }
    }
}
