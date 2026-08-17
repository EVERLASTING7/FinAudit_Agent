[CmdletBinding()]
param()

if ($MyInvocation.InvocationName -cne '.') {
    throw 'Dot-source this script so generated application credentials are removed from the current PowerShell process: . .\scripts\stop-local-minio.ps1'
}

& {
    $ErrorActionPreference = 'Stop'
    $sessionVariableName = 'FinAuditLocalMinioSession'
    $sessionVariable = Get-Variable -Name $sessionVariableName -Scope Global -ErrorAction SilentlyContinue
    if (
        $null -eq $sessionVariable -or
        $sessionVariable.Value.Kind -cne 'FinAuditLocalMinioSessionV1' -or
        $sessionVariable.Value.OwnerProcessId -ne $PID
    ) {
        throw 'No FinAudit local MinIO session is owned by this PowerShell process.'
    }
    $session = $sessionVariable.Value

    function Reveal-EnvironmentValue([Security.SecureString]$Value) {
        return [Net.NetworkCredential]::new('', $Value).Password
    }

    function Save-CurrentValue([string]$Name) {
        $item = Get-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        if ($null -eq $item) {
            return $null
        }
        $protected = [Security.SecureString]::new()
        foreach ($character in ([string]$item.Value).ToCharArray()) {
            $protected.AppendChar($character)
        }
        $protected.MakeReadOnly()
        return $protected
    }

    function Restore-Value([string]$Name, [Security.SecureString]$Value) {
        if ($null -eq $Value) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -LiteralPath "Env:$Name" -Value (Reveal-EnvironmentValue $Value)
        }
    }

    function Invoke-DockerCommand([string[]]$Arguments) {
        $priorErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $null = @(& docker @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $priorErrorPreference
        }
        return $exitCode
    }

    function Get-ComposeContainerIdentity() {
        $priorErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = @(& docker compose -f $composePath ps -q minio 2>&1)
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $priorErrorPreference
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Text = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
        }
    }

    function Test-MinIOHealthy([string]$ContainerId) {
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $priorErrorPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $output = @(& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' $ContainerId 2>&1)
                $exitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $priorErrorPreference
            }
            $status = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
            if ($exitCode -ne 0) {
                return $false
            }
            if ($status -ceq 'healthy') {
                return $true
            }
            if ($status -ceq 'unhealthy') {
                return $false
            }
            Start-Sleep -Seconds 2
        }
        return $false
    }

    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local-minio.yml'
    $pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
    $restartPersistencePath = Join-Path $projectRoot 'scripts\verify_local_minio_restart_persistence.py'
    $temporaryNames = @('MINIO_IMAGE_TAG', 'MINIO_IMAGE_DIGEST', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD')
    $beforeStop = @{}
    foreach ($name in $temporaryNames) {
        $beforeStop[$name] = Save-CurrentValue $name
    }

    $env:MINIO_IMAGE_TAG = 'RELEASE.2025-09-07T16-13-09Z'
    $env:MINIO_IMAGE_DIGEST = 'sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e'
    $restartCleanupProperty = $session.PSObject.Properties['RestartCleanupRequired']
    $restartCleanupRequired = (
        $null -ne $restartCleanupProperty -and
        $restartCleanupProperty.Value -eq $true
    )
    if (-not $restartCleanupRequired) {
        $env:MINIO_ROOT_USER = 'unused-local-stop'
        $env:MINIO_ROOT_PASSWORD = 'unused-local-stop-password'
    }
    $ownedContainerProperty = $session.PSObject.Properties['OwnedContainerId']
    $ownedContainerId = if ($null -eq $ownedContainerProperty) {
        $null
    }
    else {
        [string]$ownedContainerProperty.Value
    }

    try {
        $currentContainer = Get-ComposeContainerIdentity
        if ($currentContainer.ExitCode -ne 0) {
            throw 'compose identity inspection failed'
        }
        if (
            $currentContainer.Text -and
            (
                -not $ownedContainerId -or
                $currentContainer.Text -cne $ownedContainerId
            )
        ) {
            throw 'compose container ownership changed'
        }
        if ($restartCleanupRequired) {
            if (-not $currentContainer.Text) {
                $restartUp = Invoke-DockerCommand @('compose', '-f', $composePath, 'up', '-d', '--pull', 'never')
                if ($restartUp -ne 0) {
                    $partialContainer = Get-ComposeContainerIdentity
                    if ($partialContainer.ExitCode -eq 0 -and $partialContainer.Text) {
                        $ownedContainerId = $partialContainer.Text
                        if ($null -eq $ownedContainerProperty) {
                            $session | Add-Member -NotePropertyName OwnedContainerId -NotePropertyValue $ownedContainerId
                            $ownedContainerProperty = $session.PSObject.Properties['OwnedContainerId']
                        }
                        else {
                            $ownedContainerProperty.Value = $ownedContainerId
                        }
                    }
                    throw 'restart persistence recovery up failed'
                }
                $currentContainer = Get-ComposeContainerIdentity
                if ($currentContainer.ExitCode -ne 0 -or -not $currentContainer.Text) {
                    throw 'restart persistence recovery identity failed'
                }
                $ownedContainerId = $currentContainer.Text
                if ($null -eq $ownedContainerProperty) {
                    $session | Add-Member -NotePropertyName OwnedContainerId -NotePropertyValue $ownedContainerId
                    $ownedContainerProperty = $session.PSObject.Properties['OwnedContainerId']
                }
                else {
                    $ownedContainerProperty.Value = $ownedContainerId
                }
            }
            elseif (-not (Test-MinIOHealthy $currentContainer.Text)) {
                $restartExitCode = Invoke-DockerCommand @('restart', $ownedContainerId)
                if ($restartExitCode -ne 0) {
                    throw 'restart persistence recovery container restart failed'
                }
                $currentContainer = Get-ComposeContainerIdentity
                if (
                    $currentContainer.ExitCode -ne 0 -or
                    $currentContainer.Text -cne $ownedContainerId
                ) {
                    throw 'restart persistence recovery ownership changed'
                }
            }
            if (-not (Test-MinIOHealthy $currentContainer.Text)) {
                throw 'restart persistence recovery health failed'
            }
            $priorErrorPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $null = @(& $pythonPath -I $restartPersistencePath cleanup 2>&1)
                $restartCleanupExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $priorErrorPreference
            }
            if ($restartCleanupExitCode -ne 0) {
                throw 'restart persistence exact-object cleanup failed'
            }
            $restartCleanupProperty.Value = $false
        }
        $containerBeforeDown = Get-ComposeContainerIdentity
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
            throw 'compose container ownership could not be confirmed before down'
        }
        $exitCode = Invoke-DockerCommand @('compose', '-f', $composePath, 'down')
        if ($exitCode -ne 0) {
            throw 'compose down failed'
        }
    }
    catch {
        foreach ($name in $temporaryNames) {
            Restore-Value $name $beforeStop[$name]
        }
        throw 'MinIO failed to stop. Application credentials and lifecycle ownership were retained for a safe retry.'
    }

    foreach ($entry in $session.PreviousEnvironment.GetEnumerator()) {
        Restore-Value ([string]$entry.Key) $entry.Value
    }
    $null = $session.LifecycleGate.Release()
    $session.LifecycleGate.Dispose()
    Remove-Variable -Name $sessionVariableName -Scope Global

    Write-Output 'LOCAL_MINIO_STOP=PASS'
    Write-Output 'LOCAL_MINIO_DATA_VOLUME=PRESERVED'
}
