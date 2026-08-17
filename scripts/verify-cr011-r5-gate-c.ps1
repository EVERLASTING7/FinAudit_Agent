[CmdletBinding()]
param(
    [string]$BackendPythonPath,
    [string]$ProjectRootPath,
    [string]$WheelhousePath,
    [ValidateSet('OFFLINE_VERIFIED_CACHE')]
    [string]$DependencyMode = 'OFFLINE_VERIFIED_CACHE'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Captured {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $global:LASTEXITCODE = 0
            $output = @(& $FilePath @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Lines = [string[]]@($output | ForEach-Object { $_.ToString().TrimEnd("`r") })
    }
}

function Assert-ExactOutput {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][object]$Result,
        [Parameter(Mandatory)][string[]]$Expected
    )

    if ($Result.ExitCode -ne 0) {
        $fixedFailure = @(
            $Result.Lines | Where-Object { $_ -cmatch '^CR011_R5_GATE_C_CORE=(FAIL|BLOCKED)_[A-Z0-9_]+$' }
        )
        if ($fixedFailure.Count -eq 1) {
            throw "$Name failed with exit code $($Result.ExitCode): $($fixedFailure[0])"
        }
        throw "$Name failed with exit code $($Result.ExitCode)."
    }
    if ($Result.Lines -ccontains 'CR011_R5_GATE_C=PASS') {
        throw "$Name emitted the outer-only final PASS marker."
    }
    if ($Result.Lines.Count -ne $Expected.Count) {
        throw "$Name emitted an unexpected evidence line count."
    }
    for ($index = 0; $index -lt $Expected.Count; $index += 1) {
        if ($Result.Lines[$index] -cne $Expected[$index]) {
            throw "$Name emitted missing, duplicate, forged, or out-of-order evidence."
        }
    }
}

function Invoke-CoreFixed {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string[]]$Expected
    )

    $result = Invoke-Captured -FilePath $backendPython `
        -Arguments (@('-I', $corePath) + $Arguments) -WorkingDirectory $projectRoot
    Assert-ExactOutput -Name $Name -Result $result -Expected $Expected
    return $result
}

function Copy-AppBuildContext {
    param([Parameter(Mandatory)][string]$Destination)

    [void](New-Item -ItemType Directory -Path $Destination)
    Copy-Item -LiteralPath (Join-Path $backendRoot 'pyproject.toml') -Destination $Destination
    $appSource = Join-Path $backendRoot 'app'
    $files = @(
        Get-ChildItem -LiteralPath $appSource -Recurse -File |
            Where-Object { $_.Extension -in @('.py', '.json') } |
            Sort-Object FullName
    )
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($backendRoot.Length + 1)
        $target = Join-Path $Destination $relative
        [void](New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($target)))
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }
}

function Build-AppWheel {
    param(
        [Parameter(Mandatory)][string]$BuildRoot,
        [Parameter(Mandatory)][string]$OutputRoot
    )

    Copy-AppBuildContext -Destination $BuildRoot
    [void](New-Item -ItemType Directory -Path $OutputRoot)
    $result = Invoke-Captured -FilePath $backendPython -WorkingDirectory $tempRoot -Arguments @(
        '-I', '-m', 'pip', '--isolated', 'wheel', '--no-index', '--no-deps',
        '--no-build-isolation', '--disable-pip-version-check', '--wheel-dir', $OutputRoot,
        $BuildRoot
    )
    if ($result.ExitCode -ne 0) {
        throw "Application wheel build failed with exit code $($result.ExitCode)."
    }
    $wheels = @(Get-ChildItem -LiteralPath $OutputRoot -File -Filter '*.whl')
    if ($wheels.Count -ne 1 -or $wheels[0].Name -cne 'finaudit_backend-0.1.0-py3-none-any.whl') {
        throw 'Application wheel build did not produce the one exact expected filename.'
    }
    return $wheels[0].FullName
}

function Invoke-StartupProbe {
    param(
        [Parameter(Mandatory)][string]$AppSite,
        [Parameter(Mandatory)][string]$Form,
        [Parameter(Mandatory)][string]$Environment,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$Outcome
    )

    $expected = @(
        "CR011_R5_STARTUP_PROBE=${Form}:${Environment}:${Target}:${Outcome}",
        'CR011_R5_STARTUP_GUARD_SCOPE=CPYTHON_SOCKET_DNS_API_ONLY',
        'CR011_R5_STARTUP_GUARDED_SOCKET_ATTEMPTS=0',
        'CR011_R5_STARTUP_GUARDED_DNS_ATTEMPTS=0',
        'CR011_R5_STARTUP_LOCAL_HOSTNAME_READS=1',
        'CR011_R5_NATIVE_WINSOCK_NAMED_PIPE=NOT_CLAIMED'
    )
    $arguments = @('run-child', '--cwd', $tempRoot, '--timeout', '300', '--exact')
    foreach ($marker in $expected) {
        $arguments += @('--expected', $marker)
    }
    $arguments += @(
        '--', $backendPython, '-I', $corePath, 'startup-probe',
        '--app-site', $AppSite, '--runtime-site', $runtimeSite,
        '--policy-file', $policyFile, '--form', $Form, '--environment', $Environment,
        '--target', $Target
    )
    [void](Invoke-CoreFixed -Name "startup-$Form-$Environment-$Target" -Expected $expected `
            -Arguments $arguments)
}

