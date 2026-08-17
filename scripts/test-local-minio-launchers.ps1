[CmdletBinding()]
param(
    [switch]$Child
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Child) {
    $childPowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
    & $childPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $PSCommandPath -Child
    if ($LASTEXITCODE -ne 0) {
        throw 'Local MinIO launcher self-test failed in its isolated PowerShell process.'
    }
    $global:LASTEXITCODE = 0
    return
}

$startPath = Join-Path $PSScriptRoot 'start-local-minio.ps1'
$stopPath = Join-Path $PSScriptRoot 'stop-local-minio.ps1'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$restartHelperTestPath = Join-Path $PSScriptRoot 'tests\test_verify_local_minio_restart_persistence.py'
$originalEnvironment = @{}
foreach ($name in @('APP_ENV', 'MINIO_ACCESS_KEY')) {
    $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    $originalEnvironment[$name] = if ($null -eq $item) {
        $null
    }
    else {
        ConvertTo-SecureString -String ([string]$item.Value) -AsPlainText -Force
    }
}
$global:FinAuditLauncherFakeMode = 'inspect-empty'
$global:FinAuditLauncherDownCalled = $false
$global:FinAuditLauncherContainerId = $null
$global:FinAuditLauncherCommands = [Collections.Generic.List[string]]::new()

function global:docker {
    $commandLine = $args -join ' '
    $global:FinAuditLauncherCommands.Add($commandLine)
    if ($commandLine -match ' ps -a -q minio$') {
        if ($global:FinAuditLauncherFakeMode -eq 'existing') {
            'external-container'
        }
        $global:LASTEXITCODE = 0
        return
    }
    if ($commandLine -match ' ps -q minio$') {
        if ($global:FinAuditLauncherContainerId) {
            $global:FinAuditLauncherContainerId
        }
        $global:LASTEXITCODE = 0
        return
    }
    if ($commandLine -match ' up -d --pull never$') {
        $global:FinAuditLauncherContainerId = 'owned-container'
        $global:LASTEXITCODE = 1
        return
    }
    if ($commandLine -match ' down$') {
        $global:FinAuditLauncherDownCalled = $true
        $global:LASTEXITCODE = if ($global:FinAuditLauncherFakeMode -eq 'down-fails') { 1 } else { 0 }
        if ($global:LASTEXITCODE -eq 0) {
            $global:FinAuditLauncherContainerId = $null
        }
        return
    }
    $global:LASTEXITCODE = 1
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-ExpectedFailure([scriptblock]$Action, [string]$MessagePrefix) {
    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -like "$MessagePrefix*") {
            return
        }
        throw
    }
    throw "Expected failure was not raised: $MessagePrefix"
}

