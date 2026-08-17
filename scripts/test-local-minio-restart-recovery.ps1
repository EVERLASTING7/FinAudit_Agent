[CmdletBinding()]
param(
    [switch]$Child
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Child) {
    & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $PSCommandPath -Child
    if ($LASTEXITCODE -ne 0) {
        throw 'Local MinIO restart recovery self-test failed.'
    }
    $global:LASTEXITCODE = 0
    return
}

$startPath = Join-Path $PSScriptRoot 'start-local-minio.ps1'
$stopPath = Join-Path $PSScriptRoot 'stop-local-minio.ps1'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "finaudit-minio-restart-$PID"
$fakePythonPath = Join-Path $temporaryRoot 'fake-python.ps1'
$testStartPath = Join-Path $temporaryRoot 'start-local-minio.ps1'
$testStopPath = Join-Path $temporaryRoot 'stop-local-minio.ps1'

$baselineEnvironment = [ordered]@{
    APP_ENV = 'prior-app-env'
    MINIO_IMAGE_TAG = 'prior-image-tag'
    MINIO_IMAGE_DIGEST = 'prior-image-digest'
    MINIO_ENDPOINT = 'http://prior.invalid:9000'
    MINIO_SECURE = 'true'
    MINIO_ROOT_USER = 'prior-root-user'
    MINIO_ROOT_PASSWORD = 'prior-root-password'
    MINIO_ACCESS_KEY = 'prior-app-user'
    MINIO_SECRET_KEY = 'prior-app-password'
    FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE = 'prior-restart-gate'
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Set-BaselineEnvironment {
    foreach ($entry in $baselineEnvironment.GetEnumerator()) {
        Set-Item -LiteralPath "Env:$($entry.Key)" -Value $entry.Value
    }
}

function Assert-BaselineEnvironment {
    foreach ($entry in $baselineEnvironment.GetEnumerator()) {
        $item = Get-Item -LiteralPath "Env:$($entry.Key)" -ErrorAction SilentlyContinue
        Assert-True (
            $null -ne $item -and [string]$item.Value -ceq [string]$entry.Value
        ) "Environment restoration failed for $($entry.Key)."
    }
}

function Assert-NoSession {
    Assert-True (
        $null -eq (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)
    ) 'Lifecycle ownership was unexpectedly retained.'
}

function Assert-RetainedCredentials {
    Assert-True (
        (Test-Path Env:MINIO_ROOT_USER) -and
        $env:MINIO_ROOT_USER -cne $baselineEnvironment.MINIO_ROOT_USER
    ) 'Generated root credentials were not retained for recovery.'
    Assert-True (
        (Test-Path Env:MINIO_ACCESS_KEY) -and
        $env:MINIO_ACCESS_KEY -cne $baselineEnvironment.MINIO_ACCESS_KEY
    ) 'Generated application credentials were not retained for recovery.'
}

function Assert-SafeDockerCommands {
    foreach ($line in $global:FinAuditFakeDocker.Commands) {
        Assert-True ($line -notmatch '(?<!\S)-v(?!\S)') 'Docker used the destructive -v option.'
        Assert-True ($line -notmatch '--volumes') 'Docker used the destructive --volumes option.'
        Assert-True ($line -notmatch '--remove-orphans') 'Docker used --remove-orphans.'
        Assert-True ($line -notmatch '(?:^|\s)pull(?:\s|$)') 'Docker performed a network pull.'
        if ($line -match '(?:^|\s)up(?:\s|$)') {
            Assert-True ($line -match 'up -d --pull never$') 'Docker start was not pinned to --pull never.'
        }
    }
}

function Assert-EventOrder([string[]]$Patterns) {
    $nextIndex = 0
    foreach ($pattern in $Patterns) {
        $matched = $false
        while ($nextIndex -lt $global:FinAuditFakeEvents.Count) {
            $event = $global:FinAuditFakeEvents[$nextIndex]
            $nextIndex += 1
            if ($event -match $pattern) {
                $matched = $true
                break
            }
        }
        Assert-True $matched (
            "Expected event was missing or out of order: $pattern. Events: " +
            ($global:FinAuditFakeEvents -join ' | ')
        )
    }
}

function Reset-FakeState(
    [int]$FailUpNumber = 0,
    [int]$PrepareExitCode = 0,
    [int]$CleanupFailuresRemaining = 0
) {
    Assert-NoSession
    Set-BaselineEnvironment
    $global:FinAuditFakeEvents = [Collections.Generic.List[string]]::new()
    $global:FinAuditFakeDocker = [pscustomobject]@{
        Commands = [Collections.Generic.List[string]]::new()
        CurrentContainerId = $null
        CreatedContainerIds = [Collections.Generic.List[string]]::new()
        UpCount = 0
        DownCount = 0
        FailUpNumber = $FailUpNumber
    }
    $global:FinAuditFakePython = [pscustomobject]@{
        Calls = [Collections.Generic.List[string]]::new()
        ObjectCreated = $false
        PrepareExitCode = $PrepareExitCode
        CleanupFailuresRemaining = $CleanupFailuresRemaining
    }
}

function Invoke-StartExpectFailure {
    $failed = $false
    try {
        $null = @(. $testStartPath -VerifyRestartPersistence)
    }
    catch {
        $failed = $true
    }
    Assert-True $failed 'Start unexpectedly succeeded.'
}

function Invoke-StopExpectFailure {
    $failed = $false
    try {
        $null = @(. $testStopPath)
    }
    catch {
        $failed = $true
    }
    Assert-True $failed 'Stop unexpectedly succeeded.'
}

function global:docker {
    $arguments = @($args | ForEach-Object { [string]$_ })
    $line = $arguments -join ' '
    $state = $global:FinAuditFakeDocker
    $state.Commands.Add($line)
    $global:FinAuditFakeEvents.Add("docker:$line")

    if ($line -match '^(?:compose) .* ps -a -q minio$') {
        if ($state.CurrentContainerId) {
            Write-Output $state.CurrentContainerId
        }
        $global:LASTEXITCODE = 0
        return
    }
    if ($line -match '^(?:compose) .* up -d --pull never$') {
        $state.UpCount += 1
        if ($state.FailUpNumber -gt 0 -and $state.UpCount -eq $state.FailUpNumber) {
            $state.CurrentContainerId = $null
            $global:LASTEXITCODE = 1
            return
        }
        $containerId = "owned-container-$($state.UpCount)"
        $state.CurrentContainerId = $containerId
        $state.CreatedContainerIds.Add($containerId)
        $global:LASTEXITCODE = 0
        return
    }
    if ($line -match '^(?:compose) .* ps -q minio$') {
        if ($state.CurrentContainerId) {
            Write-Output $state.CurrentContainerId
        }
        $global:LASTEXITCODE = 0
        return
    }
    if ($line -match '^inspect .* (?<container>\S+)$') {
        if ($state.CurrentContainerId -and $Matches.container -ceq $state.CurrentContainerId) {
            Write-Output 'healthy'
            $global:LASTEXITCODE = 0
        }
        else {
            $global:LASTEXITCODE = 1
        }
        return
    }
    if ($line -match '^(?:compose) .* down$') {
        $state.DownCount += 1
        $state.CurrentContainerId = $null
        $global:LASTEXITCODE = 0
        return
    }

    $global:LASTEXITCODE = 97
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot -ErrorAction Stop | Out-Null
    $fakePythonSource = @'
$pythonArguments = @($args | ForEach-Object { [string]$_ })
$line = $pythonArguments -join ' '
$pythonState = $global:FinAuditFakePython
$dockerState = $global:FinAuditFakeDocker
$pythonState.Calls.Add($line)
$phase = if ($pythonArguments.Count -gt 0) { $pythonArguments[-1] } else { '' }
$exitCode = 0

switch ($phase) {
    'prepare' {
        $global:FinAuditFakeEvents.Add('python:prepare')
        $pythonState.ObjectCreated = $true
        $exitCode = $pythonState.PrepareExitCode
    }
    'verify' {
        $global:FinAuditFakeEvents.Add('python:verify')
        if (-not $pythonState.ObjectCreated -or -not $dockerState.CurrentContainerId) {
            $exitCode = 1
        }
    }
    'delete' {
        $global:FinAuditFakeEvents.Add('python:delete')
        if (-not $pythonState.ObjectCreated -or -not $dockerState.CurrentContainerId) {
            $exitCode = 1
        }
        else {
            $pythonState.ObjectCreated = $false
        }
    }
    'cleanup' {
        $global:FinAuditFakeEvents.Add('python:cleanup')
        if (-not $dockerState.CurrentContainerId) {
            $exitCode = 1
        }
        elseif ($pythonState.CleanupFailuresRemaining -gt 0) {
            $pythonState.CleanupFailuresRemaining -= 1
            $exitCode = 1
        }
        else {
            $pythonState.ObjectCreated = $false
        }
    }
    default {
        $global:FinAuditFakeEvents.Add('python:bootstrap')
    }
}

Set-Variable -Name LASTEXITCODE -Scope Global -Value $exitCode
'@
    [IO.File]::WriteAllText($fakePythonPath, $fakePythonSource, [Text.UTF8Encoding]::new($false))

    $escapedProjectRoot = $projectRoot.Replace("'", "''")
    $escapedPythonPath = $fakePythonPath.Replace("'", "''")

    $startSource = Get-Content -LiteralPath $startPath -Raw
    $startProjectRootLine = '$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ''..''))'
    $startPythonLine = '$pythonPath = Join-Path $projectRoot ''backend\.venv\Scripts\python.exe'''
    Assert-True ($startSource.Contains($startProjectRootLine)) 'Start project-root seam was not found.'
    Assert-True ($startSource.Contains($startPythonLine)) 'Start Python seam was not found.'
    $testStartSource = $startSource.Replace(
        $startProjectRootLine,
        "`$projectRoot = '$escapedProjectRoot'"
    ).Replace(
        $startPythonLine,
        "`$pythonPath = '$escapedPythonPath'"
    )
    [IO.File]::WriteAllText($testStartPath, $testStartSource, [Text.UTF8Encoding]::new($false))

    $stopSource = Get-Content -LiteralPath $stopPath -Raw
    $stopProjectRootLine = '$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ''..''))'
    $stopPythonLine = '$pythonPath = Join-Path $projectRoot ''backend\.venv\Scripts\python.exe'''
    Assert-True ($stopSource.Contains($stopProjectRootLine)) 'Stop project-root seam was not found.'
    Assert-True ($stopSource.Contains($stopPythonLine)) 'Stop Python seam was not found.'
    $testStopSource = $stopSource.Replace(
        $stopProjectRootLine,
        "`$projectRoot = '$escapedProjectRoot'"
    ).Replace(
        $stopPythonLine,
        "`$pythonPath = '$escapedPythonPath'"
    )
    [IO.File]::WriteAllText($testStopPath, $testStopSource, [Text.UTF8Encoding]::new($false))

    # Restart happy path: two distinct containers, exact helper sequence, then ordinary stop.
    Reset-FakeState
    $startOutput = @(. $testStartPath -VerifyRestartPersistence)
    Assert-True (($startOutput -join "`n") -match 'LOCAL_MINIO_RESTART_PERSISTENCE=PASS') 'Restart persistence did not report PASS.'
    Assert-True (($startOutput -join "`n") -match 'LOCAL_MINIO_RESTART_IDENTITY_CONTINUITY=PASS') 'Identity continuity did not report PASS.'
    $session = $global:FinAuditLocalMinioSession
    Assert-True ($session.OwnedContainerId -ceq 'owned-container-2') 'Restarted container ownership was not transferred.'
    Assert-True ($session.RestartCleanupRequired -eq $false) 'Happy path incorrectly retained cleanup ownership.'
    Assert-True ($global:FinAuditFakeDocker.CreatedContainerIds.Count -eq 2) 'Happy path did not create exactly two containers.'
    Assert-True (
        $global:FinAuditFakeDocker.CreatedContainerIds[0] -cne $global:FinAuditFakeDocker.CreatedContainerIds[1]
    ) 'Restart reused the initial container identity.'
    Assert-EventOrder @(
        'docker:compose .* up -d --pull never$',
        '^python:prepare$',
        'docker:compose .* down$',
        'docker:compose .* up -d --pull never$',
        '^python:verify$',
        '^python:delete$'
    )
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-True ($global:FinAuditFakeDocker.UpCount -eq 2) 'Happy path performed an unexpected start.'
    Assert-True ($global:FinAuditFakeDocker.DownCount -eq 2) 'Happy path did not perform restart and final down exactly once each.'
    Assert-True (-not $global:FinAuditFakePython.ObjectCreated) 'Happy path retained the synthetic object.'
    Assert-SafeDockerCommands

    # Restart up failure: start retains exact cleanup ownership; stop recovers with a new container.
    Reset-FakeState -FailUpNumber 2
    Invoke-StartExpectFailure
    $session = $global:FinAuditLocalMinioSession
    Assert-True ($session.RestartCleanupRequired -eq $true) 'Restart up failure did not retain exact-object cleanup ownership.'
    Assert-True ($null -eq $session.OwnedContainerId) 'Restart up failure retained a nonexistent container identity.'
    Assert-RetainedCredentials
    Assert-True $global:FinAuditFakePython.ObjectCreated 'Restart up failure lost synthetic-object ownership.'
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-True ($global:FinAuditFakeDocker.UpCount -eq 3) 'Recovery did not perform exactly one replacement start.'
    Assert-True ($global:FinAuditFakeDocker.DownCount -eq 2) 'Recovery did not perform restart and final down exactly once each.'
    Assert-True (-not $global:FinAuditFakePython.ObjectCreated) 'Recovery retained the synthetic object.'
    Assert-EventOrder @(
        '^python:prepare$',
        'docker:compose .* down$',
        'docker:compose .* up -d --pull never$',
        'docker:compose .* up -d --pull never$',
        '^python:cleanup$',
        'docker:compose .* down$'
    )
    Assert-SafeDockerCommands

    # A failed stop cleanup retains ownership; a second stop reuses that exact container.
    Reset-FakeState -FailUpNumber 2 -CleanupFailuresRemaining 1
    Invoke-StartExpectFailure
    Invoke-StopExpectFailure
    $session = $global:FinAuditLocalMinioSession
    Assert-True ($session.RestartCleanupRequired -eq $true) 'Failed cleanup cleared exact-object ownership.'
    Assert-True ($session.OwnedContainerId -ceq 'owned-container-3') 'Failed cleanup did not retain the recovery container identity.'
    Assert-RetainedCredentials
    Assert-True ($global:FinAuditFakeDocker.UpCount -eq 3) 'First cleanup retry performed an unexpected start count.'
    Assert-True ($global:FinAuditFakeDocker.DownCount -eq 1) 'Failed cleanup incorrectly stopped the recovery container.'
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-True ($global:FinAuditFakeDocker.UpCount -eq 3) 'Second cleanup retry replaced an already-owned container.'
    Assert-True ($global:FinAuditFakeDocker.DownCount -eq 2) 'Second cleanup retry did not stop the owned container.'
    Assert-True (-not $global:FinAuditFakePython.ObjectCreated) 'Second cleanup retry retained the synthetic object.'
    Assert-SafeDockerCommands

    # Container identity drift must never stop a container not owned by the session.
    Reset-FakeState
    $null = @(. $testStartPath -VerifyRestartPersistence)
    $ownedContainerId = $global:FinAuditLocalMinioSession.OwnedContainerId
    $global:FinAuditFakeDocker.CurrentContainerId = 'foreign-container'
    $downCountBeforeDrift = $global:FinAuditFakeDocker.DownCount
    Invoke-StopExpectFailure
    Assert-True (
        $global:FinAuditFakeDocker.DownCount -eq $downCountBeforeDrift
    ) 'Container identity drift triggered compose down.'
    Assert-True (
        $null -ne (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)
    ) 'Container identity drift released lifecycle ownership.'
    $global:FinAuditFakeDocker.CurrentContainerId = $ownedContainerId
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-SafeDockerCommands

    # A normally completed session may safely stop after its owned container disappeared.
    Reset-FakeState
    $null = @(. $testStartPath -VerifyRestartPersistence)
    Assert-True (
        $global:FinAuditLocalMinioSession.OwnedContainerId -ceq 'owned-container-2'
    ) 'Missing-container scenario did not begin with transferred ownership.'
    $global:FinAuditFakeDocker.CurrentContainerId = $null
    $downCountBeforeMissingContainerStop = $global:FinAuditFakeDocker.DownCount
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-True (
        $global:FinAuditFakeDocker.DownCount -eq $downCountBeforeMissingContainerStop + 1
    ) 'Missing owned container did not complete safe Compose cleanup.'
    Assert-True ($global:FinAuditFakeDocker.UpCount -eq 2) 'Missing owned container triggered an unexpected restart.'
    Assert-SafeDockerCommands

    # Helper prepare exit 2 means the exact object is owned and cleanup remains mandatory.
    Reset-FakeState -PrepareExitCode 2 -CleanupFailuresRemaining 1
    Invoke-StartExpectFailure
    $session = $global:FinAuditLocalMinioSession
    Assert-True ($session.RestartCleanupRequired -eq $true) 'Prepare exit 2 was not treated as owned cleanup work.'
    Assert-True ($session.OwnedContainerId -ceq 'owned-container-1') 'Prepare exit 2 lost the owned container identity.'
    Assert-RetainedCredentials
    Assert-True $global:FinAuditFakePython.ObjectCreated 'Prepare exit 2 lost synthetic-object ownership.'
    Assert-EventOrder @('^python:prepare$', '^python:cleanup$')
    $null = @(. $testStopPath)
    Assert-NoSession
    Assert-BaselineEnvironment
    Assert-True (-not $global:FinAuditFakePython.ObjectCreated) 'Prepare exit 2 recovery retained the synthetic object.'
    Assert-SafeDockerCommands
}
finally {
    if ($null -ne (Get-Variable FinAuditLocalMinioSession -Scope Global -ErrorAction SilentlyContinue)) {
        $session = $global:FinAuditLocalMinioSession
        try {
            $null = $session.LifecycleGate.Release()
        }
        catch {
        }
        $session.LifecycleGate.Dispose()
        Remove-Variable FinAuditLocalMinioSession -Scope Global
    }
    Remove-Item Function:\docker -ErrorAction SilentlyContinue
    Remove-Variable FinAuditFakeDocker, FinAuditFakePython, FinAuditFakeEvents -Scope Global -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$global:LASTEXITCODE = 0
'LOCAL_MINIO_RESTART_RECOVERY_TESTS=PASS'