if ([string]::IsNullOrWhiteSpace($ProjectRootPath)) {
    $ProjectRootPath = Join-Path $PSScriptRoot '..'
}
$projectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRootPath).Path)
$backendRoot = Join-Path $projectRoot 'backend'
$corePath = Join-Path $projectRoot 'scripts/verify-cr011-r5-gate-c.py'
$antiPath = Join-Path $projectRoot 'scripts/test-verify-cr011-r5-gate-c.ps1'
$gateBPath = Join-Path $projectRoot 'scripts/verify-cr011-gate-b.ps1'
$gateBAntiPath = Join-Path $projectRoot 'scripts/test-verify-cr011-gate-b.ps1'
$offlinePath = Join-Path $projectRoot 'scripts/verify-local-offline.ps1'
$lockPath = Join-Path $projectRoot 'scripts/requirements-cr011-gate-b.txt'
$childPowerShell = (Get-Command powershell -CommandType Application -ErrorAction Stop).Source

if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $backendRoot '.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}
$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
if ([string]::IsNullOrWhiteSpace($WheelhousePath)) {
    $WheelhousePath = Join-Path $projectRoot 'build/cr011-gate-b-dependencies/python-wheelhouse'
}
elseif (-not [System.IO.Path]::IsPathRooted($WheelhousePath)) {
    $WheelhousePath = Join-Path $projectRoot $WheelhousePath
}
$wheelhouse = [System.IO.Path]::GetFullPath($WheelhousePath)

foreach ($requiredFile in @(
        $backendPython, $corePath, $antiPath, $gateBPath, $gateBAntiPath, $offlinePath, $lockPath
    )) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required CR-011-R5 Gate C file is missing: $requiredFile"
    }
}
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) {
    [Console]::Error.WriteLine('CR011_R5_GATE_C=BLOCKED_OFFLINE_VERIFIED_CACHE')
    exit 4
}

