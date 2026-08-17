[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,39}$')]
    [string]$ProjectName = 'finaudit-local',

    [switch]$FileUpload,

    [switch]$WorkerCrashRecovery,

    [switch]$ContractExtractionCrashRecovery,

    [switch]$InvoiceExtractionCrashRecovery,

    [switch]$AuditExecutionCrashRecovery,

    [switch]$ReportGenerationCrashRecovery,

    [switch]$KnowledgeIndexCrashRecovery,

    [switch]$AiAuditCrashRecovery,

    [switch]$PerformanceBaseline,

    [switch]$SecurityBaseline
)

$ErrorActionPreference = 'Stop'
$markerName = '.finaudit-local-runtime.json'

if ($ContractExtractionCrashRecovery -and $InvoiceExtractionCrashRecovery) {
    throw 'Contract and invoice extraction crash recovery gates must run separately.'
}

if (
    $AuditExecutionCrashRecovery -and
    ($ContractExtractionCrashRecovery -or $InvoiceExtractionCrashRecovery)
) {
    throw 'Audit and extraction crash recovery gates must run separately.'
}

if (
    $ReportGenerationCrashRecovery -and
    (
        $AuditExecutionCrashRecovery -or
        $ContractExtractionCrashRecovery -or
        $InvoiceExtractionCrashRecovery
    )
) {
    throw 'Report and other business Job crash recovery gates must run separately.'
}

if (
    $KnowledgeIndexCrashRecovery -and
    (
        $ReportGenerationCrashRecovery -or
        $AuditExecutionCrashRecovery -or
        $ContractExtractionCrashRecovery -or
        $InvoiceExtractionCrashRecovery
    )
) {
    throw 'Knowledge index and other business Job crash recovery gates must run separately.'
}

if (
    $AiAuditCrashRecovery -and
    (
        $FileUpload -or
        $WorkerCrashRecovery -or
        $ContractExtractionCrashRecovery -or
        $InvoiceExtractionCrashRecovery -or
        $AuditExecutionCrashRecovery -or
        $ReportGenerationCrashRecovery -or
        $KnowledgeIndexCrashRecovery -or
        $PerformanceBaseline -or
        $SecurityBaseline
    )
) {
    throw 'AI audit crash recovery must run as an isolated gate.'
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
    $text = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
    if ($exitCode -ne 0) {
        throw "$FailureMessage $text"
    }
    return $text
}

function Read-DependencyHealth([int]$Port) {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.ServerCertificateCustomValidationCallback =
        [Net.Http.HttpClientHandler]::DangerousAcceptAnyServerCertificateValidator
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(10)
    try {
        $response = $client.GetAsync(
            "https://localhost:$Port/health/dependencies"
        ).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw 'Dependency readiness returned a non-success status.'
        }
        $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() |
            ConvertFrom-Json
        $readiness = $payload.data
        $failed = @(
            $readiness.dependencies |
                Where-Object { $_.required -eq $true -and $_.status -cne 'ok' }
        )
        $scanner = @($readiness.dependencies | Where-Object { $_.name -ceq 'scanner' })
        $provider = @($readiness.dependencies | Where-Object { $_.name -ceq 'ai_provider' })
        if (
            $payload.code -cne 'OK' -or
            $readiness.status -cne 'ok' -or
            $failed.Count -ne 0 -or
            $scanner.Count -ne 1 -or
            $scanner[0].required -ne $true -or
            $scanner[0].status -cne 'ok' -or
            $provider.Count -ne 1 -or
            $provider[0].required -ne $false -or
            $provider[0].status -cne 'disabled'
        ) {
            throw 'Dependency readiness projection does not match the local Profile.'
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Read-ComposeContainer([string]$Project, [string]$Service) {
    $identities = @(
        (Invoke-Docker @(
            'ps', '--all', '--no-trunc',
            '--filter', "label=com.docker.compose.project=$Project",
            '--filter', "label=com.docker.compose.service=$Service",
            '--format', '{{.ID}}'
        ) "Unable to identify the $Service container.") -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($identities.Count -ne 1 -or $identities[0] -notmatch '^[0-9a-f]{64}$') {
        throw "The $Service container identity is ambiguous."
    }
    $container = @(
        (Invoke-Docker @('inspect', $identities[0]) "Unable to inspect the $Service container.") |
            ConvertFrom-Json
    )
    if (
        $container.Count -ne 1 -or
        $container[0].Id -cne $identities[0] -or
        $container[0].Config.Labels.'com.docker.compose.project' -cne $Project -or
        $container[0].Config.Labels.'com.docker.compose.service' -cne $Service
    ) {
        throw "The $Service container ownership is invalid."
    }
    return $container[0]
}

function Read-PostgresScalar([string]$ContainerId, [string]$Query) {
    if ($ContainerId -notmatch '^[0-9a-f]{64}$' -or [string]::IsNullOrWhiteSpace($Query)) {
        throw 'The PostgreSQL scalar query identity is invalid.'
    }
    $output = Invoke-Docker @(
        'exec', $ContainerId,
        'psql', '--username', 'finaudit', '--dbname', 'finaudit',
        '--no-align', '--tuples-only', '--set', 'ON_ERROR_STOP=1',
        '--command', $Query
    ) 'The local PostgreSQL scalar query failed.'
    $values = @(
        $output -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($values.Count -ne 1) {
        throw 'The local PostgreSQL scalar query returned an ambiguous result.'
    }
    return [string]$values[0]
}

function Read-OwnedCrashHelper([string]$ContainerId, [string]$RunId) {
    $container = @(
        (Invoke-Docker @('inspect', $ContainerId) 'Unable to inspect the crash helper.') |
            ConvertFrom-Json
    )
    if (
        $container.Count -ne 1 -or
        $container[0].Id -cne $ContainerId -or
        $container[0].Config.Labels.'com.finaudit.test-purpose' -cne (
            'local-worker-crash-recovery'
        ) -or
        $container[0].Config.Labels.'com.finaudit.run-id' -cne $RunId
    ) {
        throw 'The crash helper ownership is invalid.'
    }
    return $container[0]
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

$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'The local application data directory is unavailable.'
}
$runtimeDirectory = [IO.Path]::GetFullPath(
    (Join-Path $localAppData "FinAuditAgent\runtime\$ProjectName")
)
$markerPath = Join-Path $runtimeDirectory $markerName
$composeEnvPath = Join-Path $runtimeDirectory 'compose.env'
if (
    -not (Test-Path -LiteralPath $markerPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $composeEnvPath -PathType Leaf)
) {
    throw 'No managed FinAudit local runtime exists for this project name.'
}
$marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
if (
    $marker.schemaVersion -cne 'finaudit-local-runtime-v1' -or
    $marker.projectName -cne $ProjectName
) {
    throw 'The runtime ownership marker is invalid.'
}
$composeEnv = @{}
foreach ($line in (Get-Content -LiteralPath $composeEnvPath)) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') {
        $composeEnv[$Matches[1]] = $Matches[2]
    }
}
$httpsPort = 0
$imageRevision = [string]$composeEnv['FINAUDIT_IMAGE_REVISION']
if (
    -not [int]::TryParse([string]$composeEnv['FINAUDIT_HTTPS_PORT'], [ref]$httpsPort) -or
    $httpsPort -lt 1024 -or
    $httpsPort -gt 65535 -or
    [string]::IsNullOrWhiteSpace($imageRevision)
) {
    throw 'The managed Compose environment is invalid.'
}

Read-DependencyHealth $httpsPort
Write-Output 'LOCAL_STACK_DEPENDENCY_GATE=PASS'

if ($FileUpload) {
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n'
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $passwordMount = $passwordFile.Replace('\', '/')
    $output = Invoke-Docker @(
        'run', '--rm', '--network', $network[0], '--read-only',
        '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
        '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
        '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
        '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
        '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
        "finaudit-backend-local:$imageRevision",
        'python', '/app/scripts/smoke_local_file_upload.py'
    ) 'The local TLS multipart/ClamAV/Worker smoke failed.'
    if ($output -notmatch '(?m)^LOCAL_FILE_UPLOAD_SMOKE=PASS\r?$') {
        throw 'The local file smoke did not return its PASS gate.'
    }
    Write-Output $output
}

if ($WorkerCrashRecovery) {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $clamav = Read-ComposeContainer $ProjectName 'clamav'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $clamav.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The crash recovery target services are not running.'
    }
    $workerId = [string]$worker.Id

    $runId = [Guid]::NewGuid().ToString('N')
    $helperName = "finaudit-worker-crash-$runId"
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $stateDirectory = [IO.Path]::GetFullPath(
        (Join-Path $temporaryRoot "finaudit-worker-crash-$runId")
    )
    if (-not (Test-IsExactChild $temporaryRoot $stateDirectory)) {
        throw 'The crash recovery state directory escaped the temporary root.'
    }
    $statePath = Join-Path $stateDirectory 'status.json'
    $passwordMount = $passwordFile.Replace('\', '/')
    $stateMount = $stateDirectory.Replace('\', '/')
    $helperId = $null
    $clamavPaused = $false
    $gateStartedAt = [DateTimeOffset]::UtcNow

    try {
        $null = New-Item -ItemType Directory -Path $stateDirectory
        $null = Invoke-Docker @('pause', $clamav.Id) 'Unable to pause the local Scanner.'
        $clamavPaused = $true
        $helperId = Invoke-Docker @(
            'run', '--detach', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-worker-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--name', $helperName,
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--mount', "type=bind,src=$stateMount,dst=/state",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', 'FINAUDIT_CRASH_STATE_PATH=/state/status.json',
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_worker_crash_recovery.py', 'client'
        ) 'Unable to start the worker crash helper.'
        if ($helperId -notmatch '^[0-9a-f]{64}$') {
            throw 'Docker returned an invalid crash helper identity.'
        }
        $null = Read-OwnedCrashHelper $helperId $runId

        $runningState = $null
        $runningDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $runningDeadline) {
            if (Test-Path -LiteralPath $statePath -PathType Leaf) {
                try {
                    $candidate = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                    if ($candidate.phase -ceq 'running') {
                        $runningState = $candidate
                        break
                    }
                }
                catch {
                    # 原子替换在 Windows bind mount 上仍可能出现短暂读取竞争，继续等待。
                }
            }
            $helper = Read-OwnedCrashHelper $helperId $runId
            if ($helper.State.Status -cne 'running') {
                throw 'The crash helper exited before the Job reached running.'
            }
            Start-Sleep -Milliseconds 500
        }
        if (
            $null -eq $runningState -or
            $runningState.schema_version -cne 'finaudit-local-worker-crash-v1' -or
            $runningState.file_id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' -or
            $runningState.job_id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        ) {
            throw 'The crash helper running-state manifest is invalid.'
        }

        $worker = Read-ComposeContainer $ProjectName 'worker'
        if ($worker.Id -cne $workerId -or $worker.State.Status -cne 'running') {
            throw 'The worker identity changed before the crash injection.'
        }
        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $workerId) `
            'Unable to SIGKILL the owned local Worker.'
        if ($killed -cne $workerId) {
            throw 'Docker did not confirm the exact Worker crash target.'
        }
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if (
            $stoppedWorker.Id -cne $workerId -or
            $stoppedWorker.State.Status -cne 'exited' -or
            [int]$stoppedWorker.State.ExitCode -ne 137
        ) {
            throw 'The owned local Worker did not reach the expected SIGKILL state.'
        }
        $null = Invoke-Docker @('unpause', $clamav.Id) 'Unable to unpause the local Scanner.'
        $clamavPaused = $false
        $started = Invoke-Docker @('start', $workerId) `
            'Unable to perform the managed Worker restart.'
        if ($started -cne $workerId) {
            throw 'Docker did not confirm the exact managed Worker restart target.'
        }

        $workerRecovered = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if (
                $currentWorker.Id -ceq $workerId -and
                $currentWorker.State.Status -ceq 'running'
            ) {
                $workerRecovered = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRecovered) {
            throw 'The local Worker did not recover after the managed restart.'
        }

        $helperExitCode = $null
        $helperDeadline = [DateTimeOffset]::UtcNow.AddSeconds(210)
        while ([DateTimeOffset]::UtcNow -lt $helperDeadline) {
            $helper = Read-OwnedCrashHelper $helperId $runId
            if ($helper.State.Status -in @('exited', 'dead')) {
                $helperExitCode = [int]$helper.State.ExitCode
                break
            }
            Start-Sleep -Seconds 1
        }
        $helperLogs = Invoke-Docker @('logs', $helperId) 'Unable to read the crash helper logs.'
        Write-Output $helperLogs
        if (
            $helperExitCode -ne 0 -or
            $helperLogs -notmatch '(?m)^LOCAL_WORKER_CRASH_CLIENT_GATE=PASS\r?$'
        ) {
            throw 'The client-visible worker crash recovery gate failed.'
        }

        $databaseOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_FILE_ID=$($runningState.file_id)",
                '--env', "FINAUDIT_CRASH_JOB_ID=$($runningState.job_id)",
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                'maintenance', 'python',
                '/app/scripts/smoke_local_worker_crash_recovery.py', 'database'
            )
        ) 'The database worker crash recovery gate failed.'
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch '(?m)^LOCAL_WORKER_CRASH_DATABASE_GATE=PASS\r?$') {
            throw 'The database worker crash recovery gate did not return PASS.'
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenance.Id
        ) 'Unable to read the Maintenance recovery logs.'
        $expectedOutcome = (
            'MAINTENANCE_OUTCOME outcome=claimed_and_succeeded job_id=' +
            [regex]::Escape([string]$runningState.job_id)
        )
        if ($maintenanceLogs -notmatch $expectedOutcome) {
            throw 'The Maintenance process did not record the expected recovery outcome.'
        }

        Read-DependencyHealth $httpsPort
        Write-Output 'LOCAL_WORKER_SIGKILL_GATE=PASS'
        Write-Output 'LOCAL_WORKER_MANAGED_RESTART_GATE=PASS'
        Write-Output 'LOCAL_WORKER_LEASE_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_WORKER_FILE_PROCESS_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_WORKER_CONTRACT_EXTRACT_AFTER_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_WORKER_CRASH_STACK_RESTORED=PASS'
    }
    finally {
        if ($clamavPaused) {
            $currentClamav = Read-ComposeContainer $ProjectName 'clamav'
            if ($currentClamav.Id -cne $clamav.Id) {
                throw 'Refusing to unpause a Scanner whose identity changed.'
            }
            $null = Invoke-Docker @('unpause', $clamav.Id) `
                'Unable to restore the paused local Scanner.'
        }
        if ($null -ne $helperId) {
            $null = Read-OwnedCrashHelper $helperId $runId
            $null = Invoke-Docker @('rm', '--force', '--volumes', $helperId) `
                'Unable to remove the owned crash helper.'
        }
        if (Test-Path -LiteralPath $stateDirectory -PathType Container) {
            if (-not (Test-IsExactChild $temporaryRoot $stateDirectory)) {
                throw 'Refusing to remove an unsafe crash recovery state directory.'
            }
            [IO.Directory]::Delete($stateDirectory, $true)
        }
    }
}

