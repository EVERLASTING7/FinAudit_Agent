[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$verifierPath = Join-Path $projectRoot 'scripts/verify-postgresql-current-head.ps1'
$backendPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$nonPythonExecutable = (Get-Command where.exe -ErrorAction Stop).Source
$missingDocker = Join-Path (
    [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
) ('finaudit-missing-docker-' + [System.Guid]::NewGuid().ToString('N') + '.exe')

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $output = @(
        & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $verifierPath -BackendPythonPath $backendPython `
            -DockerPath $missingDocker 2>&1
    )
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$outputText = $output -join [System.Environment]::NewLine
if ($exitCode -eq 0) {
    throw 'A missing Docker executable unexpectedly passed the PostgreSQL gate.'
}
if ($outputText -match 'POSTGRESQL_CURRENT_HEAD=PASS') {
    throw 'The failed PostgreSQL gate emitted a PASS marker.'
}

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $output = @(
        & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $verifierPath -BackendPythonPath $nonPythonExecutable `
            -DockerPath $childPowerShell 2>&1
    )
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$outputText = $output -join [System.Environment]::NewLine
if ($exitCode -eq 0) {
    throw 'A non-Python executable unexpectedly passed the PostgreSQL gate.'
}
if ($outputText -match 'POSTGRESQL_CURRENT_HEAD=PASS') {
    throw 'The non-Python failure emitted a PASS marker.'
}

$injectedImage = "postgres:16-alpine`nPOSTGRESQL_CURRENT_HEAD=PASS"
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $output = @(
        & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $verifierPath -Image $injectedImage 2>&1
    )
    $exitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$outputText = $output -join [System.Environment]::NewLine
if ($exitCode -eq 0) {
    throw 'A control-character image reference unexpectedly passed the gate.'
}
if ($outputText -match '(?m)^POSTGRESQL_CURRENT_HEAD=PASS$') {
    throw 'The invalid image reference injected a PASS marker.'
}

$fakeRoot = Join-Path (
    [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
) ('finaudit-postgresql-gate-negative-' + [System.Guid]::NewGuid().ToString('N'))
$fakePython = Join-Path $fakeRoot 'python.cmd'
$fakeDocker = Join-Path $fakeRoot 'docker.cmd'
$fakeDockerArguments = Join-Path $fakeRoot 'docker-arguments.txt'
$fakeDockerImplementation = Join-Path $fakeRoot 'docker-outcome.ps1'
$fakeDockerState = Join-Path $fakeRoot 'docker-state.json'
[System.IO.Directory]::CreateDirectory($fakeRoot) | Out-Null
try {
    [System.IO.File]::WriteAllText(
        $fakePython,
        (@'
@echo off
if "%~1"=="-I" (
  echo FINAUDIT_POSTGRESQL_PYTHON_PREFLIGHT_V1
  exit /b 0
)
if "%~1"=="-m" exit /b 0
exit /b 91
'@).TrimStart(),
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        $fakeDocker,
        (@'
@echo off
>>"%FINAUDIT_FAKE_DOCKER_ARGS_PATH%" echo %*
if "%~1"=="version" (
  echo 29.0.0
  exit /b 0
)
if "%~1"=="image" (
  if "%~2"=="inspect" (
    if "%~3"=="postgres:16-alpine" (
      1>&2 echo Error response from daemon: No such image: postgres:16-alpine
      exit /b 1
    )
    echo sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    exit /b 0
  )
  if "%~2"=="ls" (
    echo sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    exit /b 0
  )
  exit /b 93
)
if "%~1"=="run" (
  echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  exit /b 0
)
if "%~1"=="exec" (
  if "%~3"=="pg_isready" exit /b 0
  if "%~3"=="psql" (
    echo %* | findstr /C:"SHOW server_version_num" >nul
    if not errorlevel 1 echo 160014
    exit /b 0
  )
)
if "%~1"=="port" (
  echo 127.0.0.1:15432
  exit /b 0
)
if "%~1"=="inspect" (
  1>&2 echo Docker daemon unavailable
  exit /b 92
)
exit /b 93
'@).TrimStart(),
        [System.Text.UTF8Encoding]::new($false)
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $fakeDockerArgumentsWasPresent = Test-Path Env:FINAUDIT_FAKE_DOCKER_ARGS_PATH
    $previousFakeDockerArguments = if ($fakeDockerArgumentsWasPresent) {
        [System.Environment]::GetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_ARGS_PATH', 'Process'
        )
    }
    else {
        $null
    }
    try {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_ARGS_PATH', $fakeDockerArguments, 'Process'
        )
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $verifierPath -BackendPythonPath $fakePython `
                -DockerPath $fakeDocker 2>&1
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($fakeDockerArgumentsWasPresent) {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_ARGS_PATH', $previousFakeDockerArguments, 'Process'
            )
        }
        else {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_ARGS_PATH', $null, 'Process'
            )
        }
    }

    $outputText = $output -join [System.Environment]::NewLine
    if ($exitCode -eq 0) {
        throw 'An unverified Docker cleanup failure unexpectedly passed the gate.'
    }
    if ($outputText -match 'POSTGRESQL_CURRENT_HEAD=PASS') {
        throw 'The Docker cleanup failure emitted a PASS marker.'
    }
    $capturedDockerArguments = [System.IO.File]::ReadAllText($fakeDockerArguments)
    if ($capturedDockerArguments -match 'POSTGRES_PASSWORD=') {
        throw 'The PostgreSQL password was exposed in Docker command arguments.'
    }
    if ($capturedDockerArguments -notmatch 'image ls --no-trunc') {
        throw 'The PostgreSQL gate did not exercise the cached image ID fallback.'
    }
    if ($capturedDockerArguments -notmatch (
            'image inspect sha256:' + ('c' * 64)
        )) {
        throw 'The PostgreSQL gate did not verify the immutable fallback image ID.'
    }
    if ($capturedDockerArguments -notmatch (
            '--tmpfs /var/lib/postgresql/data:rw,nosuid,size=1g'
        )) {
        throw 'The PostgreSQL gate does not reserve the required 1 GiB data tmpfs.'
    }

    [System.IO.File]::WriteAllText(
        $fakeDockerImplementation,
        (@'
$ErrorActionPreference = 'Stop'
$dockerArguments = [string[]]$args
$verb = $dockerArguments[0]
$containerId = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

if ($verb -eq 'version') {
    '29.0.0'
    exit 0
}
if ($verb -eq 'image') {
    'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'
    exit 0
}
if ($verb -eq 'run') {
    if ($env:FINAUDIT_FAKE_DOCKER_RUN_MODE -eq 'absent') {
        [Console]::Error.WriteLine('synthetic run failure')
        exit 85
    }
    $runLabel = $dockerArguments | Where-Object { $_ -like 'com.finaudit.run-id=*' }
    $nameIndex = [Array]::IndexOf($dockerArguments, '--name')
    if ($runLabel.Count -ne 1 -or $nameIndex -lt 0) {
        exit 81
    }
    [pscustomobject]@{
        ContainerId = $containerId
        ContainerName = $dockerArguments[$nameIndex + 1]
        RunId = $runLabel.Substring('com.finaudit.run-id='.Length)
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:FINAUDIT_FAKE_DOCKER_STATE_PATH
    'synthetic warning'
    $containerId
    exit 0
}
if ($verb -eq 'inspect') {
    if (-not (Test-Path -LiteralPath $env:FINAUDIT_FAKE_DOCKER_STATE_PATH -PathType Leaf)) {
        [Console]::Error.WriteLine("Error: No such object: $($dockerArguments[1])")
        exit 1
    }
    $state = Get-Content -LiteralPath $env:FINAUDIT_FAKE_DOCKER_STATE_PATH -Raw | ConvertFrom-Json
    if ($dockerArguments[1] -ne $state.ContainerName -and
        $dockerArguments[1] -ne $state.ContainerId) {
        exit 82
    }
    if (($dockerArguments -join ' ') -match 'json \.Config\.Labels') {
        $labels = (
            '{"com.finaudit.test-purpose":"postgresql-current-head",' +
            '"com.finaudit.run-id":"' + $state.RunId + '"}'
        )
        "$($state.ContainerId)|$labels"
    }
    else {
        $state.ContainerId
    }
    exit 0
}
if ($verb -eq 'rm') {
    $state = Get-Content -LiteralPath $env:FINAUDIT_FAKE_DOCKER_STATE_PATH -Raw | ConvertFrom-Json
    if ($dockerArguments[-1] -ne $state.ContainerId) {
        exit 83
    }
    Remove-Item -LiteralPath $env:FINAUDIT_FAKE_DOCKER_STATE_PATH -Force
    $state.ContainerId
    exit 0
}
exit 84
'@).TrimStart(),
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        $fakeDocker,
        (@'
@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0docker-outcome.ps1" %*
exit /b %errorlevel%
'@).TrimStart(),
        [System.Text.UTF8Encoding]::new($false)
    )

    $fakeDockerStateWasPresent = Test-Path Env:FINAUDIT_FAKE_DOCKER_STATE_PATH
    $previousFakeDockerState = if ($fakeDockerStateWasPresent) {
        [System.Environment]::GetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_STATE_PATH', 'Process'
        )
    }
    else {
        $null
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_STATE_PATH', $fakeDockerState, 'Process'
        )
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $verifierPath -BackendPythonPath $fakePython `
                -DockerPath $fakeDocker 2>&1
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($fakeDockerStateWasPresent) {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_STATE_PATH', $previousFakeDockerState, 'Process'
            )
        }
        else {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_STATE_PATH', $null, 'Process'
            )
        }
    }

    $outputText = $output -join [System.Environment]::NewLine
    if ($exitCode -eq 0) {
        throw 'An ambiguous Docker run outcome unexpectedly passed the gate.'
    }
    if ($outputText -match 'POSTGRESQL_CURRENT_HEAD=PASS') {
        throw 'The ambiguous Docker run outcome emitted a PASS marker.'
    }
    if (Test-Path -LiteralPath $fakeDockerState -PathType Leaf) {
        throw 'The ambiguous Docker run outcome left a synthetic container behind.'
    }

    $fakeDockerRunModeWasPresent = Test-Path Env:FINAUDIT_FAKE_DOCKER_RUN_MODE
    $previousFakeDockerRunMode = if ($fakeDockerRunModeWasPresent) {
        [System.Environment]::GetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_RUN_MODE', 'Process'
        )
    }
    else {
        $null
    }
    $fakeDockerStateWasPresent = Test-Path Env:FINAUDIT_FAKE_DOCKER_STATE_PATH
    $previousFakeDockerState = if ($fakeDockerStateWasPresent) {
        [System.Environment]::GetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_STATE_PATH', 'Process'
        )
    }
    else {
        $null
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_RUN_MODE', 'absent', 'Process'
        )
        [System.Environment]::SetEnvironmentVariable(
            'FINAUDIT_FAKE_DOCKER_STATE_PATH', $fakeDockerState, 'Process'
        )
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $verifierPath -BackendPythonPath $fakePython `
                -DockerPath $fakeDocker 2>&1
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($fakeDockerRunModeWasPresent) {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_RUN_MODE', $previousFakeDockerRunMode, 'Process'
            )
        }
        else {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_RUN_MODE', $null, 'Process'
            )
        }
        if ($fakeDockerStateWasPresent) {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_STATE_PATH', $previousFakeDockerState, 'Process'
            )
        }
        else {
            [System.Environment]::SetEnvironmentVariable(
                'FINAUDIT_FAKE_DOCKER_STATE_PATH', $null, 'Process'
            )
        }
    }

    $outputText = $output -join [System.Environment]::NewLine
    if ($exitCode -eq 0) {
        throw 'A Docker run failure without a container unexpectedly passed the gate.'
    }
    if ($outputText -match 'POSTGRESQL_CURRENT_HEAD=PASS') {
        throw 'The Docker run failure without a container emitted a PASS marker.'
    }
    if ($outputText -match 'Could not confirm that the isolated PostgreSQL container is absent') {
        throw 'A confirmed absent Docker object was misclassified as cleanup uncertainty.'
    }
    if ($outputText -notmatch 'Failed to create the isolated PostgreSQL 16 container') {
        throw 'The original Docker run failure was not preserved after absence confirmation.'
    }
}
finally {
    if (Test-Path -LiteralPath $fakeRoot -PathType Container) {
        Remove-Item -LiteralPath $fakeRoot -Recurse -Force
    }
}

$global:LASTEXITCODE = 0
'POSTGRESQL_CURRENT_HEAD_NEGATIVE_CASES=PASS'