try {
    & $pythonPath $restartHelperTestPath
    Assert-True ($LASTEXITCODE -eq 0) 'Local MinIO restart persistence helper tests failed.'

    $parseErrors = @()
    $null = [Management.Automation.Language.Parser]::ParseFile(
        $startPath,
        [ref]$null,
        [ref]$parseErrors
    )
    $null = [Management.Automation.Language.Parser]::ParseFile(
        $stopPath,
        [ref]$null,
        [ref]$parseErrors
    )
    Assert-True ($parseErrors.Count -eq 0) 'Local MinIO launchers must parse as PowerShell.'

    $startSource = Get-Content -LiteralPath $startPath -Raw
    $switchPosition = $startSource.IndexOf('[switch]$VerifyAdapterIntegration')
    $bootstrapPosition = $startSource.IndexOf('& $pythonPath $bootstrapPath')
    $integrationGuardPosition = $startSource.IndexOf('if ($VerifyAdapterIntegration)')
    $gatePosition = $startSource.IndexOf("`$env:FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION = 'VERIFY_SYNTHETIC_STORAGE_V2'")
    $pluginIsolationPosition = $startSource.IndexOf("`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'")
    $integrationPosition = $startSource.IndexOf('& $pythonPath -m pytest $integrationTestPath -m integration --tb=no')
    $integrationFailurePosition = $startSource.IndexOf("throw 'Real MinIO storage Adapter integration did not pass.'")
    $restartSwitchPosition = $startSource.IndexOf('[switch]$VerifyRestartPersistence')
    $restartGuardPosition = $startSource.IndexOf('if ($VerifyRestartPersistence)')
    $restartPreparePosition = $startSource.IndexOf("Invoke-RestartPersistenceHelper 'prepare'")
    $restartDownPosition = $startSource.IndexOf("`$restartDown = Invoke-DockerCommand @('compose', '-f', `$composePath, 'down')")
    $restartUpPosition = $startSource.IndexOf("`$restartUp = Invoke-DockerCommand @(")
    $restartVerifyPosition = $startSource.IndexOf("Invoke-RestartPersistenceHelper 'verify'")
    $restartDeletePosition = $startSource.IndexOf("Invoke-RestartPersistenceHelper 'delete'")
    $restartCleanupPosition = $startSource.IndexOf("Invoke-RestartPersistenceHelper 'cleanup'")
    $rootRemovalPosition = $startSource.IndexOf('Remove-Item Env:MINIO_ROOT_USER, Env:MINIO_ROOT_PASSWORD')
    Assert-True ($switchPosition -ge 0) 'Adapter integration must be an explicit launcher switch.'
    Assert-True ($integrationGuardPosition -gt $bootstrapPosition) 'Adapter integration must be closed by default and run after bootstrap.'
    Assert-True ($gatePosition -gt $integrationGuardPosition) 'Adapter integration confirmation must be scoped by its switch.'
    Assert-True ($pluginIsolationPosition -gt $gatePosition) 'Adapter integration must disable ambient pytest plugins.'
    Assert-True ($integrationPosition -gt $pluginIsolationPosition) 'Adapter integration must run the exact storage test with redacted traceback output.'
    Assert-True ($integrationFailurePosition -gt $integrationPosition) 'Adapter integration failure must stop launcher readiness.'
    Assert-True ($rootRemovalPosition -gt $integrationFailurePosition) 'Adapter integration must run before root verifier credentials are removed.'
    Assert-True ($restartSwitchPosition -ge 0) 'Restart persistence verification must be explicit opt-in.'
    Assert-True ($restartGuardPosition -gt $bootstrapPosition) 'Restart persistence verification must run after bootstrap.'
    Assert-True ($restartPreparePosition -gt $restartGuardPosition) 'Restart persistence prepare must be scoped by its switch.'
    Assert-True ($restartDownPosition -gt $restartPreparePosition) 'Restart persistence must create its object before Compose down.'
    Assert-True ($restartUpPosition -gt $restartDownPosition) 'Restart persistence must recreate the stack after Compose down.'
    Assert-True ($restartVerifyPosition -gt $restartUpPosition) 'Restart persistence must verify after the recreated stack is healthy.'
    Assert-True ($restartDeletePosition -gt $restartVerifyPosition) 'Restart persistence must delete only after post-restart verification.'
    Assert-True ($rootRemovalPosition -gt $restartDeletePosition) 'Restart persistence must run before root verifier credentials are removed.'
    Assert-True ($restartCleanupPosition -gt $restartDeletePosition) 'Restart persistence failure cleanup must be owned by the launcher catch path.'
    Assert-True ($startSource.Contains("& `$pythonPath -I `$restartPersistencePath `$Phase")) 'Restart persistence helper must run in isolated Python mode.'
    Assert-True ($startSource -notmatch "'down'.*'-v'|'down'.*'--volumes'|'down'.*'--remove-orphans'") 'Restart persistence must preserve the named volume and unrelated resources.'
    Assert-True ($startSource -notmatch 'docker\s+pull') 'Adapter integration launcher must not pull images.'

    $env:APP_ENV = 'caller-environment'
    $env:MINIO_ACCESS_KEY = 'caller-access-key'
    $global:FinAuditLauncherDownCalled = $false
    Invoke-ExpectedFailure { . $stopPath } 'No FinAudit local MinIO session'
    Assert-True (-not $global:FinAuditLauncherDownCalled) 'Stop without ownership called Docker.'
    Assert-True ($env:APP_ENV -ceq 'caller-environment') 'Stop without ownership changed APP_ENV.'
    Assert-True ($env:MINIO_ACCESS_KEY -ceq 'caller-access-key') 'Stop without ownership changed credentials.'

    $global:FinAuditLauncherFakeMode = 'existing'
    $global:FinAuditLauncherDownCalled = $false
    $composeTouched = $true
    Invoke-ExpectedFailure { . $startPath } 'A FinAudit local MinIO container already exists'
    Assert-True (-not $global:FinAuditLauncherDownCalled) 'Caller scope caused an external Compose down.'
    Assert-True ($env:APP_ENV -ceq 'caller-environment') 'Existing-container rejection did not restore APP_ENV.'
    Assert-True ($null -eq (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) 'Existing-container rejection retained ownership.'
    Remove-Variable composeTouched

    $global:FinAuditLauncherFakeMode = 'down-succeeds'
    Invoke-ExpectedFailure { . $startPath } 'MinIO failed to start'
    Assert-True ($env:APP_ENV -ceq 'caller-environment') 'Successful startup cleanup did not restore APP_ENV.'
    Assert-True ($env:MINIO_ACCESS_KEY -ceq 'caller-access-key') 'Successful startup cleanup did not restore credentials.'
    Assert-True ($null -eq (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) 'Successful startup cleanup retained ownership.'

    $global:FinAuditLauncherFakeMode = 'down-fails'
    Invoke-ExpectedFailure { . $startPath } 'MinIO startup failed and automatic cleanup also failed'
    $retainedAccessKey = $env:MINIO_ACCESS_KEY
    Assert-True ($env:APP_ENV -ceq 'local') 'Failed startup cleanup did not retain local APP_ENV.'
    Assert-True ($retainedAccessKey -like 'finaudit-app-*') 'Failed startup cleanup did not retain the generated app identity.'
    Assert-True ($null -ne (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) 'Failed startup cleanup lost ownership.'
    Assert-True ($global:FinAuditLocalMinioSession.OwnedContainerId -ceq $global:FinAuditLauncherContainerId) 'Failed startup cleanup retained the wrong container identity.'

    $childCommand = "try { . '$startPath'; exit 9 } catch { Write-Output `$_.Exception.Message; exit 0 }"
    $childOutput = @(& powershell.exe -NoLogo -NoProfile -NonInteractive -Command $childCommand)
    Assert-True ($LASTEXITCODE -eq 0) 'Cross-process lifecycle check failed to execute.'
    Assert-True (($childOutput -join "`n") -like 'Another PowerShell process owns*') 'Cross-process lifecycle ownership was not enforced.'

    Invoke-ExpectedFailure { . $stopPath } 'MinIO failed to stop'
    Assert-True ($env:MINIO_ACCESS_KEY -ceq $retainedAccessKey) 'Failed stop lost the generated application credential.'
    Assert-True ($null -ne (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) 'Failed stop lost ownership.'

    $global:FinAuditLauncherFakeMode = 'down-succeeds'
    . $stopPath | Out-Null
    Assert-True ($env:APP_ENV -ceq 'caller-environment') 'Stop retry did not restore APP_ENV.'
    Assert-True ($env:MINIO_ACCESS_KEY -ceq 'caller-access-key') 'Stop retry did not restore credentials.'
    Assert-True ($null -eq (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) 'Stop retry retained ownership.'
    Assert-True ($null -eq $global:FinAuditLauncherContainerId) 'Stop retry left the owned fake container running.'

    foreach ($leakedName in @('previous', 'managedNames', 'lifecycleGate', 'session', 'beforeStop')) {
        Assert-True ($null -eq (Get-Variable $leakedName -ErrorAction SilentlyContinue)) "Launcher leaked caller variable: $leakedName"
    }
}
finally {
    if ($null -ne (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) {
        $global:FinAuditLauncherFakeMode = 'down-succeeds'
        . $stopPath | Out-Null
    }
    Remove-Item Function:\docker -ErrorAction SilentlyContinue
    Remove-Variable FinAuditLauncherFakeMode -Scope Global -ErrorAction SilentlyContinue
    Remove-Variable FinAuditLauncherDownCalled -Scope Global -ErrorAction SilentlyContinue
    Remove-Variable FinAuditLauncherContainerId -Scope Global -ErrorAction SilentlyContinue
    Remove-Variable FinAuditLauncherCommands -Scope Global -ErrorAction SilentlyContinue
    foreach ($name in $originalEnvironment.Keys) {
        $value = $originalEnvironment[$name]
        if ($null -eq $value) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            $plainValue = [Net.NetworkCredential]::new('', $value).Password
            Set-Item -LiteralPath "Env:$name" -Value $plainValue
        }
    }
}

$global:LASTEXITCODE = 0
'LOCAL_MINIO_LAUNCHER_TESTS=PASS'
