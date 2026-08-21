function Assert-NarratorProviderContract {
    $provider = Get-WinEvent -ListProvider 'Microsoft-Windows-Narrator'
    if ("$($provider.Id)" -cne '835b79e2-e76a-44c4-9885-26ad122d3b4d') {
        throw 'The Windows Narrator ETW provider identity changed.'
    }
    $expected = @{
        5 = 'InitiateSpeaking'
        43 = 'ProcessFocusChange'
        68 = 'SapiTextSpeak'
        170 = 'UiaFocusEventReceived'
        231 = 'AudioPlayBackCompleted'
        254 = 'GenerateAudioStream'
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $event = @($provider.Events | Where-Object Id -eq $entry.Key | Select-Object -First 1)
        if ($event.Count -ne 1 -or $event[0].Task.Name -cne $entry.Value) {
            throw "The Windows Narrator ETW event contract changed for event $($entry.Key)."
        }
    }
}

function Assert-NarratorTraceRoot([string]$TraceRoot) {
    $resolvedRoot = [IO.Path]::GetFullPath($TraceRoot)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (
        -not $resolvedRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFileName($resolvedRoot)).StartsWith(
            'narrator-accessibility-',
            [StringComparison]::Ordinal
        )
    ) {
        throw 'Narrator trace root is outside the dedicated system temp scope.'
    }
    return $resolvedRoot
}

function Stop-OwnedNarratorProcesses([int[]]$ProcessIds) {
    foreach ($processId in $ProcessIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 300
}

function Start-FinAuditNarratorEtw([string]$TraceRoot) {
    Assert-NarratorProviderContract
    $resolvedRoot = Assert-NarratorTraceRoot $TraceRoot
    if (Test-Path -LiteralPath $resolvedRoot) {
        throw 'Narrator trace root already exists.'
    }
    New-Item -ItemType Directory -Path $resolvedRoot | Out-Null
    $sessionName = "FinAuditNarrator-$([Guid]::NewGuid().ToString('N'))"
    $etlPath = Join-Path $resolvedRoot 'narrator.etl'
    $csvPath = Join-Path $resolvedRoot 'narrator.csv'
    $markerPath = Join-Path $resolvedRoot 'narrator-focus.json'
    $beforeIds = @(Get-Process Narrator -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    if ($beforeIds.Count -ne 0) {
        throw 'Narrator is already running; the isolated accessibility gate will not take ownership.'
    }
    $traceStarted = $false
    $launcher = $null
    $ownedProcesses = @()
    try {
        logman start $sessionName `
            -p '{835b79e2-e76a-44c4-9885-26ad122d3b4d}' `
            0xffffffffffffffff 5 -o $etlPath -ets | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Narrator ETW trace start failed.'
        }
        $traceStarted = $true
        $launcher = Start-Process -FilePath 'C:\Windows\System32\Narrator.exe' -PassThru
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Milliseconds 150
            $ownedProcesses = @(
                Get-Process Narrator -ErrorAction SilentlyContinue |
                    Where-Object Id -notin $beforeIds
            )
            if (
                $ownedProcesses.Count -eq 1 -and
                $ownedProcesses[0].MainWindowHandle -ne 0
            ) {
                break
            }
        }
        if ($ownedProcesses.Count -ne 1 -or $ownedProcesses[0].MainWindowHandle -eq 0) {
            throw 'Narrator did not expose one isolated runtime process.'
        }
        return [pscustomobject]@{
            Kind = 'FinAuditNarratorEtwV1'
            TraceRoot = $resolvedRoot
            SessionName = $sessionName
            EtlPath = $etlPath
            CsvPath = $csvPath
            MarkerPath = $markerPath
            NarratorProcessIds = @($ownedProcesses.Id)
            LauncherProcessId = $launcher.Id
            TraceStarted = $true
        }
    }
    catch {
        Stop-OwnedNarratorProcesses @($ownedProcesses.Id)
        if ($null -ne $launcher) {
            Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
        }
        if ($traceStarted) {
            logman stop $sessionName -ets 2>$null | Out-Null
        }
        if (Test-Path -LiteralPath $resolvedRoot) {
            Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
        }
        throw
    }
}

function Convert-EtwProcessId([string]$Value) {
    if ($Value -notmatch '^0x[0-9A-Fa-f]{8}$') {
        throw 'Narrator ETW PID is not canonical hexadecimal.'
    }
    return [Convert]::ToInt32($Value.Substring(2), 16)
}

function Convert-EtwClock([string]$Value) {
    $ticks = 0L
    if (-not [long]::TryParse($Value, [ref]$ticks) -or $ticks -le 0) {
        throw 'Narrator ETW clock value is invalid.'
    }
    return [DateTime]::FromFileTimeUtc($ticks)
}

function Convert-JsonUtcTimestamp([object]$Value) {
    if ($Value -is [DateTime]) {
        return $Value.ToUniversalTime()
    }
    if ($Value -isnot [string]) {
        throw 'Narrator focus marker timestamp type is invalid.'
    }
    return [DateTimeOffset]::Parse($Value).UtcDateTime
}