if ($ContractExtractionCrashRecovery -or $InvoiceExtractionCrashRecovery) {
    if ($ContractExtractionCrashRecovery) {
        $extractionKind = 'contract'
        $extractionTable = 'contracts'
        $extractionScript = 'smoke_local_contract_extraction_crash_recovery.py'
        $extractionStateSchema = 'finaudit-local-contract-extract-crash-v1'
        $extractionPurpose = 'local-contract-extract-crash-recovery'
        $prepareGate = 'LOCAL_CONTRACT_EXTRACT_CRASH_PREPARE_GATE=PASS'
        $runningGate = 'LOCAL_CONTRACT_EXTRACT_RUNNING_GATE=PASS'
        $runningJobPrefix = 'LOCAL_CONTRACT_EXTRACT_RUNNING_JOB_ID='
        $zeroFactsGate = 'LOCAL_CONTRACT_EXTRACT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS'
        $clientGate = 'LOCAL_CONTRACT_EXTRACT_CRASH_CLIENT_GATE=PASS'
        $databaseGate = 'LOCAL_CONTRACT_EXTRACT_CRASH_DATABASE_GATE=PASS'
        $sigkillGate = 'LOCAL_CONTRACT_EXTRACT_SIGKILL_GATE=PASS'
        $restartGate = 'LOCAL_CONTRACT_EXTRACT_MANAGED_RESTART_GATE=PASS'
        $leaseGate = 'LOCAL_CONTRACT_EXTRACT_LEASE_RECOVERY_GATE=PASS'
        $attemptGate = 'LOCAL_CONTRACT_EXTRACT_ATTEMPT_TWO_GATE=PASS'
        $factsGate = 'LOCAL_CONTRACT_EXTRACT_UNIQUE_FACTS_GATE=PASS'
        $restoredGate = 'LOCAL_CONTRACT_EXTRACT_CRASH_STACK_RESTORED=PASS'
    }
    else {
        $extractionKind = 'invoice'
        $extractionTable = 'invoices'
        $extractionScript = 'smoke_local_invoice_extraction_crash_recovery.py'
        $extractionStateSchema = 'finaudit-local-invoice-extract-crash-v1'
        $extractionPurpose = 'local-invoice-extract-crash-recovery'
        $prepareGate = 'LOCAL_INVOICE_EXTRACT_CRASH_PREPARE_GATE=PASS'
        $runningGate = 'LOCAL_INVOICE_EXTRACT_RUNNING_GATE=PASS'
        $runningJobPrefix = 'LOCAL_INVOICE_EXTRACT_RUNNING_JOB_ID='
        $zeroFactsGate = 'LOCAL_INVOICE_EXTRACT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS'
        $clientGate = 'LOCAL_INVOICE_EXTRACT_CRASH_CLIENT_GATE=PASS'
        $databaseGate = 'LOCAL_INVOICE_EXTRACT_CRASH_DATABASE_GATE=PASS'
        $sigkillGate = 'LOCAL_INVOICE_EXTRACT_SIGKILL_GATE=PASS'
        $restartGate = 'LOCAL_INVOICE_EXTRACT_MANAGED_RESTART_GATE=PASS'
        $leaseGate = 'LOCAL_INVOICE_EXTRACT_LEASE_RECOVERY_GATE=PASS'
        $attemptGate = 'LOCAL_INVOICE_EXTRACT_ATTEMPT_TWO_GATE=PASS'
        $factsGate = 'LOCAL_INVOICE_EXTRACT_UNIQUE_FACTS_GATE=PASS'
        $restoredGate = 'LOCAL_INVOICE_EXTRACT_CRASH_STACK_RESTORED=PASS'
    }
    $extractionLabel = "$extractionKind extraction"
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $postgresql = Read-ComposeContainer $ProjectName 'postgresql'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $postgresql.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw "The $extractionLabel crash recovery target services are not running."
    }
    $workerId = [string]$worker.Id
    $postgresqlId = [string]$postgresql.Id
    $runId = [Guid]::NewGuid().ToString('N')
    $lockApplicationName = "finaudit-$extractionKind-crash-$runId"
    if ($lockApplicationName.Length -gt 63) {
        throw "The $extractionLabel lock identity is invalid."
    }
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $stateDirectory = [IO.Path]::GetFullPath(
        (Join-Path $temporaryRoot "finaudit-$extractionKind-crash-$runId")
    )
    if (-not (Test-IsExactChild $temporaryRoot $stateDirectory)) {
        throw "The $extractionLabel crash state directory escaped the temporary root."
    }
    $statePath = Join-Path $stateDirectory 'status.json'
    $passwordMount = $passwordFile.Replace('\', '/')
    $stateMount = $stateDirectory.Replace('\', '/')
    $lockHeld = $false
    $lockProcessStarted = $false
    $workerNeedsRestart = $false
    $gateStartedAt = [DateTimeOffset]::UtcNow
    $lockSessionCountQuery = (
        'SELECT count(*) FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName';"
    )
    $terminateQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName' " +
        'AND pid <> pg_backend_pid()' +
        ') AS result WHERE terminated;'
    )

    try {
        $null = New-Item -ItemType Directory -Path $stateDirectory
        $lockQuery = (
            "BEGIN; LOCK TABLE public.$extractionTable IN ACCESS EXCLUSIVE MODE; " +
            'SELECT pg_sleep(600); COMMIT;'
        )
        $null = Invoke-Docker @(
            'exec', '--detach', '--env', "PGAPPNAME=$lockApplicationName",
            $postgresqlId,
            'psql', '--username', 'finaudit', '--dbname', 'finaudit',
            '--set', 'ON_ERROR_STOP=1', '--command', $lockQuery
        ) "Unable to start the owned $extractionLabel database lock."
        $lockProcessStarted = $true

        $lockCountQuery = (
            'SELECT count(*) FROM pg_stat_activity AS activity ' +
            'JOIN pg_locks AS held ON held.pid = activity.pid ' +
            "WHERE activity.application_name = '$lockApplicationName' " +
            "AND held.relation = 'public.$extractionTable'::regclass " +
            "AND held.mode = 'AccessExclusiveLock' AND held.granted;"
        )
        $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $lockDeadline) {
            $lockCount = Read-PostgresScalar $postgresqlId $lockCountQuery
            if ($lockCount -ceq '1') {
                $lockHeld = $true
                break
            }
            if ($lockCount -cne '0') {
                throw "The owned $extractionLabel database lock is ambiguous."
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $lockHeld) {
            throw "The owned $extractionLabel database lock was not acquired."
        }

        $prepareOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', "com.finaudit.test-purpose=$extractionPurpose",
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--mount', "type=bind,src=$stateMount,dst=/state",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', 'FINAUDIT_CRASH_STATE_PATH=/state/status.json',
            "finaudit-backend-local:$imageRevision",
            'python', "/app/scripts/$extractionScript",
            'prepare'
        ) "The $extractionLabel crash prepare helper failed."
        Write-Output $prepareOutput
        if ($prepareOutput -notmatch "(?m)^$prepareGate\r?$") {
            throw "The $extractionLabel crash prepare helper did not return PASS."
        }
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            throw "The $extractionLabel crash state manifest is missing."
        }
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if (
            $state.schema_version -cne $extractionStateSchema -or
            $state.phase -cne 'file_ready' -or
            $state.run_id -cne $runId -or
            $state.file_id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' -or
            $state.file_job_id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' -or
            $state.file_sha256 -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "The $extractionLabel crash state manifest is invalid."
        }

        $runningOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_FILE_ID=$($state.file_id)",
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                'maintenance', 'python',
                "/app/scripts/$extractionScript",
                'wait-running'
            )
        ) "The $extractionLabel running-state gate failed."
        Write-Output $runningOutput
        if ($runningOutput -notmatch "(?m)^$runningGate\r?$") {
            throw "The $extractionLabel running-state gate did not return PASS."
        }
        $jobMatch = [regex]::Match(
            $runningOutput,
            "(?m)^$runningJobPrefix([0-9a-f-]{36})\r?$"
        )
        if (
            -not $jobMatch.Success -or
            $jobMatch.Groups[1].Value -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        ) {
            throw "The $extractionLabel running Job identity is invalid."
        }
        $extractionJobId = $jobMatch.Groups[1].Value

        $worker = Read-ComposeContainer $ProjectName 'worker'
        if ($worker.Id -cne $workerId -or $worker.State.Status -cne 'running') {
            throw "The Worker identity changed before $extractionLabel crash injection."
        }
        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $workerId) `
            "Unable to SIGKILL the owned local Worker during $extractionLabel."
        if ($killed -cne $workerId) {
            throw "Docker did not confirm the exact $extractionLabel Worker target."
        }
        $workerNeedsRestart = $true
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if (
            $stoppedWorker.Id -cne $workerId -or
            $stoppedWorker.State.Status -cne 'exited' -or
            [int]$stoppedWorker.State.ExitCode -ne 137
        ) {
            throw "The $extractionLabel Worker did not reach the expected SIGKILL state."
        }

        $terminated = Read-PostgresScalar $postgresqlId $terminateQuery
        if ($terminated -cne '1') {
            throw "The owned $extractionLabel database lock was not terminated exactly once."
        }
        $lockHeld = $false
        if ((Read-PostgresScalar $postgresqlId $lockCountQuery) -cne '0') {
            throw "The owned $extractionLabel database lock was not released."
        }
        if ((Read-PostgresScalar $postgresqlId $lockSessionCountQuery) -cne '0') {
            throw "The owned $extractionLabel database session was not released."
        }
        $lockProcessStarted = $false

        $beforeRecoveryOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_FILE_ID=$($state.file_id)",
                '--env', "FINAUDIT_CRASH_EXTRACTION_JOB_ID=$extractionJobId",
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                'maintenance', 'python',
                "/app/scripts/$extractionScript",
                'before-recovery'
            )
        ) "The pre-recovery $extractionLabel database gate failed."
        Write-Output $beforeRecoveryOutput
        if ($beforeRecoveryOutput -notmatch "(?m)^$zeroFactsGate\r?$") {
            throw "The pre-recovery $extractionLabel database gate did not return PASS."
        }

        $started = Invoke-Docker @('start', $workerId) `
            "Unable to perform the managed Worker restart after $extractionLabel crash."
        if ($started -cne $workerId) {
            throw 'Docker did not confirm the exact managed Worker restart target.'
        }
        $workerNeedsRestart = $false
        $workerRecovered = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if (
                $currentWorker.Id -ceq $workerId -and
                $currentWorker.State.Status -ceq 'running'
            ) {
                $workerRecovered = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRecovered) {
            throw "The local Worker did not recover after the $extractionLabel crash."
        }

        $clientOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', "com.finaudit.test-purpose=$extractionPurpose",
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_CRASH_FILE_ID=$($state.file_id)",
            '--env', "FINAUDIT_CRASH_FILE_SHA256=$($state.file_sha256)",
            "finaudit-backend-local:$imageRevision",
            'python', "/app/scripts/$extractionScript",
            'verify-client'
        ) "The client-visible $extractionLabel crash recovery gate failed."
        Write-Output $clientOutput
        if ($clientOutput -notmatch "(?m)^$clientGate\r?$") {
            throw "The client-visible $extractionLabel crash recovery gate did not return PASS."
        }

        $databaseOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_FILE_ID=$($state.file_id)",
                '--env', "FINAUDIT_CRASH_EXTRACTION_JOB_ID=$extractionJobId",
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                'maintenance', 'python',
                "/app/scripts/$extractionScript",
                'database'
            )
        ) "The database $extractionLabel crash recovery gate failed."
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch "(?m)^$databaseGate\r?$") {
            throw "The database $extractionLabel crash recovery gate did not return PASS."
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenance.Id
        ) "Unable to read the Maintenance $extractionLabel recovery logs."
        $expectedOutcome = (
            'MAINTENANCE_OUTCOME outcome=claimed_and_succeeded job_id=' +
            [regex]::Escape($extractionJobId)
        )
        if ($maintenanceLogs -notmatch $expectedOutcome) {
            throw "Maintenance did not record the expected $extractionLabel recovery outcome."
        }

        Read-DependencyHealth $httpsPort
        Write-Output $sigkillGate
        Write-Output $restartGate
        Write-Output $leaseGate
        Write-Output $attemptGate
        Write-Output $factsGate
        Write-Output $restoredGate
    }
    finally {
        if ($lockProcessStarted) {
            $cleanupSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            if ($cleanupSessionCount -ceq '1') {
                $cleanupTerminated = Read-PostgresScalar $postgresqlId $terminateQuery
                if ($cleanupTerminated -cne '1') {
                    throw "Unable to release the owned $extractionLabel database session."
                }
            }
            elseif ($cleanupSessionCount -cne '0') {
                throw "Refusing to release an ambiguous $extractionLabel database session."
            }
        }
        if ($workerNeedsRestart) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -cne $workerId) {
                throw 'Refusing to restore a Worker whose identity changed.'
            }
            if ($currentWorker.State.Status -ceq 'exited') {
                $restoredWorker = Invoke-Docker @('start', $workerId) `
                    'Unable to restore the owned local Worker.'
                if ($restoredWorker -cne $workerId) {
                    throw 'Docker did not confirm restoration of the owned local Worker.'
                }
            }
            elseif ($currentWorker.State.Status -cne 'running') {
                throw 'The owned local Worker is not in a restorable state.'
            }
        }
        if (Test-Path -LiteralPath $stateDirectory -PathType Container) {
            if (-not (Test-IsExactChild $temporaryRoot $stateDirectory)) {
                throw "Refusing to remove an unsafe $extractionLabel crash state directory."
            }
            [IO.Directory]::Delete($stateDirectory, $true)
        }
    }
}

if ($AuditExecutionCrashRecovery) {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $postgresql = Read-ComposeContainer $ProjectName 'postgresql'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $postgresql.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The audit execution crash recovery target services are not running.'
    }
    $workerId = [string]$worker.Id
    $postgresqlId = [string]$postgresql.Id
    $runId = [Guid]::NewGuid().ToString('N')
    $lockApplicationName = "finaudit-audit-crash-$runId"
    if ($lockApplicationName.Length -gt 63) {
        throw 'The audit execution lock identity is invalid.'
    }
    $passwordMount = $passwordFile.Replace('\', '/')
    $lockHeld = $false
    $lockProcessStarted = $false
    $workerNeedsRestart = $false
    $gateStartedAt = [DateTimeOffset]::UtcNow
    $lockSessionCountQuery = (
        'SELECT count(*) FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName';"
    )
    $terminateQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName' " +
        'AND pid <> pg_backend_pid()' +
        ') AS result WHERE terminated;'
    )
    $lockCountQuery = (
        'SELECT count(*) FROM pg_stat_activity AS activity ' +
        'JOIN pg_locks AS held ON held.pid = activity.pid ' +
        "WHERE activity.application_name = '$lockApplicationName' " +
        "AND held.relation = 'public.rule_executions'::regclass " +
        "AND held.mode = 'AccessExclusiveLock' AND held.granted;"
    )
    $waitingLockCountQuery = (
        'SELECT count(*) FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.rule_executions'::regclass " +
        'AND NOT waiting.granted;'
    )
    $terminateWaitingQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.rule_executions'::regclass " +
        'AND NOT waiting.granted' +
        ') AS result WHERE terminated;'
    )

    try {
        $lockQuery = (
            'BEGIN; LOCK TABLE public.rule_executions IN ACCESS EXCLUSIVE MODE; ' +
            'SELECT pg_sleep(600); COMMIT;'
        )
        $null = Invoke-Docker @(
            'exec', '--detach', '--env', "PGAPPNAME=$lockApplicationName",
            $postgresqlId,
            'psql', '--username', 'finaudit', '--dbname', 'finaudit',
            '--set', 'ON_ERROR_STOP=1', '--command', $lockQuery
        ) 'Unable to start the owned audit execution database lock.'
        $lockProcessStarted = $true

        $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $lockDeadline) {
            $lockCount = Read-PostgresScalar $postgresqlId $lockCountQuery
            if ($lockCount -ceq '1') {
                $lockHeld = $true
                break
            }
            if ($lockCount -cne '0') {
                throw 'The owned audit execution database lock is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $lockHeld) {
            throw 'The owned audit execution database lock was not acquired.'
        }

        $seedOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
                'maintenance', 'python',
                '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
                'seed'
            )
        ) 'The audit execution crash seed helper failed.'
        Write-Output $seedOutput
        if ($seedOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_SEED_GATE=PASS\r?$') {
            throw 'The audit execution crash seed helper did not return PASS.'
        }

        $prepareOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-audit-execute-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
            'prepare'
        ) 'The audit execution crash prepare helper failed.'
        Write-Output $prepareOutput
        if ($prepareOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_PREPARE_GATE=PASS\r?$') {
            throw 'The audit execution crash prepare helper did not return PASS.'
        }
        $canonicalUuidV4 = (
            '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-' +
            '[89ab][0-9a-f]{3}-[0-9a-f]{12}'
        )
        $taskMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_TASK_ID=($canonicalUuidV4)\r?$"
        )
        $executionMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_EXECUTION_ID=($canonicalUuidV4)\r?$"
        )
        $jobMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_JOB_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $taskMatch.Success -or -not $executionMatch.Success -or -not $jobMatch.Success) {
            throw 'The audit execution crash identities are invalid.'
        }
        $taskId = $taskMatch.Groups[1].Value
        $executionId = $executionMatch.Groups[1].Value
        $jobId = $jobMatch.Groups[1].Value
        if (@(@($taskId, $executionId, $jobId) | Select-Object -Unique).Count -ne 3) {
            throw 'The audit execution crash identities are not unique.'
        }

        $runningOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
                '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
                '--env', "FINAUDIT_CRASH_JOB_ID=$jobId",
                'maintenance', 'python',
                '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
                'wait-running'
            )
        ) 'The audit execution running-state gate failed.'
        Write-Output $runningOutput
        if ($runningOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_RUNNING_GATE=PASS\r?$') {
            throw 'The audit execution running-state gate did not return PASS.'
        }
        $runningJobMatch = [regex]::Match(
            $runningOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_RUNNING_JOB_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $runningJobMatch.Success -or $runningJobMatch.Groups[1].Value -cne $jobId) {
            throw 'The running audit Job identity drifted.'
        }

        $waiterObserved = $false
        $waiterDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $waiterDeadline) {
            $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
            if ($waitingCount -ceq '1') {
                $waiterObserved = $true
                break
            }
            if ($waitingCount -cne '0') {
                throw 'The blocked audit execution database session is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $waiterObserved) {
            throw 'The Worker did not reach the controlled audit execution body lock.'
        }

        $worker = Read-ComposeContainer $ProjectName 'worker'
        if ($worker.Id -cne $workerId -or $worker.State.Status -cne 'running') {
            throw 'The Worker identity changed before audit execution crash injection.'
        }
        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $workerId) `
            'Unable to SIGKILL the owned local Worker during audit execution.'
        if ($killed -cne $workerId) {
            throw 'Docker did not confirm the exact audit execution Worker target.'
        }
        $workerNeedsRestart = $true
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if (
            $stoppedWorker.Id -cne $workerId -or
            $stoppedWorker.State.Status -cne 'exited' -or
            [int]$stoppedWorker.State.ExitCode -ne 137
        ) {
            throw 'The audit execution Worker did not reach the expected SIGKILL state.'
        }

        $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
        if ($waitingCount -ceq '1') {
            $terminatedWaiter = Read-PostgresScalar $postgresqlId $terminateWaitingQuery
            if ($terminatedWaiter -cne '1') {
                throw 'The orphaned audit execution database session was not terminated once.'
            }
        }
        elseif ($waitingCount -cne '0') {
            throw 'The blocked audit execution database session changed unexpectedly.'
        }
        if ((Read-PostgresScalar $postgresqlId $waitingLockCountQuery) -cne '0') {
            throw 'The killed Worker database transaction did not roll back.'
        }

        $terminated = Read-PostgresScalar $postgresqlId $terminateQuery
        if ($terminated -cne '1') {
            throw 'The owned audit execution database lock was not terminated exactly once.'
        }
        $lockHeld = $false
        if ((Read-PostgresScalar $postgresqlId $lockCountQuery) -cne '0') {
            throw 'The owned audit execution database lock was not released.'
        }
        if ((Read-PostgresScalar $postgresqlId $lockSessionCountQuery) -cne '0') {
            throw 'The owned audit execution database session was not released.'
        }
        $lockProcessStarted = $false

        $beforeRecoveryOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
                '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
                '--env', "FINAUDIT_CRASH_JOB_ID=$jobId",
                'maintenance', 'python',
                '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
                'before-recovery'
            )
        ) 'The pre-recovery audit execution database gate failed.'
        Write-Output $beforeRecoveryOutput
        if (
            $beforeRecoveryOutput -notmatch
            '(?m)^LOCAL_AUDIT_EXECUTE_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery audit execution database gate did not return PASS.'
        }

        $started = Invoke-Docker @('start', $workerId) `
            'Unable to perform the managed Worker restart after audit execution crash.'
        if ($started -cne $workerId) {
            throw 'Docker did not confirm the exact managed Worker restart target.'
        }
        $workerNeedsRestart = $false
        $workerRecovered = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if (
                $currentWorker.Id -ceq $workerId -and
                $currentWorker.State.Status -ceq 'running'
            ) {
                $workerRecovered = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRecovered) {
            throw 'The local Worker did not recover after the audit execution crash.'
        }

        $clientOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-audit-execute-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
            '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
            '--env', "FINAUDIT_CRASH_JOB_ID=$jobId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
            'verify-client'
        ) 'The client-visible audit execution crash recovery gate failed.'
        Write-Output $clientOutput
        if ($clientOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_CLIENT_GATE=PASS\r?$') {
            throw 'The client-visible audit execution crash recovery gate did not return PASS.'
        }

        $databaseOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
                '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
                '--env', "FINAUDIT_CRASH_JOB_ID=$jobId",
                'maintenance', 'python',
                '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
                'database'
            )
        ) 'The database audit execution crash recovery gate failed.'
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_DATABASE_GATE=PASS\r?$') {
            throw 'The database audit execution crash recovery gate did not return PASS.'
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenance.Id
        ) 'Unable to read the Maintenance audit execution recovery logs.'
        $expectedOutcome = (
            'MAINTENANCE_OUTCOME outcome=claimed_and_succeeded job_id=' +
            [regex]::Escape($jobId)
        )
        if ($maintenanceLogs -notmatch $expectedOutcome) {
            throw 'Maintenance did not record the expected audit execution recovery outcome.'
        }

        Read-DependencyHealth $httpsPort
        Write-Output 'LOCAL_AUDIT_EXECUTE_BODY_LOCK_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_SIGKILL_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_MANAGED_RESTART_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_LEASE_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_ATTEMPT_TWO_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_UNIQUE_FACTS_GATE=PASS'
        Write-Output 'LOCAL_AUDIT_EXECUTE_CRASH_STACK_RESTORED=PASS'
    }
    finally {
        if ($lockProcessStarted) {
            $cleanupSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            if ($cleanupSessionCount -ceq '1') {
                $cleanupTerminated = Read-PostgresScalar $postgresqlId $terminateQuery
                if ($cleanupTerminated -cne '1') {
                    throw 'Unable to release the owned audit execution database session.'
                }
            }
            elseif ($cleanupSessionCount -cne '0') {
                throw 'Refusing to release an ambiguous audit execution database session.'
            }
        }
        if ($workerNeedsRestart) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -cne $workerId) {
                throw 'Refusing to restore a Worker whose identity changed.'
            }
            if ($currentWorker.State.Status -ceq 'exited') {
                $restoredWorker = Invoke-Docker @('start', $workerId) `
                    'Unable to restore the owned local Worker.'
                if ($restoredWorker -cne $workerId) {
                    throw 'Docker did not confirm restoration of the owned local Worker.'
                }
            }
            elseif ($currentWorker.State.Status -cne 'running') {
                throw 'The owned local Worker is not in a restorable state.'
            }
        }
    }
}