$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-cr011-r5-gate-c-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'CR-011-R5 Gate C temporary path escaped the system temporary directory.'
}
[void](New-Item -ItemType Directory -Path $tempRoot)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$environmentNames = @(
    'ALL_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
    'PIP_CONFIG_FILE', 'PIP_EXTRA_INDEX_URL', 'PIP_FIND_LINKS', 'PIP_INDEX_URL',
    'PIP_NO_INDEX', 'PYTHONHOME', 'PYTHONINSPECT', 'PYTHONPATH', 'PYTHONSTARTUP',
    'PYTHONUSERBASE', 'PYTHONWARNINGS', 'PYTHONDONTWRITEBYTECODE', 'PYTHONHASHSEED',
    'SOURCE_DATE_EPOCH', 'NODE_OPTIONS', 'NODE_PATH',
    'DATABASE_URL', 'TEST_DATABASE_URL', 'REDIS_URL', 'CELERY_BROKER_URL',
    'CELERY_RESULT_BACKEND', 'AI_POLICY_FILE', 'AI_PROVIDER_CALLS_ENABLED',
    'LLM_API_KEY', 'EMBEDDING_API_KEY'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [pscustomobject]@{
        Present = Test-Path "Env:$name"
        Value = [System.Environment]::GetEnvironmentVariable($name, 'Process')
    }
}
$finalEvidence = $null
$finalExitCode = 0