function Stop-FinAuditNarratorEtw(
    [pscustomobject]$State,
    [switch]$Validate
) {
    if ($State.Kind -cne 'FinAuditNarratorEtwV1') {
        throw 'Narrator ETW lifecycle state is invalid.'
    }
    $resolvedRoot = Assert-NarratorTraceRoot $State.TraceRoot
    $summary = $null
    try {
        Stop-OwnedNarratorProcesses @($State.NarratorProcessIds)
        Stop-Process -Id $State.LauncherProcessId -Force -ErrorAction SilentlyContinue
        if ($State.TraceStarted) {
            logman stop $State.SessionName -ets | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw 'Narrator ETW trace stop failed.'
            }
            $State.TraceStarted = $false
        }
        if (-not $Validate) {
            return $null
        }
        if (-not (Test-Path -LiteralPath $State.MarkerPath -PathType Leaf)) {
            throw 'Narrator focus marker is missing.'
        }
        $marker = Get-Content -LiteralPath $State.MarkerPath -Raw | ConvertFrom-Json
        if (
            $marker.schema_version -cne 'finaudit-narrator-focus-v1' -or
            $marker.report_route -notmatch '^/audit-reports/[0-9a-f-]{36}$' -or
            @($marker.focus_sequence).Count -lt 7
        ) {
            throw 'Narrator focus marker contract is invalid.'
        }
        tracerpt $State.EtlPath -of CSV -o $State.CsvPath -y | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Narrator ETW conversion failed.'
        }
        $windowStart = (Convert-JsonUtcTimestamp $marker.focus_started_utc).AddSeconds(-1)
        $windowEnd = (Convert-JsonUtcTimestamp $marker.focus_completed_utc).AddSeconds(2)
        if ($windowEnd -le $windowStart -or ($windowEnd - $windowStart).TotalSeconds -gt 30) {
            throw 'Narrator focus marker time window is invalid.'
        }
        $ownedIds = @($State.NarratorProcessIds | ForEach-Object { [int]$_ })
        $ownedRows = @(
            Import-Csv -LiteralPath $State.CsvPath |
                Where-Object {
                    $_.'Event Name'.Trim() -ceq 'Microsoft-Windows-Narrator' -and
                    (Convert-EtwProcessId $_.PID) -in $ownedIds
                }
        )
        $rows = @(
            $ownedRows |
                Where-Object {
                    (Convert-EtwClock $_.'Clock-Time') -ge $windowStart -and
                    (Convert-EtwClock $_.'Clock-Time') -le $windowEnd
                }
        )
        $counts = @{}
        $allCounts = @{}
        foreach ($eventId in @(5, 43, 68, 170, 231, 254)) {
            $counts["$eventId"] = @($rows | Where-Object { $_.'Event ID' -eq "$eventId" }).Count
            $allCounts["$eventId"] = @(
                $ownedRows | Where-Object { $_.'Event ID' -eq "$eventId" }
            ).Count
        }
        if (
            $counts['170'] -lt 4 -or
            $counts['43'] -lt 4 -or
            $counts['5'] -lt 3 -or
            $counts['68'] -lt 2 -or
            $counts['254'] -lt 3 -or
            $counts['231'] -lt 1
        ) {
            $ownedClocks = @($ownedRows | ForEach-Object { Convert-EtwClock $_.'Clock-Time' })
            $diagnostic = [ordered]@{
                window_counts = $counts
                all_counts = $allCounts
                marker_start = $windowStart.ToString('o')
                marker_end = $windowEnd.ToString('o')
                event_start = if ($ownedClocks.Count) {
                    ($ownedClocks | Measure-Object -Minimum).Minimum.ToString('o')
                }
                else {
                    $null
                }
                event_end = if ($ownedClocks.Count) {
                    ($ownedClocks | Measure-Object -Maximum).Maximum.ToString('o')
                }
                else {
                    $null
                }
            } | ConvertTo-Json -Compress
            throw "Narrator did not emit the required focus, speech, and audio event chain: $diagnostic"
        }
        $summary = [pscustomobject]@{
            SchemaVersion = 'finaudit-narrator-etw-v1'
            NarratorProcessIds = $ownedIds
            NarratorFileVersion = (Get-Item -LiteralPath 'C:\Windows\System32\Narrator.exe').VersionInfo.FileVersion
            FocusWindowStartUtc = $windowStart.ToString('o')
            FocusWindowEndUtc = $windowEnd.ToString('o')
            FocusSequence = @($marker.focus_sequence)
            ReportRoute = $marker.report_route
            EventCounts = $counts
            EtlSha256 = (Get-FileHash -LiteralPath $State.EtlPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        return $summary
    }
    finally {
        if ($State.TraceStarted) {
            logman stop $State.SessionName -ets 2>$null | Out-Null
            $State.TraceStarted = $false
        }
        Stop-OwnedNarratorProcesses @($State.NarratorProcessIds)
        Stop-Process -Id $State.LauncherProcessId -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $resolvedRoot) {
            Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
        }
    }
}