if ($ReportGenerationCrashRecovery) {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $postgresql = Read-ComposeContainer $ProjectName 'postgresql'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $postgresql.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The report generation crash recovery target services are not running.'
    }
    $workerId = [string]$worker.Id
    $workerShortId = $workerId.Substring(0, 12)
    $postgresqlId = [string]$postgresql.Id
    $runId = [Guid]::NewGuid().ToString('N')
    $lockApplicationName = "finaudit-report-crash-$runId"
    if ($lockApplicationName.Length -gt 63) {
        throw 'The report generation lock identity is invalid.'
    }
    $passwordMount = $passwordFile.Replace('\', '/')
    $lockProcessStarted = $false
    $workerNeedsRestart = $false
    $gateStartedAt = [DateTimeOffset]::UtcNow
    $lockSessionCountQuery = (
        'SELECT count(*) FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName';"
    )
    $terminateQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName' " +
        'AND pid <> pg_backend_pid()' +
        ') AS result WHERE terminated;'
    )
    $lockCountQuery = (
        'SELECT count(*) FROM pg_stat_activity AS activity ' +
        'JOIN pg_locks AS held ON held.pid = activity.pid ' +
        "WHERE activity.application_name = '$lockApplicationName' " +
        "AND held.relation = 'public.operation_logs'::regclass " +
        "AND held.mode = 'AccessExclusiveLock' AND held.granted;"
    )
    $waitingLockCountQuery = (
        'SELECT count(*) FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.operation_logs'::regclass " +
        'AND NOT waiting.granted;'
    )
    $terminateWaitingQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.operation_logs'::regclass " +
        'AND NOT waiting.granted' +
        ') AS result WHERE terminated;'
    )

    try {
        $seedOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
                'maintenance', 'python',
                '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
                'seed'
            )
        ) 'The report prerequisite audit seed helper failed.'
        Write-Output $seedOutput
        if ($seedOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_SEED_GATE=PASS\r?$') {
            throw 'The report prerequisite audit seed helper did not return PASS.'
        }

        $prepareOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-report-generate-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_audit_execution_crash_recovery.py',
            'prepare'
        ) 'The report prerequisite audit prepare helper failed.'
        Write-Output $prepareOutput
        if ($prepareOutput -notmatch '(?m)^LOCAL_AUDIT_EXECUTE_CRASH_PREPARE_GATE=PASS\r?$') {
            throw 'The report prerequisite audit prepare helper did not return PASS.'
        }
        $canonicalUuidV4 = (
            '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-' +
            '[89ab][0-9a-f]{3}-[0-9a-f]{12}'
        )
        $taskMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_TASK_ID=($canonicalUuidV4)\r?$"
        )
        $executionMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_EXECUTION_ID=($canonicalUuidV4)\r?$"
        )
        $auditJobMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_AUDIT_EXECUTE_JOB_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $taskMatch.Success -or -not $executionMatch.Success -or -not $auditJobMatch.Success) {
            throw 'The report prerequisite audit identities are invalid.'
        }
        $taskId = $taskMatch.Groups[1].Value
        $executionId = $executionMatch.Groups[1].Value
        $auditJobId = $auditJobMatch.Groups[1].Value
        if (@(@($taskId, $executionId, $auditJobId) | Select-Object -Unique).Count -ne 3) {
            throw 'The report prerequisite audit identities are not unique.'
        }

        $auditReadyOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
                '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
                '--env', "FINAUDIT_CRASH_JOB_ID=$auditJobId",
                'maintenance', 'python',
                '/app/scripts/smoke_local_report_generation_crash_recovery.py',
                'wait-audit-ready'
            )
        ) 'The report prerequisite audit execution did not become ready for review.'
        Write-Output $auditReadyOutput
        if ($auditReadyOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_AUDIT_READY_GATE=PASS\r?$') {
            throw 'The report prerequisite audit ready helper did not return PASS.'
        }

        $stopped = Invoke-Docker @('stop', '--timeout', '30', $workerId) `
            'Unable to stop the owned local Worker before report queueing.'
        $workerNeedsRestart = $true
        if ($stopped -cne $workerId -and $stopped -cne $workerShortId) {
            throw 'Docker did not confirm the exact Worker stopped for report queueing.'
        }
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if ($stoppedWorker.Id -cne $workerId -or $stoppedWorker.State.Status -cne 'exited') {
            throw 'The report generation Worker did not stop cleanly before queueing.'
        }

        $queueOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-report-generate-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
            '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
            '--env', "FINAUDIT_CRASH_JOB_ID=$auditJobId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_report_generation_crash_recovery.py',
            'queue-report'
        ) 'The report queue helper failed.'
        Write-Output $queueOutput
        if ($queueOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_QUEUE_GATE=PASS\r?$') {
            throw 'The report queue helper did not return PASS.'
        }
        $reportMatch = [regex]::Match(
            $queueOutput,
            "(?m)^LOCAL_REPORT_GENERATE_REPORT_ID=($canonicalUuidV4)\r?$"
        )
        $reportJobMatch = [regex]::Match(
            $queueOutput,
            "(?m)^LOCAL_REPORT_GENERATE_JOB_ID=($canonicalUuidV4)\r?$"
        )
        $reportVersionMatch = [regex]::Match(
            $queueOutput,
            '(?m)^LOCAL_REPORT_GENERATE_VERSION=([1-9][0-9]*)\r?$'
        )
        $payloadHashMatch = [regex]::Match(
            $queueOutput,
            '(?m)^LOCAL_REPORT_GENERATE_PAYLOAD_SHA256=([0-9a-f]{64})\r?$'
        )
        if (
            -not $reportMatch.Success -or
            -not $reportJobMatch.Success -or
            -not $reportVersionMatch.Success -or
            -not $payloadHashMatch.Success
        ) {
            throw 'The queued report identities are invalid.'
        }
        $reportId = $reportMatch.Groups[1].Value
        $reportJobId = $reportJobMatch.Groups[1].Value
        $reportVersion = $reportVersionMatch.Groups[1].Value
        $reportPayloadSha256 = $payloadHashMatch.Groups[1].Value
        if (@(@($taskId, $executionId, $auditJobId, $reportId, $reportJobId) | Select-Object -Unique).Count -ne 5) {
            throw 'The report crash recovery identities are not unique.'
        }

        $lockQuery = (
            'BEGIN; LOCK TABLE public.operation_logs IN ACCESS EXCLUSIVE MODE; ' +
            'SELECT pg_sleep(600); COMMIT;'
        )
        $null = Invoke-Docker @(
            'exec', '--detach', '--env', "PGAPPNAME=$lockApplicationName",
            $postgresqlId,
            'psql', '--username', 'finaudit', '--dbname', 'finaudit',
            '--set', 'ON_ERROR_STOP=1', '--command', $lockQuery
        ) 'Unable to start the owned report generation database lock.'
        $lockProcessStarted = $true
        $lockHeld = $false
        $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $lockDeadline) {
            $lockCount = Read-PostgresScalar $postgresqlId $lockCountQuery
            if ($lockCount -ceq '1') {
                $lockHeld = $true
                break
            }
            if ($lockCount -cne '0') {
                throw 'The owned report generation database lock is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $lockHeld) {
            throw 'The owned report generation database lock was not acquired.'
        }

        $started = Invoke-Docker @('start', $workerId) `
            'Unable to start the owned Worker for report generation fault injection.'
        if ($started -cne $workerId -and $started -cne $workerShortId) {
            throw 'Docker did not confirm the exact Worker start for report generation.'
        }
        $workerNeedsRestart = $false
        $workerRunning = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -ceq $workerId -and $currentWorker.State.Status -ceq 'running') {
                $workerRunning = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRunning) {
            throw 'The report generation Worker did not start.'
        }

        $reportEnvironment = @(
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
            '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
            '--env', "FINAUDIT_CRASH_JOB_ID=$auditJobId",
            '--env', "FINAUDIT_REPORT_ID=$reportId",
            '--env', "FINAUDIT_REPORT_JOB_ID=$reportJobId",
            '--env', "FINAUDIT_REPORT_VERSION=$reportVersion"
        )
        $runningOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $reportEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_report_generation_crash_recovery.py',
                'wait-running'
            )
        ) 'The report generation running-state gate failed.'
        Write-Output $runningOutput
        if ($runningOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_RUNNING_GATE=PASS\r?$') {
            throw 'The report generation running-state gate did not return PASS.'
        }
        $runningJobMatch = [regex]::Match(
            $runningOutput,
            "(?m)^LOCAL_REPORT_GENERATE_RUNNING_JOB_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $runningJobMatch.Success -or $runningJobMatch.Groups[1].Value -cne $reportJobId) {
            throw 'The running report Job identity drifted.'
        }

        $waiterObserved = $false
        $waiterDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $waiterDeadline) {
            $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
            if ($waitingCount -ceq '1') {
                $waiterObserved = $true
                break
            }
            if ($waitingCount -cne '0') {
                throw 'The blocked report generation database session is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $waiterObserved) {
            throw 'The Worker did not reach the controlled report generation body lock.'
        }

        $objectsOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $reportEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_report_generation_crash_recovery.py',
                'verify-objects'
            )
        ) 'The pre-crash report object verification failed.'
        Write-Output $objectsOutput
        if ($objectsOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_OBJECTS_BEFORE_CRASH_GATE=PASS\r?$') {
            throw 'The pre-crash report object verification did not return PASS.'
        }
        $pdfHashMatch = [regex]::Match(
            $objectsOutput,
            '(?m)^LOCAL_REPORT_GENERATE_PRECRASH_PDF_SHA256=([0-9a-f]{64})\r?$'
        )
        $pdfSizeMatch = [regex]::Match(
            $objectsOutput,
            '(?m)^LOCAL_REPORT_GENERATE_PRECRASH_PDF_SIZE=([1-9][0-9]*)\r?$'
        )
        $xlsxHashMatch = [regex]::Match(
            $objectsOutput,
            '(?m)^LOCAL_REPORT_GENERATE_PRECRASH_XLSX_SHA256=([0-9a-f]{64})\r?$'
        )
        $xlsxSizeMatch = [regex]::Match(
            $objectsOutput,
            '(?m)^LOCAL_REPORT_GENERATE_PRECRASH_XLSX_SIZE=([1-9][0-9]*)\r?$'
        )
        if (
            -not $pdfHashMatch.Success -or
            -not $pdfSizeMatch.Success -or
            -not $xlsxHashMatch.Success -or
            -not $xlsxSizeMatch.Success
        ) {
            throw 'The pre-crash report artifact identities are invalid.'
        }
        $reportPdfSha256 = $pdfHashMatch.Groups[1].Value
        $reportPdfSize = $pdfSizeMatch.Groups[1].Value
        $reportXlsxSha256 = $xlsxHashMatch.Groups[1].Value
        $reportXlsxSize = $xlsxSizeMatch.Groups[1].Value

        $worker = Read-ComposeContainer $ProjectName 'worker'
        if ($worker.Id -cne $workerId -or $worker.State.Status -cne 'running') {
            throw 'The Worker identity changed before report generation crash injection.'
        }
        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $workerId) `
            'Unable to SIGKILL the owned local Worker during report generation.'
        $workerNeedsRestart = $true
        if ($killed -cne $workerId -and $killed -cne $workerShortId) {
            throw 'Docker did not confirm the exact report generation Worker target.'
        }
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if (
            $stoppedWorker.Id -cne $workerId -or
            $stoppedWorker.State.Status -cne 'exited' -or
            [int]$stoppedWorker.State.ExitCode -ne 137
        ) {
            throw 'The report generation Worker did not reach the expected SIGKILL state.'
        }

        $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
        if ($waitingCount -ceq '1') {
            $terminatedWaiter = Read-PostgresScalar $postgresqlId $terminateWaitingQuery
            if ($terminatedWaiter -cne '1') {
                throw 'The orphaned report generation database session was not terminated once.'
            }
        }
        elseif ($waitingCount -cne '0') {
            throw 'The blocked report generation database session changed unexpectedly.'
        }
        if ((Read-PostgresScalar $postgresqlId $waitingLockCountQuery) -cne '0') {
            throw 'The killed report Worker database transaction did not roll back.'
        }

        $terminated = Read-PostgresScalar $postgresqlId $terminateQuery
        if ($terminated -cne '1') {
            throw 'The owned report generation database lock was not terminated exactly once.'
        }
        if ((Read-PostgresScalar $postgresqlId $lockCountQuery) -cne '0') {
            throw 'The owned report generation database lock was not released.'
        }
        if ((Read-PostgresScalar $postgresqlId $lockSessionCountQuery) -cne '0') {
            throw 'The owned report generation database session was not released.'
        }
        $lockProcessStarted = $false

        $beforeRecoveryOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $reportEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_report_generation_crash_recovery.py',
                'before-recovery'
            )
        ) 'The pre-recovery report generation gate failed.'
        Write-Output $beforeRecoveryOutput
        if (
            $beforeRecoveryOutput -notmatch
            '(?m)^LOCAL_REPORT_GENERATE_ZERO_DATABASE_FACTS_BEFORE_RECOVERY_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery report database gate did not return PASS.'
        }
        if (
            $beforeRecoveryOutput -notmatch
            '(?m)^LOCAL_REPORT_GENERATE_ORPHAN_OBJECTS_PRESERVED_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery orphan report object gate did not return PASS.'
        }

        $started = Invoke-Docker @('start', $workerId) `
            'Unable to perform the managed Worker restart after report generation crash.'
        if ($started -cne $workerId -and $started -cne $workerShortId) {
            throw 'Docker did not confirm the exact managed report Worker restart target.'
        }
        $workerNeedsRestart = $false
        $workerRecovered = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -ceq $workerId -and $currentWorker.State.Status -ceq 'running') {
                $workerRecovered = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRecovered) {
            throw 'The local Worker did not recover after the report generation crash.'
        }

        $clientOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-report-generate-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_CRASH_TASK_ID=$taskId",
            '--env', "FINAUDIT_CRASH_EXECUTION_ID=$executionId",
            '--env', "FINAUDIT_CRASH_JOB_ID=$auditJobId",
            '--env', "FINAUDIT_REPORT_ID=$reportId",
            '--env', "FINAUDIT_REPORT_JOB_ID=$reportJobId",
            '--env', "FINAUDIT_REPORT_VERSION=$reportVersion",
            '--env', "FINAUDIT_REPORT_PAYLOAD_SHA256=$reportPayloadSha256",
            '--env', "FINAUDIT_REPORT_PDF_SHA256=$reportPdfSha256",
            '--env', "FINAUDIT_REPORT_PDF_SIZE=$reportPdfSize",
            '--env', "FINAUDIT_REPORT_XLSX_SHA256=$reportXlsxSha256",
            '--env', "FINAUDIT_REPORT_XLSX_SIZE=$reportXlsxSize",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_report_generation_crash_recovery.py',
            'verify-client'
        ) 'The client-visible report generation crash recovery gate failed.'
        Write-Output $clientOutput
        if ($clientOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_CRASH_CLIENT_GATE=PASS\r?$') {
            throw 'The client-visible report generation crash recovery gate did not return PASS.'
        }

        $databaseOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $reportEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_report_generation_crash_recovery.py',
                'database'
            )
        ) 'The database report generation crash recovery gate failed.'
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch '(?m)^LOCAL_REPORT_GENERATE_CRASH_DATABASE_GATE=PASS\r?$') {
            throw 'The database report generation crash recovery gate did not return PASS.'
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenance.Id
        ) 'Unable to read the Maintenance report generation recovery logs.'
        $expectedOutcome = (
            'MAINTENANCE_OUTCOME outcome=claimed_and_succeeded job_id=' +
            [regex]::Escape($reportJobId)
        )
        if ($maintenanceLogs -notmatch $expectedOutcome) {
            throw 'Maintenance did not record the expected report generation recovery outcome.'
        }

        Read-DependencyHealth $httpsPort
        Write-Output 'LOCAL_REPORT_GENERATE_BODY_LOCK_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_SIGKILL_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_MANAGED_RESTART_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_LEASE_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_ATTEMPT_TWO_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_UNIQUE_FACTS_GATE=PASS'
        Write-Output 'LOCAL_REPORT_GENERATE_CRASH_STACK_RESTORED=PASS'
    }
    finally {
        if ($lockProcessStarted) {
            $cleanupSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            if ($cleanupSessionCount -ceq '1') {
                $cleanupTerminated = Read-PostgresScalar $postgresqlId $terminateQuery
                if ($cleanupTerminated -cne '1') {
                    throw 'Unable to release the owned report generation database session.'
                }
            }
            elseif ($cleanupSessionCount -cne '0') {
                throw 'Refusing to release an ambiguous report generation database session.'
            }
        }
        if ($workerNeedsRestart) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -cne $workerId) {
                throw 'Refusing to restore a report Worker whose identity changed.'
            }
            if ($currentWorker.State.Status -ceq 'exited') {
                $restoredWorker = Invoke-Docker @('start', $workerId) `
                    'Unable to restore the owned local Worker.'
                if (
                    $restoredWorker -cne $workerId -and
                    $restoredWorker -cne $workerShortId
                ) {
                    throw 'Docker did not confirm restoration of the owned report Worker.'
                }
            }
            elseif ($currentWorker.State.Status -cne 'running') {
                throw 'The owned report Worker is not in a restorable state.'
            }
        }
    }
}

if ($KnowledgeIndexCrashRecovery) {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $postgresql = Read-ComposeContainer $ProjectName 'postgresql'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $postgresql.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The knowledge index crash recovery target services are not running.'
    }
    $workerId = [string]$worker.Id
    $workerShortId = $workerId.Substring(0, 12)
    $postgresqlId = [string]$postgresql.Id
    $runId = [Guid]::NewGuid().ToString('N')
    $lockApplicationName = "finaudit-knowledge-crash-$runId"
    if ($lockApplicationName.Length -gt 63) {
        throw 'The knowledge index lock identity is invalid.'
    }
    $passwordMount = $passwordFile.Replace('\', '/')
    $lockProcessStarted = $false
    $workerNeedsRestart = $false
    $gateStartedAt = [DateTimeOffset]::UtcNow
    $lockSessionCountQuery = (
        'SELECT count(*) FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName';"
    )
    $terminateQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName' " +
        'AND pid <> pg_backend_pid()' +
        ') AS result WHERE terminated;'
    )
    $lockCountQuery = (
        'SELECT count(*) FROM pg_stat_activity AS activity ' +
        'JOIN pg_locks AS held ON held.pid = activity.pid ' +
        "WHERE activity.application_name = '$lockApplicationName' " +
        "AND held.relation = 'public.operation_logs'::regclass " +
        "AND held.mode = 'AccessExclusiveLock' AND held.granted;"
    )
    $waitingLockCountQuery = (
        'SELECT count(*) FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.operation_logs'::regclass " +
        'AND NOT waiting.granted;'
    )
    $terminateWaitingQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.operation_logs'::regclass " +
        'AND NOT waiting.granted' +
        ') AS result WHERE terminated;'
    )

    try {
        $seedOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
                '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
                'maintenance', 'python',
                '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
                'seed'
            )
        ) 'The knowledge index crash recovery seed helper failed.'
        Write-Output $seedOutput
        if ($seedOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_SEED_GATE=PASS\r?$') {
            throw 'The knowledge index seed helper did not return PASS.'
        }
        $canonicalUuid = (
            '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-' +
            '[0-9a-f]{4}-[0-9a-f]{12}'
        )
        $canonicalUuidV4 = (
            '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-' +
            '[89ab][0-9a-f]{3}-[0-9a-f]{12}'
        )
        $knowledgeBaseMatch = [regex]::Match(
            $seedOutput,
            "(?m)^LOCAL_KNOWLEDGE_INDEX_KNOWLEDGE_BASE_ID=($canonicalUuid)\r?$"
        )
        if (-not $knowledgeBaseMatch.Success) {
            throw 'The knowledge index seed identity is invalid.'
        }
        $knowledgeBaseId = $knowledgeBaseMatch.Groups[1].Value

        $prepareOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-knowledge-index-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
            'prepare-policy'
        ) 'The knowledge index policy prepare helper failed.'
        Write-Output $prepareOutput
        if ($prepareOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_POLICY_READY_GATE=PASS\r?$') {
            throw 'The knowledge index policy prepare helper did not return PASS.'
        }
        $policyMatch = [regex]::Match(
            $prepareOutput,
            "(?m)^LOCAL_KNOWLEDGE_INDEX_POLICY_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $policyMatch.Success) {
            throw 'The knowledge index policy identity is invalid.'
        }
        $policyId = $policyMatch.Groups[1].Value
        if ($policyId -ceq $knowledgeBaseId) {
            throw 'The knowledge index prerequisite identities are not unique.'
        }

        $stopped = Invoke-Docker @('stop', '--timeout', '30', $workerId) `
            'Unable to stop the owned local Worker before index queueing.'
        $workerNeedsRestart = $true
        if ($stopped -cne $workerId -and $stopped -cne $workerShortId) {
            throw 'Docker did not confirm the exact Worker stopped for index queueing.'
        }
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if ($stoppedWorker.Id -cne $workerId -or $stoppedWorker.State.Status -cne 'exited') {
            throw 'The knowledge index Worker did not stop cleanly before queueing.'
        }

        $queueOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-knowledge-index-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_KNOWLEDGE_BASE_ID=$knowledgeBaseId",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
            'queue-index'
        ) 'The knowledge index queue helper failed.'
        Write-Output $queueOutput
        if ($queueOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_QUEUE_GATE=PASS\r?$') {
            throw 'The knowledge index queue helper did not return PASS.'
        }
        $indexMatch = [regex]::Match(
            $queueOutput,
            "(?m)^LOCAL_KNOWLEDGE_INDEX_ID=($canonicalUuidV4)\r?$"
        )
        $jobMatch = [regex]::Match(
            $queueOutput,
            "(?m)^LOCAL_KNOWLEDGE_INDEX_JOB_ID=($canonicalUuidV4)\r?$"
        )
        $memberCountMatch = [regex]::Match(
            $queueOutput,
            '(?m)^LOCAL_KNOWLEDGE_INDEX_MEMBER_COUNT=([1-9][0-9]*)\r?$'
        )
        $manifestMatch = [regex]::Match(
            $queueOutput,
            '(?m)^LOCAL_KNOWLEDGE_INDEX_MANIFEST_SHA256=([0-9a-f]{64})\r?$'
        )
        if (
            -not $indexMatch.Success -or
            -not $jobMatch.Success -or
            -not $memberCountMatch.Success -or
            -not $manifestMatch.Success
        ) {
            throw 'The queued knowledge index identities are invalid.'
        }
        $indexId = $indexMatch.Groups[1].Value
        $jobId = $jobMatch.Groups[1].Value
        $memberCount = $memberCountMatch.Groups[1].Value
        $manifestSha256 = $manifestMatch.Groups[1].Value
        if (
            @(@($knowledgeBaseId, $policyId, $indexId, $jobId) | Select-Object -Unique).Count -ne 4
        ) {
            throw 'The knowledge index crash recovery identities are not unique.'
        }

        $lockQuery = (
            'BEGIN; LOCK TABLE public.operation_logs IN ACCESS EXCLUSIVE MODE; ' +
            'SELECT pg_sleep(600); COMMIT;'
        )
        $null = Invoke-Docker @(
            'exec', '--detach', '--env', "PGAPPNAME=$lockApplicationName",
            $postgresqlId,
            'psql', '--username', 'finaudit', '--dbname', 'finaudit',
            '--set', 'ON_ERROR_STOP=1', '--command', $lockQuery
        ) 'Unable to start the owned knowledge index database lock.'
        $lockProcessStarted = $true
        $lockHeld = $false
        $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $lockDeadline) {
            $lockCount = Read-PostgresScalar $postgresqlId $lockCountQuery
            if ($lockCount -ceq '1') {
                $lockHeld = $true
                break
            }
            if ($lockCount -cne '0') {
                throw 'The owned knowledge index database lock is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $lockHeld) {
            throw 'The owned knowledge index database lock was not acquired.'
        }

        $started = Invoke-Docker @('start', $workerId) `
            'Unable to start the owned Worker for knowledge index fault injection.'
        if ($started -cne $workerId -and $started -cne $workerShortId) {
            throw 'Docker did not confirm the exact Worker start for knowledge indexing.'
        }
        $workerNeedsRestart = $false
        $workerRunning = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -ceq $workerId -and $currentWorker.State.Status -ceq 'running') {
                $workerRunning = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRunning) {
            throw 'The knowledge index Worker did not start.'
        }

        $indexEnvironment = @(
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_KNOWLEDGE_BASE_ID=$knowledgeBaseId",
            '--env', "FINAUDIT_POLICY_ID=$policyId",
            '--env', "FINAUDIT_INDEX_ID=$indexId",
            '--env', "FINAUDIT_INDEX_JOB_ID=$jobId",
            '--env', "FINAUDIT_INDEX_MEMBER_COUNT=$memberCount",
            '--env', "FINAUDIT_INDEX_MANIFEST_SHA256=$manifestSha256"
        )
        $runningOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $indexEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
                'wait-running'
            )
        ) 'The knowledge index running-state gate failed.'
        Write-Output $runningOutput
        if ($runningOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_RUNNING_GATE=PASS\r?$') {
            throw 'The knowledge index running-state helper did not return PASS.'
        }
        $runningJobMatch = [regex]::Match(
            $runningOutput,
            "(?m)^LOCAL_KNOWLEDGE_INDEX_RUNNING_JOB_ID=($canonicalUuidV4)\r?$"
        )
        if (-not $runningJobMatch.Success -or $runningJobMatch.Groups[1].Value -cne $jobId) {
            throw 'The running knowledge index Job identity drifted.'
        }

        $waiterObserved = $false
        $waiterDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        while ([DateTimeOffset]::UtcNow -lt $waiterDeadline) {
            $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
            if ($waitingCount -ceq '1') {
                $waiterObserved = $true
                break
            }
            if ($waitingCount -cne '0') {
                throw 'The blocked knowledge index database session is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $waiterObserved) {
            throw 'The Worker did not reach the controlled knowledge index body lock.'
        }

        $materializedOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $indexEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
                'verify-materialized'
            )
        ) 'The pre-crash knowledge index materialization verification failed.'
        Write-Output $materializedOutput
        if (
            $materializedOutput -notmatch
            '(?m)^LOCAL_KNOWLEDGE_INDEX_MATERIALIZED_BEFORE_CRASH_GATE=PASS\r?$'
        ) {
            throw 'The pre-crash knowledge index materialization gate did not return PASS.'
        }
        $materializationMatch = [regex]::Match(
            $materializedOutput,
            '(?m)^LOCAL_KNOWLEDGE_INDEX_MATERIALIZATION_SHA256=([0-9a-f]{64})\r?$'
        )
        if (-not $materializationMatch.Success) {
            throw 'The knowledge index materialization identity is invalid.'
        }
        $materializationSha256 = $materializationMatch.Groups[1].Value

        $worker = Read-ComposeContainer $ProjectName 'worker'
        if ($worker.Id -cne $workerId -or $worker.State.Status -cne 'running') {
            throw 'The Worker identity changed before knowledge index crash injection.'
        }
        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $workerId) `
            'Unable to SIGKILL the owned local Worker during knowledge indexing.'
        $workerNeedsRestart = $true
        if ($killed -cne $workerId -and $killed -cne $workerShortId) {
            throw 'Docker did not confirm the exact knowledge index Worker target.'
        }
        $stoppedWorker = Read-ComposeContainer $ProjectName 'worker'
        if (
            $stoppedWorker.Id -cne $workerId -or
            $stoppedWorker.State.Status -cne 'exited' -or
            [int]$stoppedWorker.State.ExitCode -ne 137
        ) {
            throw 'The knowledge index Worker did not reach the expected SIGKILL state.'
        }

        $waitingCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
        if ($waitingCount -ceq '1') {
            $terminatedWaiter = Read-PostgresScalar $postgresqlId $terminateWaitingQuery
            if ($terminatedWaiter -cne '1') {
                throw 'The orphaned knowledge index database session was not terminated once.'
            }
        }
        elseif ($waitingCount -cne '0') {
            throw 'The blocked knowledge index database session changed unexpectedly.'
        }
        if ((Read-PostgresScalar $postgresqlId $waitingLockCountQuery) -cne '0') {
            throw 'The killed knowledge index Worker database transaction did not roll back.'
        }
        $terminatedLock = Read-PostgresScalar $postgresqlId $terminateQuery
        if ($terminatedLock -cne '1') {
            throw 'The owned knowledge index database lock was not released once.'
        }
        if ((Read-PostgresScalar $postgresqlId $lockSessionCountQuery) -cne '0') {
            throw 'The owned knowledge index database session was not released.'
        }
        $lockProcessStarted = $false

        $beforeRecoveryOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $indexEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
                'before-recovery'
            )
        ) 'The pre-recovery knowledge index gate failed.'
        Write-Output $beforeRecoveryOutput
        if (
            $beforeRecoveryOutput -notmatch
            '(?m)^LOCAL_KNOWLEDGE_INDEX_ZERO_READY_FACTS_BEFORE_RECOVERY_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery knowledge index database gate did not return PASS.'
        }
        if (
            $beforeRecoveryOutput -notmatch
            '(?m)^LOCAL_KNOWLEDGE_INDEX_ORPHAN_POINTS_PRESERVED_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery orphan Qdrant point gate did not return PASS.'
        }
        $preservedMatch = [regex]::Match(
            $beforeRecoveryOutput,
            '(?m)^LOCAL_KNOWLEDGE_INDEX_MATERIALIZATION_SHA256=([0-9a-f]{64})\r?$'
        )
        if (
            -not $preservedMatch.Success -or
            $preservedMatch.Groups[1].Value -cne $materializationSha256
        ) {
            throw 'The preserved knowledge index materialization identity drifted.'
        }

        $started = Invoke-Docker @('start', $workerId) `
            'Unable to perform the managed Worker restart after knowledge index crash.'
        if ($started -cne $workerId -and $started -cne $workerShortId) {
            throw 'Docker did not confirm the exact managed knowledge Worker restart target.'
        }
        $workerNeedsRestart = $false
        $workerRecovered = $false
        $workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
        while ([DateTimeOffset]::UtcNow -lt $workerDeadline) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -ceq $workerId -and $currentWorker.State.Status -ceq 'running') {
                $workerRecovered = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $workerRecovered) {
            throw 'The local Worker did not recover after the knowledge index crash.'
        }

        $clientOutput = Invoke-Docker @(
            'run', '--rm', '--network', $network[0], '--read-only',
            '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true',
            '--label', 'com.finaudit.test-purpose=local-knowledge-index-crash-recovery',
            '--label', "com.finaudit.run-id=$runId",
            '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
            '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
            '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
            '--env', "FINAUDIT_CRASH_RUN_ID=$runId",
            '--env', "FINAUDIT_KNOWLEDGE_BASE_ID=$knowledgeBaseId",
            '--env', "FINAUDIT_POLICY_ID=$policyId",
            '--env', "FINAUDIT_INDEX_ID=$indexId",
            '--env', "FINAUDIT_INDEX_JOB_ID=$jobId",
            '--env', "FINAUDIT_INDEX_MEMBER_COUNT=$memberCount",
            '--env', "FINAUDIT_INDEX_MANIFEST_SHA256=$manifestSha256",
            "finaudit-backend-local:$imageRevision",
            'python', '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
            'verify-client'
        ) 'The client-visible knowledge index crash recovery gate failed.'
        Write-Output $clientOutput
        if ($clientOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_CRASH_CLIENT_GATE=PASS\r?$') {
            throw 'The client-visible knowledge index crash recovery gate did not return PASS.'
        }

        $databaseOutput = Invoke-Docker (
            $composeArguments + @('exec', '--no-TTY') + $indexEnvironment + @(
                'maintenance', 'python',
                '/app/scripts/smoke_local_knowledge_index_crash_recovery.py',
                'database'
            )
        ) 'The database knowledge index crash recovery gate failed.'
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch '(?m)^LOCAL_KNOWLEDGE_INDEX_CRASH_DATABASE_GATE=PASS\r?$') {
            throw 'The database knowledge index crash recovery gate did not return PASS.'
        }
        $finalMaterializationMatch = [regex]::Match(
            $databaseOutput,
            '(?m)^LOCAL_KNOWLEDGE_INDEX_FINAL_MATERIALIZATION_SHA256=([0-9a-f]{64})\r?$'
        )
        if (
            -not $finalMaterializationMatch.Success -or
            $finalMaterializationMatch.Groups[1].Value -cne $materializationSha256
        ) {
            throw 'The recovered knowledge index materialization identity drifted.'
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenance.Id
        ) 'Unable to read the Maintenance knowledge index recovery logs.'
        $expectedOutcome = (
            'MAINTENANCE_OUTCOME outcome=claimed_and_succeeded job_id=' +
            [regex]::Escape($jobId)
        )
        if ($maintenanceLogs -notmatch $expectedOutcome) {
            throw 'Maintenance did not record the expected knowledge index recovery outcome.'
        }

        Read-DependencyHealth $httpsPort
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_BODY_LOCK_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_SIGKILL_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_MANAGED_RESTART_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_LEASE_RECOVERY_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_ATTEMPT_TWO_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_UNIQUE_FACTS_GATE=PASS'
        Write-Output 'LOCAL_KNOWLEDGE_INDEX_CRASH_STACK_RESTORED=PASS'
    }
    finally {
        if ($lockProcessStarted) {
            $cleanupSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            if ($cleanupSessionCount -ceq '1') {
                $cleanupTerminated = Read-PostgresScalar $postgresqlId $terminateQuery
                if ($cleanupTerminated -cne '1') {
                    throw 'Unable to release the owned knowledge index database session.'
                }
            }
            elseif ($cleanupSessionCount -cne '0') {
                throw 'Refusing to release an ambiguous knowledge index database session.'
            }
        }
        if ($workerNeedsRestart) {
            $currentWorker = Read-ComposeContainer $ProjectName 'worker'
            if ($currentWorker.Id -cne $workerId) {
                throw 'Refusing to restore a knowledge Worker whose identity changed.'
            }
            if ($currentWorker.State.Status -ceq 'exited') {
                $restoredWorker = Invoke-Docker @('start', $workerId) `
                    'Unable to restore the owned local Worker.'
                if (
                    $restoredWorker -cne $workerId -and
                    $restoredWorker -cne $workerShortId
                ) {
                    throw 'Docker did not confirm restoration of the owned knowledge Worker.'
                }
            }
            elseif ($currentWorker.State.Status -cne 'running') {
                throw 'The owned knowledge Worker is not in a restorable state.'
            }
        }
    }
}