try {
    foreach ($name in $environmentNames) {
        [System.Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    [System.Environment]::SetEnvironmentVariable('PIP_CONFIG_FILE', 'NUL', 'Process')
    [System.Environment]::SetEnvironmentVariable('PIP_NO_INDEX', '1', 'Process')
    [System.Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
    [System.Environment]::SetEnvironmentVariable('PYTHONHASHSEED', '0', 'Process')
    [System.Environment]::SetEnvironmentVariable('SOURCE_DATE_EPOCH', '315532800', 'Process')

    $preflightExpected = @(
        'CR011_R5_PLATFORM=CPYTHON_3_10_WINDOWS_AMD64',
        'CR011_R5_DEPENDENCY_MODE=OFFLINE_VERIFIED_CACHE',
        'CR011_R5_DEPENDENCY_ACQUISITION=NOT_RUN',
        'CR011_R5_ACQUISITION_REQUESTS=0',
        'CR011_R5_RUNTIME_LOCK=641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c',
        'CR011_R5_RUNTIME_WHEELS=6/6',
        'CR011_R5_GATE_C_PREFLIGHT=PASS'
    )
    [void](Invoke-CoreFixed -Name 'preflight' -Expected $preflightExpected -Arguments @(
            'preflight', '--project-root', $projectRoot, '--wheelhouse', $wheelhouse
        ))

    $runtimeSite = Join-Path $tempRoot 'runtime-site'
    [void](New-Item -ItemType Directory -Path $runtimeSite)
    $runtimeInstall = Invoke-Captured -FilePath $backendPython -WorkingDirectory $projectRoot `
        -Arguments @(
            '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps',
            '--only-binary=:all:', '--require-hashes', '--no-compile',
            '--disable-pip-version-check', '--target', $runtimeSite, '--find-links', $wheelhouse,
            '-r', $lockPath
        )
    if ($runtimeInstall.ExitCode -ne 0) {
        throw "Exact runtime closure install failed with exit code $($runtimeInstall.ExitCode)."
    }

    $wheelOne = Build-AppWheel -BuildRoot (Join-Path $tempRoot 'build-one') `
        -OutputRoot (Join-Path $tempRoot 'dist-one')
    $wheelTwo = Build-AppWheel -BuildRoot (Join-Path $tempRoot 'build-two') `
        -OutputRoot (Join-Path $tempRoot 'dist-two')
    $wheelOneHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelOne).Hash.ToLowerInvariant()
    $wheelTwoHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelTwo).Hash.ToLowerInvariant()
    if (
        $wheelOneHash -cne $wheelTwoHash -or
        (Get-Item -LiteralPath $wheelOne).Length -ne (Get-Item -LiteralPath $wheelTwo).Length
    ) {
        throw 'Application wheel builds are not byte reproducible.'
    }

    $appSite = Join-Path $tempRoot 'app-site'
    [void](New-Item -ItemType Directory -Path $appSite)
    $appInstall = Invoke-Captured -FilePath $backendPython -WorkingDirectory $projectRoot `
        -Arguments @(
            '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps',
            '--no-compile', '--disable-pip-version-check', '--target', $appSite, $wheelOne
        )
    if ($appInstall.ExitCode -ne 0) {
        throw "Application wheel --no-deps install failed with exit code $($appInstall.ExitCode)."
    }

    $artifactResult = Invoke-Captured -FilePath $backendPython -WorkingDirectory $projectRoot `
        -Arguments @(
            '-I', $corePath, 'verify-artifacts', '--source-root', $backendRoot,
            '--app-site', $appSite, '--runtime-site', $runtimeSite, '--app-wheel', $wheelOne
        )
    if ($artifactResult.ExitCode -ne 0 -or $artifactResult.Lines.Count -ne 8) {
        throw 'Gate C artifact verification failed.'
    }
    $fixedArtifactLines = @(
        'CR011_R5_RUNTIME_DISTRIBUTIONS=6/6',
        'CR011_R5_RUNTIME_SCHEMA_ENGINE=jsonschema@4.26.0-draft202012',
        'CR011_R5_PACKAGE_RESOURCES_SOURCE=4/4',
        'CR011_R5_PACKAGE_RESOURCES_WHEEL=4/4',
        'CR011_R5_PACKAGE_RESOURCES_INSTALLED=4/4',
        'CR011_R5_PACKAGE_RESOURCE_EXTRA_JSON=0'
    )
    for ($index = 0; $index -lt $fixedArtifactLines.Count; $index += 1) {
        if ($artifactResult.Lines[$index] -cne $fixedArtifactLines[$index]) {
            throw 'Gate C artifact evidence is forged or out of order.'
        }
    }
    if (
        $artifactResult.Lines[6] -cnotmatch '^CR011_R5_APP_WHEEL_IDENTITY=finaudit_backend-0\.1\.0-py3-none-any\.whl/[1-9][0-9]*/[0-9a-f]{64}$' -or
        $artifactResult.Lines[7] -cne 'CR011_R5_GATE_C_ARTIFACTS=PASS'
    ) {
        throw 'Gate C application wheel identity evidence is invalid.'
    }
    $appWheelIdentity = $artifactResult.Lines[6]

    [void](Invoke-CoreFixed -Name 'zero-socket-guard-selftest' -Expected @(
            'CR011_R5_STARTUP_GUARD_SCOPE=CPYTHON_SOCKET_DNS_API_ONLY',
            'CR011_R5_NATIVE_WINSOCK_NAMED_PIPE=NOT_CLAIMED',
            'CR011_R5_CPYTHON_SOCKET_DNS_GUARD_SELFTEST=PASS',
            'CR011_R5_CPYTHON_SOCKET_DNS_GUARD_DENIALS=9'
        ) -Arguments @('guard-selftest'))

    $policyFile = Join-Path $tempRoot 'ai-policy-v1.positive.json'
    Copy-Item -LiteralPath (
        Join-Path $backendRoot 'app/ai/artifacts/cr011_v1/ai-policy-v1.positive.json'
    ) -Destination $policyFile
    (Get-Item -LiteralPath $policyFile).IsReadOnly = $true

    foreach ($environment in @('local', 'test')) {
        foreach ($target in @('fastapi-factory', 'fastapi-module', 'worker-factory', 'worker-module')) {
            Invoke-StartupProbe -AppSite $backendRoot -Form 'source' -Environment $environment `
                -Target $target -Outcome 'ADOPTED'
        }
    }
    foreach ($target in @('fastapi-module', 'worker-module')) {
        Invoke-StartupProbe -AppSite $backendRoot -Form 'source' -Environment 'prod' `
            -Target $target -Outcome 'REJECTED_PRE_EXPOSURE'
        Invoke-StartupProbe -AppSite $appSite -Form 'installed' -Environment 'test' `
            -Target $target -Outcome 'ADOPTED'
    }

    $manifest = Invoke-Captured -FilePath $backendPython -WorkingDirectory $projectRoot `
        -Arguments @('-I', $corePath, 'focused-manifest')
    $manifestCountMatch = if ($manifest.Lines.Count -ge 1) {
        [regex]::Match($manifest.Lines[0], '^CR011_R5_FOCUSED_MANIFEST_COUNT=([1-9][0-9]*)$')
    }
    else {
        [regex]::Match('', 'x')
    }
    $manifestHashMatch = if ($manifest.Lines.Count -ge 2) {
        [regex]::Match($manifest.Lines[1], '^CR011_R5_FOCUSED_MANIFEST_SHA256=([0-9a-f]{64})$')
    }
    else {
        [regex]::Match('', 'x')
    }
    if (
        $manifest.ExitCode -ne 0 -or $manifest.Lines.Count -lt 3 -or
        -not $manifestCountMatch.Success -or -not $manifestHashMatch.Success
    ) {
        throw 'Focused pytest manifest is invalid.'
    }
    $focusedCount = [int]$manifestCountMatch.Groups[1].Value
    $focusedHash = $manifestHashMatch.Groups[1].Value
    if ($manifest.Lines.Count -ne $focusedCount + 2) {
        throw 'Focused pytest manifest count is invalid.'
    }
    $focusedNodeIds = [string[]]@(
        $manifest.Lines[2..($manifest.Lines.Count - 1)] | ForEach-Object {
            if ($_ -cnotmatch '^CR011_R5_FOCUSED_NODEID=tests/[A-Za-z0-9_./-]+::.+$') {
                throw 'Focused pytest manifest contains an invalid nodeid.'
            }
            $_.Substring('CR011_R5_FOCUSED_NODEID='.Length)
        }
    )
    if (@($focusedNodeIds | Sort-Object -Unique).Count -ne $focusedCount) {
        throw 'Focused pytest manifest contains duplicate nodeids.'
    }
    $manifestPath = Join-Path $tempRoot 'focused-nodeids.txt'
    [System.IO.File]::WriteAllText(
        $manifestPath,
        (($focusedNodeIds -join "`n") + "`n"),
        $utf8NoBom
    )
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant() -cne $focusedHash) {
        throw 'Focused pytest manifest hash is invalid.'
    }

    $focusedCollect = Invoke-Captured -FilePath $backendPython -WorkingDirectory $backendRoot `
        -Arguments (@(
                '-m', 'pytest', '-o', 'addopts=', '--strict-markers', '--collect-only', '-q',
                '--color=no', '-p', 'no:warnings'
            ) + $focusedNodeIds)
    if ($focusedCollect.ExitCode -ne 0) {
        throw "Focused pytest collection failed with exit code $($focusedCollect.ExitCode)."
    }
    $focusedCollectPath = Join-Path $tempRoot 'focused-collect.txt'
    [System.IO.File]::WriteAllText(
        $focusedCollectPath,
        (($focusedCollect.Lines -join "`n") + "`n"),
        $utf8NoBom
    )

    $focused = Invoke-Captured -FilePath $backendPython -WorkingDirectory $backendRoot `
        -Arguments (@(
                '-m', 'pytest', '-o', 'addopts=', '--strict-markers', '-q',
                '--color=no', '-p', 'no:warnings'
            ) + $focusedNodeIds)
    if ($focused.ExitCode -ne 0) {
        throw "Focused Policy/startup tests failed with exit code $($focused.ExitCode)."
    }
    $focusedResultPath = Join-Path $tempRoot 'focused-result.txt'
    [System.IO.File]::WriteAllText(
        $focusedResultPath,
        (($focused.Lines -join "`n") + "`n"),
        $utf8NoBom
    )
    $focusedExpected = @(
        "CR011_R5_FOCUSED_MANIFEST=${focusedCount}/${focusedCount}",
        "CR011_R5_FOCUSED_MANIFEST_SHA256=${focusedHash}",
        "CR011_R5_FOCUSED_TESTS=${focusedCount}_PASSED",
        'CR011_R5_FOCUSED_SKIP_XFAIL_XPASS=0',
        'CR011_R5_FOCUSED_COVERAGE=PASS'
    )
    [void](Invoke-CoreFixed -Name 'focused pytest evidence' -Expected $focusedExpected -Arguments @(
            'verify-focused-evidence', '--collected-output', $focusedCollectPath,
            '--result-output', $focusedResultPath
        ))

    $r5Anti = Invoke-Captured -FilePath $childPowerShell -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $antiPath,
        '-BackendPythonPath', $backendPython
    )
    Assert-ExactOutput -Name 'R5 anti-forgery' -Result $r5Anti -Expected @(
        'CR011_R5_GATE_C_NEGATIVE_CASES=13/13',
        'CR011_R5_GATE_C_ANTI_FORGERY=PASS'
    )

    $gateB = Invoke-Captured -FilePath $childPowerShell -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $gateBPath,
        '-BackendPythonPath', $backendPython
    )
    if (
        $gateB.ExitCode -ne 0 -or $gateB.Lines.Count -ne 20 -or
        @($gateB.Lines | Where-Object { $_ -ceq 'CR011_GATE_B=PASS' }).Count -ne 1 -or
        @($gateB.Lines | Where-Object { $_ -ceq 'CR011_ZERO_SOCKET_ATTEMPTS=0' }).Count -ne 1
    ) {
        throw 'R4 full Gate B failed or emitted invalid evidence.'
    }
    $gateBAnti = Invoke-Captured -FilePath $childPowerShell -WorkingDirectory $projectRoot `
        -Arguments @(
            '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $gateBAntiPath
        )
    Assert-ExactOutput -Name 'R4 Gate B anti-forgery' -Result $gateBAnti `
        -Expected @('CR011_GATE_B_NEGATIVE_CASES=11/11')

    $offline = Invoke-Captured -FilePath $childPowerShell -WorkingDirectory $projectRoot -Arguments @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $offlinePath,
        '-BackendPythonPath', $backendPython
    )
    $offlineText = $offline.Lines -join "`n"
    if (
        $offline.ExitCode -ne 0 -or
        @($offline.Lines | Where-Object { $_ -ceq 'LOCAL_OFFLINE_QUALITY=PASS' }).Count -ne 1 -or
        @($offline.Lines | Where-Object { $_ -ceq 'PROVIDER_NETWORK=NOT_RUN' }).Count -ne 1 -or
        @($offline.Lines | Where-Object { $_ -ceq 'PRODUCTION=NOT_RUN' }).Count -ne 1
    ) {
        throw 'Default local offline quality gate failed or emitted invalid evidence.'
    }
    foreach ($qualityStep in @('backend-ruff-check', 'backend-ruff-format', 'backend-mypy', 'backend-pip-check')) {
        if ($offlineText -notmatch "(?m)^LOCAL_OFFLINE_STEP=$qualityStep status=ok elapsed_ms=[0-9]+$") {
            throw "Default offline quality evidence is missing: $qualityStep"
        }
    }

    $finalEvidence = @($preflightExpected[0..5]) + @(
        'CR011_R5_RUNTIME_DISTRIBUTIONS=6/6',
        'CR011_R5_RUNTIME_SCHEMA_ENGINE=jsonschema@4.26.0-draft202012',
        'CR011_R5_APP_WHEEL_BUILD_REPRODUCIBLE=PASS',
        $appWheelIdentity,
        'CR011_R5_APP_WHEEL_INSTALL=NO_DEPS',
        'CR011_R5_PACKAGE_RESOURCES_SOURCE=4/4',
        'CR011_R5_PACKAGE_RESOURCES_WHEEL=4/4',
        'CR011_R5_PACKAGE_RESOURCES_INSTALLED=4/4',
        'CR011_R5_PACKAGE_RESOURCE_EXTRA_JSON=0',
        'CR011_R5_STARTUP_GUARD_SCOPE=CPYTHON_SOCKET_DNS_API_ONLY',
        'GATE_C_NATIVE_OS_TELEMETRY_SCOPE=NOT_CLAIMED',
        'GATE_C_NATIVE_WINSOCK_ATTEMPTS=NOT_CLAIMED',
        'GATE_C_WINDOWS_NAMED_PIPE_ATTEMPTS=NOT_CLAIMED',
        'GATE_C_NATIVE_OS_TELEMETRY_REASON=NATIVE_OS_TELEMETRY_VERIFIER_NOT_INTEGRATED',
        'CR011_R5_CPYTHON_SOCKET_DNS_GUARD_SELFTEST=PASS',
        'CR011_R5_FASTAPI_SOURCE_LOCAL=2/2',
        'CR011_R5_FASTAPI_SOURCE_TEST=2/2',
        'CR011_R5_WORKER_SOURCE_LOCAL=2/2',
        'CR011_R5_WORKER_SOURCE_TEST=2/2',
        'CR011_R5_PROD_PRE_EXPOSURE_REJECTION=2/2',
        'CR011_R5_INSTALLED_MODULE_STARTUP=2/2',
        'CR011_R5_STARTUP_GUARDED_SOCKET_ATTEMPTS=0',
        'CR011_R5_STARTUP_GUARDED_DNS_ATTEMPTS=0',
        'CR011_R5_STARTUP_LOCAL_HOSTNAME_READS=1_PER_PROCESS',
        $focusedExpected,
        'CR011_R5_GATE_C_ANTI_FORGERY=PASS',
        'CR011_R5_R4_FULL_GATE_B=PASS',
        'CR011_R5_R4_GATE_B_ANTI_FORGERY=PASS',
        'CR011_R5_BACKEND_QUALITY=PASS',
        'CR011_R5_DEFAULT_LOCAL_OFFLINE=PASS',
        'CR011_R5_PROVIDER_NETWORK=NOT_RUN',
        'CR011_R5_DATABASE_REDIS_BROKER=NOT_RUN',
        'CR011_R5_R4_PERSISTENT_GATE_C=NOT_AUTHORIZED',
        'CR011_R5_DOCKER_DEPLOYMENT=NOT_AUTHORIZED',
        'CR011_R5_PRODUCTION=NOT_AUTHORIZED',
        'CR011_R5_BASE004_AUTO_PROMOTION=FORBIDDEN',
        'GATE_C_RESULT=BLOCKED',
        'CR011_R5_GATE_C=BLOCKED_NATIVE_WINSOCK_NAMED_PIPE_EVIDENCE'
    )
    $finalExitCode = 4
}
finally {
    foreach ($name in $environmentNames) {
        $previous = $previousEnvironment[$name]
        [System.Environment]::SetEnvironmentVariable(
            $name,
            $(if ($previous.Present) { $previous.Value } else { $null }),
            'Process'
        )
    }
    if (Test-Path -LiteralPath $tempRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
        if (-not $resolvedTempRoot.StartsWith(
                $tempBase,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            throw 'Refusing to remove a Gate C path outside the system temporary directory.'
        }
        if (Test-Path -LiteralPath (Join-Path $tempRoot 'ai-policy-v1.positive.json')) {
            (Get-Item -LiteralPath (Join-Path $tempRoot 'ai-policy-v1.positive.json')).IsReadOnly = $false
        }
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}

if ($null -eq $finalEvidence) {
    throw 'Gate C final evidence was not constructed.'
}
$finalEvidence | ForEach-Object { $_ }
exit $finalExitCode
