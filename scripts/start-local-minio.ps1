[CmdletBinding()]
param(
    [switch]$VerifyAdapterIntegration,
    [switch]$VerifyRestartPersistence
)

if ($MyInvocation.InvocationName -cne '.') {
    throw 'Dot-source this script so application credentials stay in the current PowerShell process: . .\scripts\start-local-minio.ps1'
}

& {
    $ErrorActionPreference = 'Stop'
    $sessionVariableName = 'FinAuditLocalMinioSession'
    if ($null -ne (Get-Variable -Name $sessionVariableName -Scope Global -ErrorAction SilentlyContinue)) {
        throw 'A FinAudit local MinIO session already exists in this PowerShell process. Run the stop script first.'
    }

    $projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local-minio.yml'
    $pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
    $bootstrapPath = Join-Path $projectRoot 'scripts\bootstrap_local_minio.py'
    $workerBootstrapPath = Join-Path $projectRoot 'scripts\bootstrap_local_minio_worker.py'
    $restartPersistencePath = Join-Path $projectRoot 'scripts\verify_local_minio_restart_persistence.py'
    $managedNames = @(
        'APP_ENV',
        'MINIO_IMAGE_TAG',
        'MINIO_IMAGE_DIGEST',
        'MINIO_ENDPOINT',
        'MINIO_SECURE',
        'MINIO_ROOT_USER',
        'MINIO_ROOT_PASSWORD',
        'MINIO_ACCESS_KEY',
        'MINIO_SECRET_KEY',
        'MINIO_WORKER_ACCESS_KEY',
        'MINIO_WORKER_SECRET_KEY',
        'MINIO_BUCKET_QUARANTINE',
        'MINIO_BUCKET_ORIGINALS',
        'MINIO_BUCKET_ASSETS',
        'MINIO_BUCKET_PREVIEWS',
        'MINIO_BUCKET_REPORTS',
        'MINIO_BUCKET_EXPORTS',
        'MINIO_BUCKET_TEMP',
        'FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION',
        'FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE',
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD'
    )

    function Protect-EnvironmentValue([string]$Value) {
        $protected = [Security.SecureString]::new()
        foreach ($character in $Value.ToCharArray()) {
            $protected.AppendChar($character)
        }
        $protected.MakeReadOnly()
        return $protected
    }

    function Reveal-EnvironmentValue([Security.SecureString]$Value) {
        return [Net.NetworkCredential]::new('', $Value).Password
    }

    $previous = @{}
    foreach ($name in $managedNames) {
        $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $previous[$name] = if ($null -eq $item) {
            $null
        }
        else {
            Protect-EnvironmentValue ([string]$item.Value)
        }
    }

    function Restore-ManagedEnvironment {
        foreach ($name in $managedNames) {
            $value = $previous[$name]
            if ($null -eq $value) {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -LiteralPath "Env:$name" -Value (Reveal-EnvironmentValue $value)
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
        return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
    }

    function New-StableAccessKey([string]$Purpose) {
        $digest = [Security.Cryptography.SHA256]::Create()
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes("local-minio-v1|$Purpose")
            $hex = ([BitConverter]::ToString($digest.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
        }
        finally {
            $digest.Dispose()
        }
        return "finaudit-$Purpose-$($hex.Substring(0, 16))"
    }

    function Invoke-DockerCommand([string[]]$Arguments) {
        $priorErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $commandOutput = @(& docker @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $priorErrorPreference
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Text = (($commandOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
        }
    }

    function Test-MinIOHealthy([string]$ContainerId) {
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $health = Invoke-DockerCommand @(
                'inspect',
                '--format',
                '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}',
                $ContainerId
            )
            if ($health.ExitCode -ne 0) {
                return $false
            }
            if ($health.Text -ceq 'healthy') {
                return $true
            }
            if ($health.Text -ceq 'unhealthy') {
                return $false
            }
            Start-Sleep -Seconds 2
        }
        return $false
    }

    function Invoke-RestartPersistenceHelper([string]$Phase) {
        $priorErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $null = @(& $pythonPath -I $restartPersistencePath $Phase 2>&1)
            return $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $priorErrorPreference
        }
    }

    $lifecycleGate = [Threading.Semaphore]::new(1, 1, 'Local\FinAuditAgentLocalMinio')
    $gateHeld = $false
    $gateTransferred = $false
    $composeTouched = $false
    $restartObjectCreated = $false
    $ownedContainerId = $null
    try {
        $gateHeld = $lifecycleGate.WaitOne(0)
        if (-not $gateHeld) {
            throw 'Another PowerShell process owns the FinAudit local MinIO lifecycle.'
        }

        if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
            throw 'The Backend virtual environment is missing. Install the project dependencies first.'
        }
        if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw 'Docker CLI is unavailable.'
        }

        $env:APP_ENV = 'local'
        $env:MINIO_IMAGE_TAG = 'RELEASE.2025-09-07T16-13-09Z'
        $env:MINIO_IMAGE_DIGEST = 'sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e'
        $env:MINIO_ENDPOINT = 'http://127.0.0.1:9000'
        $env:MINIO_SECURE = 'false'
        $env:MINIO_ROOT_USER = New-StableAccessKey 'root'
        $env:MINIO_ROOT_PASSWORD = New-HexSecret 32
        $env:MINIO_ACCESS_KEY = New-StableAccessKey 'app'
        $env:MINIO_SECRET_KEY = New-HexSecret 32
        $env:MINIO_WORKER_ACCESS_KEY = New-StableAccessKey 'worker'
        $env:MINIO_WORKER_SECRET_KEY = New-HexSecret 32
        $env:MINIO_BUCKET_QUARANTINE = 'quarantine'
        $env:MINIO_BUCKET_ORIGINALS = 'originals'
        $env:MINIO_BUCKET_ASSETS = 'assets'
        $env:MINIO_BUCKET_PREVIEWS = 'previews'
        $env:MINIO_BUCKET_REPORTS = 'reports'
        $env:MINIO_BUCKET_EXPORTS = 'exports'
        $env:MINIO_BUCKET_TEMP = 'temp'

        $inspection = Invoke-DockerCommand @('compose', '-f', $composePath, 'ps', '-a', '-q', 'minio')
        if ($inspection.ExitCode -ne 0) {
            throw 'Unable to inspect the FinAudit local MinIO Compose project.'
        }
        if ($inspection.Text) {
            throw 'A FinAudit local MinIO container already exists outside this PowerShell session. Resolve that stack explicitly before starting a new session.'
        }

        $composeTouched = $true
        $startup = Invoke-DockerCommand @('compose', '-f', $composePath, 'up', '-d', '--pull', 'never')
        if ($startup.ExitCode -ne 0) {
            $partialContainer = Invoke-DockerCommand @('compose', '-f', $composePath, 'ps', '-q', 'minio')
            if ($partialContainer.ExitCode -eq 0 -and $partialContainer.Text) {
                $ownedContainerId = $partialContainer.Text
            }
            throw 'MinIO failed to start. Obtain the approved pinned image explicitly before retrying.'
        }
        $container = Invoke-DockerCommand @('compose', '-f', $composePath, 'ps', '-q', 'minio')
        $containerId = $container.Text
        if ($container.ExitCode -ne 0) {
            throw 'The MinIO container identity is unavailable.'
        }
        if (-not $containerId) {
            throw 'The MinIO container identity is unavailable.'
        }
        $ownedContainerId = $containerId
        if (-not (Test-MinIOHealthy $containerId)) {
            throw 'The MinIO health check did not pass.'
        }

        & $pythonPath $bootstrapPath
        if ($LASTEXITCODE -ne 0) {
            throw 'MinIO bootstrap did not pass.'
        }
        & $pythonPath $workerBootstrapPath
        if ($LASTEXITCODE -ne 0) {
            throw 'MinIO worker bootstrap did not pass.'
        }

        if ($VerifyAdapterIntegration) {
            $env:FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION = 'VERIFY_SYNTHETIC_STORAGE_V2'
            $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
            $integrationTestPath = Join-Path $projectRoot 'backend\tests\integration\storage'
            & $pythonPath -m pytest $integrationTestPath -m integration --tb=no
            $integrationExitCode = $LASTEXITCODE
            foreach ($temporaryName in @('FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD')) {
                $priorValue = $previous[$temporaryName]
                if ($null -eq $priorValue) {
                    Remove-Item -LiteralPath "Env:$temporaryName" -ErrorAction SilentlyContinue
                }
                else {
                    Set-Item -LiteralPath "Env:$temporaryName" -Value (Reveal-EnvironmentValue $priorValue)
                }
            }
            if ($integrationExitCode -ne 0) {
                throw 'Real MinIO storage Adapter integration did not pass.'
            }
        }

        if ($VerifyRestartPersistence) {
            if (-not (Test-Path -LiteralPath $restartPersistencePath -PathType Leaf)) {
                throw 'The local MinIO restart persistence verifier is missing.'
            }
            $env:FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE = 'VERIFY_SYNTHETIC_RESTART_PERSISTENCE_V1'
            $restartPrepareExitCode = Invoke-RestartPersistenceHelper 'prepare'
            if ($restartPrepareExitCode -eq 2) {
                $restartObjectCreated = $true
                throw 'Local MinIO restart persistence prepare requires exact-object cleanup.'
            }
            if ($restartPrepareExitCode -ne 0) {
                throw 'Local MinIO restart persistence prepare did not pass.'
            }
            $restartObjectCreated = $true

            $ownedContainer = Invoke-DockerCommand @('compose', '-f', $composePath, 'ps', '-q', 'minio')
            if ($ownedContainer.ExitCode -ne 0 -or $ownedContainer.Text -cne $containerId) {
                throw 'Local MinIO restart persistence lost Compose container ownership.'
            }
            $restartDown = Invoke-DockerCommand @('compose', '-f', $composePath, 'down')
            if ($restartDown.ExitCode -ne 0) {
                throw 'Local MinIO restart persistence down did not pass.'
            }
            $ownedContainerId = $null
            $restartUp = Invoke-DockerCommand @(
                'compose',
                '-f',
                $composePath,
                'up',
                '-d',
                '--pull',
                'never'
            )
            if ($restartUp.ExitCode -ne 0) {
                $partialRestartedContainer = Invoke-DockerCommand @(
                    'compose',
                    '-f',
                    $composePath,
                    'ps',
                    '-q',
                    'minio'
                )
                if (
                    $partialRestartedContainer.ExitCode -eq 0 -and
                    $partialRestartedContainer.Text
                ) {
                    $ownedContainerId = $partialRestartedContainer.Text
                }
                throw 'Local MinIO restart persistence up did not pass.'
            }
            $restartedContainer = Invoke-DockerCommand @(
                'compose',
                '-f',
                $composePath,
                'ps',
                '-q',
                'minio'
            )
            if ($restartedContainer.ExitCode -eq 0 -and $restartedContainer.Text) {
                $ownedContainerId = $restartedContainer.Text
            }
            if (
                $restartedContainer.ExitCode -ne 0 -or
                -not $restartedContainer.Text -or
                $restartedContainer.Text -ceq $containerId -or
                -not (Test-MinIOHealthy $restartedContainer.Text)
            ) {
                throw 'Local MinIO restart persistence health did not pass.'
            }
            if ((Invoke-RestartPersistenceHelper 'verify') -ne 0) {
                throw 'Local MinIO restart persistence verification did not pass.'
            }
            if ((Invoke-RestartPersistenceHelper 'delete') -ne 0) {
                throw 'Local MinIO restart persistence delete did not pass.'
            }
            $restartObjectCreated = $false
            $restartGatePrevious = $previous['FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE']
            if ($null -eq $restartGatePrevious) {
                Remove-Item Env:FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE -ErrorAction SilentlyContinue
            }
            else {
                $env:FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE = Reveal-EnvironmentValue $restartGatePrevious
            }
            Write-Output 'LOCAL_MINIO_RESTART_PERSISTENCE=PASS'
            Write-Output 'LOCAL_MINIO_RESTART_IDENTITY_CONTINUITY=PASS'
        }

        Remove-Item Env:MINIO_ROOT_USER, Env:MINIO_ROOT_PASSWORD -ErrorAction SilentlyContinue
        Set-Variable -Name $sessionVariableName -Scope Global -Value ([pscustomobject]@{
            Kind = 'FinAuditLocalMinioSessionV1'
            OwnerProcessId = $PID
            PreviousEnvironment = $previous
            LifecycleGate = $lifecycleGate
            OwnedContainerId = $ownedContainerId
            RestartCleanupRequired = $false
        })
        $gateHeld = $false
        $gateTransferred = $true
        Write-Output 'LOCAL_MINIO_START=PASS'
        Write-Output 'LOCAL_MINIO_APPLICATION_ENV=READY'
    }
    catch {
        $startupError = $_
        $cleanupFailed = $false
        $currentContainer = $null
        if ($composeTouched) {
            $currentContainer = Invoke-DockerCommand @(
                'compose',
                '-f',
                $composePath,
                'ps',
                '-q',
                'minio'
            )
            if (
                $currentContainer.ExitCode -ne 0 -or
                (
                    $currentContainer.Text -and
                    (
                        -not $ownedContainerId -or
                        $currentContainer.Text -cne $ownedContainerId
                    )
                )
            ) {
                $cleanupFailed = $true
            }
        }
        if ($restartObjectCreated -and -not $cleanupFailed) {
            if (-not $currentContainer.Text) {
                $cleanupFailed = $true
            }
            else {
                $cleanupFailed = (Invoke-RestartPersistenceHelper 'cleanup') -ne 0
                if (-not $cleanupFailed) {
                    $restartObjectCreated = $false
                }
            }
        }
        if ($composeTouched -and -not $cleanupFailed) {
            $containerBeforeDown = Invoke-DockerCommand @(
                'compose',
                '-f',
                $composePath,
                'ps',
                '-q',
                'minio'
            )
            if (
                $containerBeforeDown.ExitCode -ne 0 -or
                (
                    $containerBeforeDown.Text -and
                    (
                        -not $ownedContainerId -or
                        $containerBeforeDown.Text -cne $ownedContainerId
                    )
                )
            ) {
                $cleanupFailed = $true
            }
            else {
                $cleanup = Invoke-DockerCommand @('compose', '-f', $composePath, 'down')
                $cleanupFailed = $cleanup.ExitCode -ne 0
            }
        }
        if ($cleanupFailed) {
            Set-Variable -Name $sessionVariableName -Scope Global -Value ([pscustomobject]@{
                Kind = 'FinAuditLocalMinioSessionV1'
                OwnerProcessId = $PID
                PreviousEnvironment = $previous
                LifecycleGate = $lifecycleGate
                OwnedContainerId = $ownedContainerId
                RestartCleanupRequired = $restartObjectCreated
            })
            $gateHeld = $false
            $gateTransferred = $true
            throw 'MinIO startup failed and automatic cleanup also failed. Generated credentials and lifecycle ownership were retained; dot-source the stop script to retry cleanup.'
        }
        Restore-ManagedEnvironment
        throw $startupError
    }
    finally {
        if (-not $gateTransferred) {
            if ($gateHeld) {
                $null = $lifecycleGate.Release()
            }
            $lifecycleGate.Dispose()
        }
    }
}