if ($AiAuditCrashRecovery) {
    if (-not $ProjectName.StartsWith('finaudit-ai-audit-', [StringComparison]::Ordinal)) {
        throw 'The AI audit crash gate requires a dedicated finaudit-ai-audit-* project.'
    }
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $backend = Read-ComposeContainer $ProjectName 'backend'
    $postgresql = Read-ComposeContainer $ProjectName 'postgresql'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $backend.State.Status -cne 'running' -or
        $postgresql.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The AI audit crash recovery target services are not running.'
    }
    $maintenanceId = [string]$maintenance.Id
    $maintenanceShortId = $maintenanceId.Substring(0, 12)
    $postgresqlId = [string]$postgresql.Id
    $runId = [Guid]::NewGuid().ToString('N')
    $lockApplicationName = "finaudit-ai-audit-crash-$runId"
    if ($lockApplicationName.Length -gt 63) {
        throw 'The AI audit crash lock identity is invalid.'
    }
    $gateStartedAt = [DateTimeOffset]::UtcNow
    $lockProcessStarted = $false
    $ownedFactsNeedCleanup = $false
    $lockSessionCountQuery = (
        'SELECT count(*) FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName';"
    )
    $terminateLockQuery = (
        'SELECT count(*) FROM (' +
        'SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity ' +
        "WHERE application_name = '$lockApplicationName' " +
        'AND pid <> pg_backend_pid()' +
        ') AS result WHERE terminated;'
    )
    $lockCountQuery = (
        'SELECT count(*) FROM pg_stat_activity AS activity ' +
        'JOIN pg_locks AS held ON held.pid = activity.pid ' +
        "WHERE activity.application_name = '$lockApplicationName' " +
        "AND held.relation = 'public.ai_call_logs'::regclass " +
        "AND held.mode = 'AccessExclusiveLock' AND held.granted;"
    )
    $waitingLockCountQuery = (
        'SELECT count(*) FROM pg_locks AS waiting ' +
        "WHERE waiting.relation = 'public.ai_call_logs'::regclass " +
        'AND NOT waiting.granted;'
    )
    $waitingPidQuery = (
        "SELECT COALESCE(max(waiting.pid)::text, '') FROM pg_locks AS waiting " +
        "WHERE waiting.relation = 'public.ai_call_logs'::regclass " +
        'AND NOT waiting.granted;'
    )
    $helperArguments = $composeArguments + @(
        'exec', '--no-TTY',
        '--env', "FINAUDIT_AI_AUDIT_CRASH_RUN_ID=$runId",
        'backend', 'python',
        '/app/scripts/smoke_local_ai_audit_crash_recovery.py'
    )

    try {
        $stopped = Invoke-Docker @('stop', '--timeout', '30', $maintenanceId) `
            'Unable to stop the owned Maintenance process before AI audit seeding.'
        if ($stopped -cne $maintenanceId -and $stopped -cne $maintenanceShortId) {
            throw 'Docker did not confirm the exact Maintenance process stopped.'
        }
        $stoppedMaintenance = Read-ComposeContainer $ProjectName 'maintenance'
        if (
            $stoppedMaintenance.Id -cne $maintenanceId -or
            $stoppedMaintenance.State.Status -cne 'exited' -or
            $stoppedMaintenance.State.ExitCode -ne 0
        ) {
            throw 'Maintenance did not stop cleanly before the AI audit crash gate.'
        }

        $ownedFactsNeedCleanup = $true
        $seedOutput = Invoke-Docker ($helperArguments + @('seed')) `
            'The AI audit crash seed helper failed.'
        Write-Output $seedOutput
        if ($seedOutput -notmatch '(?m)^LOCAL_AI_AUDIT_SEED_GATE=PASS\r?$') {
            throw 'The AI audit crash seed helper did not return PASS.'
        }
        $canonicalUuid = (
            '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-' +
            '[0-9a-f]{4}-[0-9a-f]{12}'
        )
        $eventMatch = [regex]::Match(
            $seedOutput,
            "(?m)^LOCAL_AI_AUDIT_EVENT_ID=($canonicalUuid)\r?$"
        )
        $operationMatch = [regex]::Match(
            $seedOutput,
            "(?m)^LOCAL_AI_AUDIT_OPERATION_ID=($canonicalUuid)\r?$"
        )
        if (
            -not $eventMatch.Success -or
            -not $operationMatch.Success -or
            $eventMatch.Groups[1].Value -ceq $operationMatch.Groups[1].Value
        ) {
            throw 'The AI audit crash identities are invalid.'
        }
        $eventId = $eventMatch.Groups[1].Value
        $operationId = $operationMatch.Groups[1].Value

        $lockCommand = (
            "SET application_name = '$lockApplicationName'; " +
            'BEGIN; LOCK TABLE public.ai_call_logs IN ACCESS EXCLUSIVE MODE; ' +
            'SELECT pg_sleep(600);'
        )
        $null = Invoke-Docker @(
            'exec', '--detach', $postgresqlId,
            'psql', '--username', 'finaudit', '--dbname', 'finaudit',
            '--set', 'ON_ERROR_STOP=1', '--command', $lockCommand
        ) 'Unable to start the AI audit database lock session.'
        $lockProcessStarted = $true
        $lockDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        do {
            $lockSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            $lockCount = Read-PostgresScalar $postgresqlId $lockCountQuery
            if ($lockSessionCount -ceq '1' -and $lockCount -ceq '1') {
                break
            }
            if ($lockSessionCount -notin @('0', '1') -or $lockCount -notin @('0', '1')) {
                throw 'The AI audit database lock identity is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        } while ([DateTimeOffset]::UtcNow -lt $lockDeadline)
        if ($lockSessionCount -cne '1' -or $lockCount -cne '1') {
            throw 'The AI audit database lock was not granted.'
        }

        $started = Invoke-Docker @('start', $maintenanceId) `
            'Unable to start Maintenance for the AI audit crash injection.'
        if ($started -cne $maintenanceId -and $started -cne $maintenanceShortId) {
            throw 'Docker did not confirm the exact Maintenance process started.'
        }
        $waitingDeadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
        do {
            $waitingLockCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
            if ($waitingLockCount -ceq '1') {
                break
            }
            if ($waitingLockCount -notin @('0', '1')) {
                throw 'The AI audit projector lock waiter is ambiguous.'
            }
            $currentMaintenance = Read-ComposeContainer $ProjectName 'maintenance'
            if (
                $currentMaintenance.Id -cne $maintenanceId -or
                $currentMaintenance.State.Status -cne 'running'
            ) {
                throw 'Maintenance exited before reaching the AI audit projection lock.'
            }
            Start-Sleep -Milliseconds 250
        } while ([DateTimeOffset]::UtcNow -lt $waitingDeadline)
        if ($waitingLockCount -cne '1') {
            throw 'Maintenance did not reach the AI audit projection transaction.'
        }
        $projectorDatabasePid = Read-PostgresScalar $postgresqlId $waitingPidQuery
        if ($projectorDatabasePid -notmatch '^[1-9][0-9]*$') {
            throw 'The AI audit projector database identity is invalid.'
        }
        $projectorSessionCountQuery = (
            'SELECT count(*) FROM pg_stat_activity ' +
            "WHERE pid = $projectorDatabasePid;"
        )

        $killed = Invoke-Docker @('kill', '--signal', 'KILL', $maintenanceId) `
            'Unable to SIGKILL the owned Maintenance process.'
        if ($killed -cne $maintenanceId -and $killed -cne $maintenanceShortId) {
            throw 'Docker did not confirm the exact Maintenance crash target.'
        }
        $crashedMaintenance = Read-ComposeContainer $ProjectName 'maintenance'
        if (
            $crashedMaintenance.Id -cne $maintenanceId -or
            $crashedMaintenance.State.Status -cne 'exited' -or
            $crashedMaintenance.State.ExitCode -ne 137
        ) {
            throw 'Maintenance did not reach the expected SIGKILL state.'
        }

        # PostgreSQL cannot observe a dead client while its statement is waiting on a lock.
        # Releasing only this gate's lock lets the server write to the closed socket, abort
        # the exact projector session, and roll back its still-open transaction.
        $terminated = Read-PostgresScalar $postgresqlId $terminateLockQuery
        if ($terminated -cne '1') {
            throw 'Unable to release the owned AI audit database lock.'
        }
        $lockProcessStarted = $false
        $waiterRollbackDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        do {
            $waitingLockCount = Read-PostgresScalar $postgresqlId $waitingLockCountQuery
            $lockSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            $projectorSessionCount = Read-PostgresScalar (
                $postgresqlId
            ) $projectorSessionCountQuery
            if (
                $waitingLockCount -ceq '0' -and
                $lockSessionCount -ceq '0' -and
                $projectorSessionCount -ceq '0'
            ) {
                break
            }
            if (
                $waitingLockCount -notin @('0', '1') -or
                $lockSessionCount -notin @('0', '1') -or
                $projectorSessionCount -notin @('0', '1')
            ) {
                throw 'The crashed AI audit projector database state is ambiguous.'
            }
            Start-Sleep -Milliseconds 250
        } while ([DateTimeOffset]::UtcNow -lt $waiterRollbackDeadline)
        if (
            $waitingLockCount -cne '0' -or
            $lockSessionCount -cne '0' -or
            $projectorSessionCount -cne '0'
        ) {
            throw 'The crashed AI audit projector transaction did not roll back.'
        }

        $beforeRecoveryOutput = Invoke-Docker ($helperArguments + @('before-recovery')) `
            'The pre-recovery AI audit database gate failed.'
        Write-Output $beforeRecoveryOutput
        if (
            $beforeRecoveryOutput -notmatch
                '(?m)^LOCAL_AI_AUDIT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS\r?$'
        ) {
            throw 'The pre-recovery AI audit database gate did not return PASS.'
        }

        $restarted = Invoke-Docker @('start', $maintenanceId) `
            'Unable to restart Maintenance after the AI audit crash.'
        if ($restarted -cne $maintenanceId -and $restarted -cne $maintenanceShortId) {
            throw 'Docker did not confirm the managed Maintenance restart.'
        }
        $databaseOutput = Invoke-Docker ($helperArguments + @('database')) `
            'The recovered AI audit database gate failed.'
        Write-Output $databaseOutput
        if ($databaseOutput -notmatch '(?m)^LOCAL_AI_AUDIT_CRASH_DATABASE_GATE=PASS\r?$') {
            throw 'The recovered AI audit database gate did not return PASS.'
        }

        $maintenanceLogs = Invoke-Docker @(
            'logs', '--since', $gateStartedAt.ToString('O'), $maintenanceId
        ) 'Unable to read the AI audit Maintenance logs.'
        $projectedCount = [regex]::Matches(
            $maintenanceLogs,
            'AI_AUDIT_PROJECTION outcome=projected'
        ).Count
        if ($projectedCount -ne 2) {
            throw 'Maintenance did not record exactly two recovered AI audit projections.'
        }
        if (
            $maintenanceLogs.Contains($eventId, [StringComparison]::Ordinal) -or
            $maintenanceLogs.Contains($operationId, [StringComparison]::Ordinal)
        ) {
            throw 'The AI audit Maintenance log exposed an event identity.'
        }

        $cleanupOutput = Invoke-Docker ($helperArguments + @('cleanup')) `
            'The AI audit owned-fact cleanup failed.'
        Write-Output $cleanupOutput
        if ($cleanupOutput -notmatch '(?m)^LOCAL_AI_AUDIT_ZERO_RESIDUE_GATE=PASS\r?$') {
            throw 'The AI audit owned-fact cleanup did not return PASS.'
        }
        $ownedFactsNeedCleanup = $false
        Read-DependencyHealth $httpsPort
        Write-Output 'LOCAL_AI_AUDIT_BODY_LOCK_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_MAINTENANCE_SIGKILL_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_TRANSACTION_ROLLBACK_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_MANAGED_RESTART_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_UNIQUE_FACTS_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_LOG_REDACTION_GATE=PASS'
        Write-Output 'LOCAL_AI_AUDIT_CRASH_STACK_RESTORED=PASS'
    }
    finally {
        if ($lockProcessStarted) {
            $cleanupSessionCount = Read-PostgresScalar $postgresqlId $lockSessionCountQuery
            if ($cleanupSessionCount -ceq '1') {
                $cleanupTerminated = Read-PostgresScalar $postgresqlId $terminateLockQuery
                if ($cleanupTerminated -cne '1') {
                    throw 'Unable to release the owned AI audit database session.'
                }
            }
            elseif ($cleanupSessionCount -cne '0') {
                throw 'Refusing to release an ambiguous AI audit database session.'
            }
        }
        if ($ownedFactsNeedCleanup) {
            $currentMaintenance = Read-ComposeContainer $ProjectName 'maintenance'
            if ($currentMaintenance.Id -cne $maintenanceId) {
                throw 'Refusing to stop a Maintenance process whose identity changed.'
            }
            if ($currentMaintenance.State.Status -ceq 'running') {
                $cleanupStopped = Invoke-Docker @(
                    'stop', '--timeout', '30', $maintenanceId
                ) 'Unable to stop Maintenance for AI audit cleanup.'
                if (
                    $cleanupStopped -cne $maintenanceId -and
                    $cleanupStopped -cne $maintenanceShortId
                ) {
                    throw 'Docker did not confirm the Maintenance cleanup stop.'
                }
            }
            elseif ($currentMaintenance.State.Status -cne 'exited') {
                throw 'Maintenance is not in a safe state for AI audit cleanup.'
            }
            $cleanupOutput = Invoke-Docker ($helperArguments + @('cleanup')) `
                'The fallback AI audit owned-fact cleanup failed.'
            if ($cleanupOutput -notmatch '(?m)^LOCAL_AI_AUDIT_ZERO_RESIDUE_GATE=PASS\r?$') {
                throw 'The fallback AI audit owned-fact cleanup did not return PASS.'
            }
        }
        $currentMaintenance = Read-ComposeContainer $ProjectName 'maintenance'
        if ($currentMaintenance.Id -cne $maintenanceId) {
            throw 'Refusing to restore a Maintenance process whose identity changed.'
        }
        if ($currentMaintenance.State.Status -ceq 'exited') {
            $restoredMaintenance = Invoke-Docker @('start', $maintenanceId) `
                'Unable to restore the owned Maintenance process.'
            if (
                $restoredMaintenance -cne $maintenanceId -and
                $restoredMaintenance -cne $maintenanceShortId
            ) {
                throw 'Docker did not confirm restoration of Maintenance.'
            }
        }
        elseif ($currentMaintenance.State.Status -cne 'running') {
            throw 'The owned Maintenance process is not in a restorable state.'
        }
    }
}

if ($PerformanceBaseline) {
    if (-not $ProjectName.StartsWith('finaudit-perf-', [StringComparison]::Ordinal)) {
        throw 'The performance gate requires a dedicated finaudit-perf-* project.'
    }
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }
    $worker = Read-ComposeContainer $ProjectName 'worker'
    $dispatcher = Read-ComposeContainer $ProjectName 'dispatcher'
    $maintenance = Read-ComposeContainer $ProjectName 'maintenance'
    if (
        $worker.State.Status -cne 'running' -or
        $dispatcher.State.Status -cne 'running' -or
        $maintenance.State.Status -cne 'running'
    ) {
        throw 'The performance gate runtime services are not running.'
    }

    $runId = [Guid]::NewGuid().ToString('N')
    $seedOutput = Invoke-Docker (
        $composeArguments + @(
            'exec', '--no-TTY',
            '--env', "FINAUDIT_PERFORMANCE_RUN_ID=$runId",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            'maintenance', 'python',
            '/app/scripts/benchmark_local_performance.py', 'seed'
        )
    ) 'The local performance seed failed.'
    Write-Output $seedOutput
    if ($seedOutput -notmatch '(?m)^LOCAL_PERFORMANCE_SEED_GATE=PASS\r?$') {
        throw 'The local performance seed did not return PASS.'
    }

    $passwordMount = $passwordFile.Replace('\', '/')
    $clientOutput = Invoke-Docker @(
        'run', '--rm', '--network', $network[0], '--read-only',
        '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--label', 'com.finaudit.test-purpose=local-performance-baseline',
        '--label', "com.finaudit.run-id=$runId",
        '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
        '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
        '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
        '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
        '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
        '--env', "FINAUDIT_PERFORMANCE_RUN_ID=$runId",
        "finaudit-backend-local:$imageRevision",
        'python', '/app/scripts/benchmark_local_performance.py', 'client'
    ) 'The local performance client gate failed.'
    Write-Output $clientOutput
    if ($clientOutput -notmatch '(?m)^LOCAL_PERFORMANCE_CLIENT_GATE=PASS\r?$') {
        throw 'The local performance client did not return PASS.'
    }
    foreach ($requiredGate in @(
        'LOCAL_PERFORMANCE_BATCH_MAX_GATE',
        'LOCAL_PERFORMANCE_BATCH_REPLAY_GATE',
        'LOCAL_PERFORMANCE_BATCH_PARTIAL_FAILURE_GATE',
        'LOCAL_PERFORMANCE_BATCH_LIMIT_GATE'
    )) {
        if ($clientOutput -notmatch "(?m)^$requiredGate=PASS\r?$") {
            throw "The local performance client did not return $requiredGate=PASS."
        }
    }

    $databaseOutput = Invoke-Docker (
        $composeArguments + @(
            'exec', '--no-TTY',
            '--env', "FINAUDIT_PERFORMANCE_RUN_ID=$runId",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            'maintenance', 'python',
            '/app/scripts/benchmark_local_performance.py', 'database'
        )
    ) 'The local performance database gate failed.'
    Write-Output $databaseOutput
    if ($databaseOutput -notmatch '(?m)^LOCAL_PERFORMANCE_DATABASE_GATE=PASS\r?$') {
        throw 'The local performance database gate did not return PASS.'
    }
    if ($databaseOutput -notmatch '(?m)^LOCAL_PERFORMANCE_BATCH_DATABASE_GATE=PASS\r?$') {
        throw 'The local performance database gate did not verify batch facts.'
    }

    $dockerVersion = Invoke-Docker @('info', '--format', '{{.ServerVersion}}') `
        'Unable to read the Docker Server version.'
    $dockerCpus = Invoke-Docker @('info', '--format', '{{.NCPU}}') `
        'Unable to read the Docker CPU allocation.'
    $dockerMemory = Invoke-Docker @('info', '--format', '{{.MemTotal}}') `
        'Unable to read the Docker memory allocation.'
    Write-Output 'LOCAL_PERFORMANCE_ENV_SCHEMA=finaudit-local-performance-v2'
    Write-Output "LOCAL_PERFORMANCE_DOCKER_SERVER_VERSION=$dockerVersion"
    Write-Output "LOCAL_PERFORMANCE_DOCKER_CPUS=$dockerCpus"
    Write-Output "LOCAL_PERFORMANCE_DOCKER_MEMORY_BYTES=$dockerMemory"
    Write-Output "LOCAL_PERFORMANCE_IMAGE_REVISION=$imageRevision"
    Write-Output 'LOCAL_PERFORMANCE_WORKER_CONCURRENCY=2'
    Write-Output 'LOCAL_PERFORMANCE_ROUNDS=3'
    Write-Output 'LOCAL_PERFORMANCE_LIST_SAMPLES_PER_ROUND=20'
    Write-Output 'LOCAL_PERFORMANCE_UPLOAD_SAMPLES_PER_ROUND=20'
    Write-Output 'LOCAL_PERFORMANCE_BATCH_FILES_PER_ROUND=20'
    Write-Output 'LOCAL_PERFORMANCE_BATCH_REPLAY_PER_ROUND=1'
    Write-Output 'LOCAL_PERFORMANCE_PARTIAL_BATCH_FILES=2'
    Write-Output 'LOCAL_PERFORMANCE_OVER_LIMIT_BATCH_FILES=21'
    Write-Output 'LOCAL_PERFORMANCE_AUDIT_TASKS_PER_ROUND=3'
    Write-Output 'LOCAL_PERFORMANCE_AI_PROVIDER=DISABLED'
    Write-Output 'LOCAL_PERFORMANCE_OCR=NOT_RUN'
    Write-Output 'LOCAL_PERFORMANCE_PRODUCTION=NOT_RUN'
    Read-DependencyHealth $httpsPort
    Write-Output 'LOCAL_PERFORMANCE_STACK_RESTORED=PASS'
    Write-Output 'LOCAL_PERFORMANCE_BASELINE=PASS'
}

if ($SecurityBaseline) {
    if (-not $ProjectName.StartsWith('finaudit-security-', [StringComparison]::Ordinal)) {
        throw 'The security gate requires a dedicated finaudit-security-* project.'
    }
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
    $composeArguments = @(
        'compose', '--project-name', $ProjectName,
        '--env-file', $composeEnvPath,
        '--file', $composePath
    )
    $network = @(
        (Invoke-Docker @(
            'network', 'ls',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--filter', 'label=com.docker.compose.network=app',
            '--format', '{{.Name}}'
        ) 'Unable to identify the local application network.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($network.Count -ne 1 -or [string]::IsNullOrWhiteSpace($network[0])) {
        throw 'The local application network identity is ambiguous.'
    }
    $passwordFile = Join-Path $runtimeDirectory 'bootstrap_admin_password'
    if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
        throw 'The local bootstrap password file is missing.'
    }

    foreach ($service in @('backend', 'worker', 'dispatcher', 'maintenance', 'frontend')) {
        $container = Read-ComposeContainer $ProjectName $service
        $capDrop = @(
            $container.HostConfig.CapDrop |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        $capAdd = @(
            $container.HostConfig.CapAdd |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        $securityOptions = @(
            $container.HostConfig.SecurityOpt |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        if (
            $container.State.Status -cne 'running' -or
            $container.HostConfig.ReadonlyRootfs -ne $true -or
            $capDrop -notcontains 'ALL' -or
            $securityOptions -notcontains 'no-new-privileges:true' -or
            (
                $service -ceq 'frontend' -and
                (
                    $capAdd.Count -ne 3 -or
                    $capAdd -notcontains 'CAP_CHOWN' -or
                    $capAdd -notcontains 'CAP_SETGID' -or
                    $capAdd -notcontains 'CAP_SETUID'
                )
            ) -or
            ($service -cne 'frontend' -and $capAdd.Count -ne 0)
        ) {
            throw "The $service container does not match the local hardening contract."
        }
    }

    $projectContainerIds = @(
        (Invoke-Docker @(
            'ps', '--all', '--no-trunc',
            '--filter', "label=com.docker.compose.project=$ProjectName",
            '--format', '{{.ID}}'
        ) 'Unable to enumerate the local project containers.') -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $publishedBindings = @()
    foreach ($containerId in $projectContainerIds) {
        $container = @(
            (Invoke-Docker @('inspect', $containerId) 'Unable to inspect a local container.') |
                ConvertFrom-Json
        )[0]
        foreach ($property in @($container.HostConfig.PortBindings.PSObject.Properties)) {
            foreach ($binding in @($property.Value)) {
                if ($null -ne $binding) {
                    $publishedBindings += [PSCustomObject]@{
                        Service = [string]$container.Config.Labels.'com.docker.compose.service'
                        ContainerPort = [string]$property.Name
                        HostIp = [string]$binding.HostIp
                        HostPort = [string]$binding.HostPort
                    }
                }
            }
        }
    }
    if (
        $publishedBindings.Count -ne 1 -or
        $publishedBindings[0].Service -cne 'frontend' -or
        $publishedBindings[0].ContainerPort -cne '8443/tcp' -or
        $publishedBindings[0].HostIp -cne '127.0.0.1' -or
        $publishedBindings[0].HostPort -cne "$httpsPort"
    ) {
        throw 'The local host port exposure does not match the loopback-only contract.'
    }

    $runId = [Guid]::NewGuid().ToString('N')
    $seedOutput = Invoke-Docker (
        $composeArguments + @(
            'exec', '--no-TTY',
            '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            'maintenance', 'python',
            '/app/scripts/smoke_local_security.py', 'seed'
        )
    ) 'The local security seed failed.'
    Write-Output $seedOutput
    if ($seedOutput -notmatch '(?m)^LOCAL_SECURITY_SEED_GATE=PASS\r?$') {
        throw 'The local security seed did not return PASS.'
    }

    $passwordMount = $passwordFile.Replace('\', '/')
    $clientArguments = @(
        'run', '--rm', '--network', $network[0], '--read-only',
        '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--label', 'com.finaudit.test-purpose=local-security-baseline',
        '--label', "com.finaudit.run-id=$runId",
        '--mount', "type=bind,src=$passwordMount,dst=/run/secrets/bootstrap_admin_password,readonly",
        '--env', 'FINAUDIT_SMOKE_BASE_URL=https://frontend:8443',
        '--env', "AUTH_PUBLIC_ORIGIN=https://localhost:$httpsPort",
        '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
        '--env', 'BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password',
        '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
        "finaudit-backend-local:$imageRevision",
        'python', '/app/scripts/smoke_local_security.py'
    )
    $clientOutput = Invoke-Docker (
        $clientArguments + @('client')
    ) 'The local security client gate failed.'
    Write-Output $clientOutput
    if ($clientOutput -notmatch '(?m)^LOCAL_SECURITY_CLIENT_GATE=PASS\r?$') {
        throw 'The local security client did not return PASS.'
    }

    $auditFailureArmed = $false
    try {
        $armOutput = Invoke-Docker (
            $composeArguments + @(
                'exec', '--no-TTY',
                '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
                '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
                'maintenance', 'python',
                '/app/scripts/smoke_local_security.py', 'arm-audit-failure'
            )
        ) 'Unable to arm the local audit failure.'
        if ($armOutput -notmatch '(?m)^LOCAL_SECURITY_AUDIT_FAILURE_ARMED=PASS\r?$') {
            throw 'The local audit failure arm did not return PASS.'
        }
        $auditFailureArmed = $true

        $failureOutput = Invoke-Docker (
            $clientArguments + @('audit-failure-client')
        ) 'The local audit failure client gate failed.'
        Write-Output $failureOutput
        if (
            $failureOutput -notmatch
                '(?m)^LOCAL_SECURITY_AUDIT_FAILURE_CLIENT_GATE=PASS\r?$'
        ) {
            throw 'The local audit failure client did not return PASS.'
        }

        $backend = Read-ComposeContainer $ProjectName 'backend'
        $backendLogs = Invoke-Docker @('logs', $backend.Id) `
            'Unable to read the local Backend logs.'
        $sentinel = "S3curitySentinel!$runId"
        if ($backendLogs.Contains($sentinel, [StringComparison]::Ordinal)) {
            throw 'The synthetic request secret sentinel was found in Backend logs.'
        }
        Write-Output 'LOCAL_SECURITY_LOG_SENTINEL_GATE=PASS'
    }
    finally {
        if ($auditFailureArmed) {
            $disarmOutput = Invoke-Docker (
                $composeArguments + @(
                    'exec', '--no-TTY',
                    '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
                    '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
                    'maintenance', 'python',
                    '/app/scripts/smoke_local_security.py', 'disarm-audit-failure'
                )
            ) 'Unable to disarm the local audit failure.'
            if (
                $disarmOutput -notmatch
                    '(?m)^LOCAL_SECURITY_AUDIT_FAILURE_DISARMED=PASS\r?$'
            ) {
                throw 'The local audit failure disarm did not return PASS.'
            }
        }
    }

    $databaseOutput = Invoke-Docker (
        $composeArguments + @(
            'exec', '--no-TTY',
            '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            'maintenance', 'python',
            '/app/scripts/smoke_local_security.py', 'database'
        )
    ) 'The local security database gate failed.'
    Write-Output $databaseOutput
    if ($databaseOutput -notmatch '(?m)^LOCAL_SECURITY_DATABASE_GATE=PASS\r?$') {
        throw 'The local security database gate did not return PASS.'
    }

    $promptInjectionOutput = Invoke-Docker (
        $clientArguments + @('prompt-injection-client')
    ) 'The local Prompt Injection client gate failed.'
    Write-Output $promptInjectionOutput
    if (
        $promptInjectionOutput -notmatch
            '(?m)^LOCAL_SECURITY_PROMPT_INJECTION_CLIENT_GATE=PASS\r?$'
    ) {
        throw 'The local Prompt Injection client did not return PASS.'
    }

    $promptInjectionDatabaseOutput = Invoke-Docker (
        $composeArguments + @(
            'exec', '--no-TTY',
            '--env', "FINAUDIT_SECURITY_RUN_ID=$runId",
            '--env', "BOOTSTRAP_ADMIN_USERNAME=$($marker.adminUsername)",
            'maintenance', 'python',
            '/app/scripts/smoke_local_security.py', 'prompt-injection-database'
        )
    ) 'The local Prompt Injection database gate failed.'
    Write-Output $promptInjectionDatabaseOutput
    if (
        $promptInjectionDatabaseOutput -notmatch
            '(?m)^LOCAL_SECURITY_PROMPT_INJECTION_DATABASE_GATE=PASS\r?$'
    ) {
        throw 'The local Prompt Injection database gate did not return PASS.'
    }

    $promptInjectionCanary = 'INTERNALCONFIGCANARYDONOTEMIT20260815'
    foreach ($service in @('backend', 'worker', 'dispatcher', 'maintenance', 'frontend')) {
        $container = Read-ComposeContainer $ProjectName $service
        $serviceLogs = Invoke-Docker @('logs', $container.Id) `
            "Unable to read the local $service logs."
        if ($serviceLogs.Contains($promptInjectionCanary, [StringComparison]::Ordinal)) {
            throw "The Prompt Injection canary was found in $service logs."
        }
    }
    Write-Output 'LOCAL_SECURITY_PROMPT_INJECTION_LOG_GATE=PASS'

    Read-DependencyHealth $httpsPort
    Write-Output 'LOCAL_SECURITY_SCHEMA=finaudit-local-security-v1'
    Write-Output 'LOCAL_SECURITY_CONTAINER_HARDENING_GATE=PASS'
    Write-Output 'LOCAL_SECURITY_HOST_EXPOSURE_GATE=PASS'
    Write-Output 'LOCAL_SECURITY_AI_PROVIDER=DISABLED'
    Write-Output 'LOCAL_SECURITY_PROMPT_INJECTION_HTTP_QDRANT=PASS'
    Write-Output 'LOCAL_SECURITY_PROMPT_INJECTION_BROWSER=NOT_RUN'
    Write-Output "LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_ORIGIN=https://localhost:$httpsPort"
    Write-Output "LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_USERNAME=sec-pi-browser-$($runId.Substring(0, 10))"
    Write-Output "LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_RUN_ID=$runId"
    Write-Output 'LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_READY=PASS'
    Write-Output 'LOCAL_SECURITY_FORMAL_DAST=NOT_RUN'
    Write-Output 'LOCAL_SECURITY_PRODUCTION=NOT_RUN'
    Write-Output 'LOCAL_SECURITY_STACK_RESTORED=PASS'
    Write-Output 'LOCAL_SECURITY_BASELINE=PASS'
}
