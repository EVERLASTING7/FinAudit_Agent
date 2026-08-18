[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path)
$verifierPath = Join-Path $projectRoot 'scripts/verify-baseline.ps1'
$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempBasePrefix = $tempBase.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-baseline-secret-scan-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Temporary test root is outside the operating-system temp directory.'
}

function Invoke-SecretScan {
    param([Parameter(Mandatory)][string]$CaseRoot)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $verifierPath `
                -RootPath $CaseRoot -SecretScanOnly 2>&1
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Invoke-BaselineAtRoot {
    param(
        [Parameter(Mandatory)][string]$CaseRoot,
        [hashtable]$EnvironmentOverrides = @{}
    )

    $previousEnvironment = @{}
    try {
        foreach ($key in $EnvironmentOverrides.Keys) {
            $previousEnvironment[$key] = [System.Environment]::GetEnvironmentVariable(
                [string]$key,
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                [string]$key,
                [string]$EnvironmentOverrides[$key],
                [System.EnvironmentVariableTarget]::Process
            )
        }
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = @(
                & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $verifierPath `
                    -RootPath $CaseRoot 2>&1
            )
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        foreach ($key in $EnvironmentOverrides.Keys) {
            $previousValue = $previousEnvironment[$key]
            if ($null -eq $previousValue) {
                Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
            }
            else {
                [System.Environment]::SetEnvironmentVariable(
                    [string]$key,
                    [string]$previousValue,
                    [System.EnvironmentVariableTarget]::Process
                )
            }
        }
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Assert-PartialBaselineSuccess {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$ExpectedRemoteMarker
    )

    $expectedLines = @(
        'BASELINE_LOCAL_VERIFY=PASS',
        'BASELINE_TASK_STATUS=PARTIAL (remote branch protection evidence required)',
        $ExpectedRemoteMarker
    )
    $actualLines = @($Result.Output | ForEach-Object { [string]$_ })
    if ($Result.ExitCode -ne 0 -or $actualLines.Count -ne $expectedLines.Count) {
        $caller = (Get-PSCallStack | Select-Object -Skip 1 -First 1).Location
        throw "Baseline verification did not return the exact partial-evidence marker set (caller=$caller, exit=$($Result.ExitCode), lines=$($actualLines.Count))."
    }
    foreach ($expectedLine in $expectedLines) {
        if (@($actualLines | Where-Object { $_ -ceq $expectedLine }).Count -ne 1) {
            throw 'Baseline verification did not return the exact partial-evidence marker set.'
        }
    }
}

function Assert-BaselineFailureWithoutPassMarker {
    param([Parameter(Mandatory)]$Result)

    $actualLines = @($Result.Output | ForEach-Object { [string]$_ })
    if ($Result.ExitCode -eq 0 -or
        $actualLines -contains 'BASELINE_LOCAL_VERIFY=PASS' -or
        $actualLines -contains 'BASELINE_VERIFY=PASS' -or
        $actualLines -contains 'BASELINE_TASK_STATUS=IMPLEMENTED' -or
        $actualLines -contains 'REMOTE_BRANCH_PROTECTION=PASS') {
        throw 'A failing baseline case returned a success or completion marker.'
    }
}

function Test-WrappedOutputContains {
    param(
        [Parameter(Mandatory)][string]$Output,
        [Parameter(Mandatory)][string]$ExpectedText
    )

    $compactOutput = $Output -replace '\s+', ''
    $compactExpected = $ExpectedText -replace '\s+', ''
    return $compactOutput.Contains($compactExpected)
}

function Test-SecretScanFailurePath {
    param(
        [Parameter(Mandatory)][string]$Output,
        [Parameter(Mandatory)][string]$RelativePath
    )

    return Test-WrappedOutputContains -Output $Output `
        -ExpectedText "Potential high-confidence secret in: $RelativePath"
}

$forgedCompletionRejected = $false
try {
    Assert-PartialBaselineSuccess -Result ([pscustomobject]@{
            ExitCode = 0
            Output = @(
                'BASELINE_LOCAL_VERIFY=PASS',
                'BASELINE_TASK_STATUS=PARTIAL (remote branch protection evidence required)',
                'REMOTE_BRANCH_PROTECTION=NOT_RUN (no remote configured)',
                'BASELINE_TASK_STATUS=IMPLEMENTED'
            )
        }) -ExpectedRemoteMarker 'REMOTE_BRANCH_PROTECTION=NOT_RUN (no remote configured)'
}
catch {
    $forgedCompletionRejected = $true
}
if (-not $forgedCompletionRejected) {
    throw 'Baseline self-test accepted an appended completion marker.'
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $positiveRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot 'positive')
    'SECRET_KEY=CHANGE_ME' | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $positiveRoot.FullName '.env.example')
    $positiveResult = Invoke-SecretScan -CaseRoot $positiveRoot.FullName
    $positiveLines = @($positiveResult.Output | ForEach-Object { [string]$_ })
    if ($positiveResult.ExitCode -ne 0 -or
        $positiveLines.Count -ne 1 -or
        $positiveLines[0] -cne 'SECRET_SCAN_VERIFY=PASS') {
        throw 'Placeholder-only .env.example unexpectedly failed the isolated secret scan.'
    }

    $negativeRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot 'negative')
    $syntheticSentinel = ('s' + 'k-') + ('A' * 24)
    "API_KEY=$syntheticSentinel" | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $negativeRoot.FullName '.env.example')
    $negativeResult = Invoke-SecretScan -CaseRoot $negativeRoot.FullName
    $negativeOutput = $negativeResult.Output -join [System.Environment]::NewLine
    if ($negativeResult.ExitCode -eq 0) {
        throw 'Synthetic high-confidence secret in .env.example unexpectedly passed.'
    }
    if (-not (Test-SecretScanFailurePath -Output $negativeOutput -RelativePath '.env.example')) {
        $redactedNegativeOutput = $negativeOutput.Replace($syntheticSentinel, '[REDACTED]')
        throw "Synthetic secret test failed through an unexpected branch: $redactedNegativeOutput"
    }
    if (Test-WrappedOutputContains -Output $negativeOutput -ExpectedText $syntheticSentinel) {
        throw 'Secret scan output exposed the synthetic sentinel.'
    }

    $scannedDirectoryCases = @(
        [pscustomobject]@{ Directory = 'Request'; File = 'leak.md' },
        [pscustomobject]@{ Directory = 'Demo'; File = 'leak.html' },
        [pscustomobject]@{ Directory = 'docs'; File = 'leak.csv' },
        [pscustomobject]@{ Directory = 'scripts'; File = 'leak.txt' }
    )
    foreach ($case in $scannedDirectoryCases) {
        $caseRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot ("negative-$($case.Directory.ToLowerInvariant())"))
        $caseDirectory = New-Item -ItemType Directory -Path (Join-Path $caseRoot.FullName $case.Directory)
        $caseFile = Join-Path $caseDirectory.FullName $case.File
        "API_KEY=$syntheticSentinel" | Set-Content -Encoding UTF8 -LiteralPath $caseFile

        $caseResult = Invoke-SecretScan -CaseRoot $caseRoot.FullName
        $caseOutput = $caseResult.Output -join [System.Environment]::NewLine
        $expectedPath = Join-Path $case.Directory $case.File
        if ($caseResult.ExitCode -eq 0) {
            throw "Synthetic high-confidence secret in $expectedPath unexpectedly passed."
        }
        if (-not (Test-SecretScanFailurePath -Output $caseOutput -RelativePath $expectedPath)) {
            throw "Synthetic secret in $expectedPath failed through an unexpected branch."
        }
        if (Test-WrappedOutputContains -Output $caseOutput -ExpectedText $syntheticSentinel) {
            throw "Secret scan output exposed the synthetic sentinel from $expectedPath."
        }
    }

    $encodedSecretCases = @(
        [pscustomobject]@{
            Name = 'utf16le-txt'
            RelativePath = (Join-Path 'scripts' 'leak-utf16le.txt')
            Encoding = [System.Text.UnicodeEncoding]::new($false, $false, $true)
        },
        [pscustomobject]@{
            Name = 'utf16be-csv'
            RelativePath = (Join-Path 'docs' 'leak-utf16be.csv')
            Encoding = [System.Text.UnicodeEncoding]::new($true, $false, $true)
        },
        [pscustomobject]@{
            Name = 'utf32le-txt'
            RelativePath = (Join-Path 'scripts' 'leak-utf32le.txt')
            Encoding = [System.Text.UTF32Encoding]::new($false, $false, $true)
        },
        [pscustomobject]@{
            Name = 'utf32be-csv'
            RelativePath = (Join-Path 'docs' 'leak-utf32be.csv')
            Encoding = [System.Text.UTF32Encoding]::new($true, $false, $true)
        }
    )
    foreach ($case in $encodedSecretCases) {
        $caseRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot ("negative-$($case.Name)"))
        $caseFile = Join-Path $caseRoot.FullName $case.RelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $caseFile) | Out-Null
        $encodedBytes = $case.Encoding.GetBytes("API_KEY=$syntheticSentinel")
        [System.IO.File]::WriteAllBytes($caseFile, $encodedBytes)

        $caseResult = Invoke-SecretScan -CaseRoot $caseRoot.FullName
        $caseOutput = $caseResult.Output -join [System.Environment]::NewLine
        if ($caseResult.ExitCode -eq 0) {
            throw "Synthetic high-confidence secret in $($case.Name) unexpectedly passed."
        }
        if (-not (
                Test-SecretScanFailurePath -Output $caseOutput -RelativePath $case.RelativePath
            )) {
            $redactedCaseOutput = $caseOutput -replace [regex]::Escape($syntheticSentinel), '[REDACTED]'
            throw "Synthetic secret in $($case.Name) failed through an unexpected branch: $redactedCaseOutput"
        }
        if (Test-WrappedOutputContains -Output $caseOutput -ExpectedText $syntheticSentinel) {
            throw "Secret scan output exposed the synthetic sentinel from $($case.Name)."
        }
    }

    $mixedEncodingCases = @(
        [pscustomobject]@{
            Name = 'invalid-utf8-prefix'
            RelativePath = (Join-Path 'scripts' 'bad.txt')
            Prefix = [byte[]]@(0xFF)
            Suffix = [byte[]]@()
        },
        [pscustomobject]@{
            Name = 'mixed-null-prefix'
            RelativePath = (Join-Path 'docs' 'mix.csv')
            Prefix = [byte[]]@(0xFF, 0x00)
            Suffix = [byte[]]@(0x41)
        }
    )
    foreach ($case in $mixedEncodingCases) {
        $caseRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot ("negative-$($case.Name)"))
        $caseFile = Join-Path $caseRoot.FullName $case.RelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $caseFile) | Out-Null
        $markerBytes = [System.Text.Encoding]::ASCII.GetBytes("API_KEY=$syntheticSentinel")
        $mixedBytes = [byte[]]$case.Prefix + $markerBytes + [byte[]]$case.Suffix
        [System.IO.File]::WriteAllBytes($caseFile, $mixedBytes)

        $caseResult = Invoke-SecretScan -CaseRoot $caseRoot.FullName
        $caseOutput = $caseResult.Output -join [System.Environment]::NewLine
        if ($caseResult.ExitCode -eq 0) {
            throw "Synthetic high-confidence secret in $($case.Name) unexpectedly passed."
        }
        if (-not (
                Test-SecretScanFailurePath -Output $caseOutput -RelativePath $case.RelativePath
            )) {
            $redactedCaseOutput = $caseOutput -replace [regex]::Escape($syntheticSentinel), '[REDACTED]'
            throw "Synthetic secret in $($case.Name) failed through an unexpected branch: $redactedCaseOutput"
        }
        if (Test-WrappedOutputContains -Output $caseOutput -ExpectedText $syntheticSentinel) {
            throw "Secret scan output exposed the synthetic sentinel from $($case.Name)."
        }
    }

    $syntheticPrivateKeyHeader = '-----BEGIN ' + 'PRIVATE KEY-----'
    foreach ($extension in @('.pem', '.key')) {
        $caseRoot = New-Item -ItemType Directory -Path (Join-Path $tempRoot ("negative-private-key-$($extension.TrimStart('.'))"))
        $fileName = "synthetic-private-key$extension"
        $caseFile = Join-Path $caseRoot.FullName $fileName
        $syntheticPrivateKeyHeader | Set-Content -Encoding UTF8 -LiteralPath $caseFile

        $caseResult = Invoke-SecretScan -CaseRoot $caseRoot.FullName
        $caseOutput = $caseResult.Output -join [System.Environment]::NewLine
        if ($caseResult.ExitCode -eq 0) {
            throw "Synthetic private-key header in $fileName unexpectedly passed."
        }
        if (-not (Test-SecretScanFailurePath -Output $caseOutput -RelativePath $fileName)) {
            throw "Synthetic private-key header in $fileName failed through an unexpected branch."
        }
        if (
            Test-WrappedOutputContains -Output $caseOutput `
                -ExpectedText $syntheticPrivateKeyHeader
        ) {
            throw "Secret scan output exposed the synthetic private-key header from $fileName."
        }
    }

    $gitIntegrationRoot = Join-Path $tempRoot 'git-integration'
    foreach ($directory in @(
            'backend',
            'frontend',
            'infra',
            'docs',
            'scripts',
            'Request',
            'Demo',
            '.githooks',
            '.github'
        )) {
        New-Item -ItemType Directory -Path (Join-Path $gitIntegrationRoot $directory) -Force | Out-Null
    }
    foreach ($relativePath in @(
            'README.md',
            'CHANGELOG.md',
            'AGENTS.md',
            'MEMORY.md',
            '.gitignore',
            '.gitmessage',
            '.githooks/commit-msg',
            '.github/pull_request_template.md',
            'docs/baseline-manifest.md',
            'docs/request-manifest.md',
            'docs/development-workflow.md',
            'scripts/setup-git-governance.ps1',
            'scripts/verify-git-governance.ps1',
            'scripts/test-verify-git-governance.ps1'
        )) {
        $destinationPath = Join-Path $gitIntegrationRoot $relativePath
        Copy-Item -LiteralPath (Join-Path $projectRoot $relativePath) -Destination $destinationPath
    }
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Request') -File -Filter '*.md' |
        Copy-Item -Destination (Join-Path $gitIntegrationRoot 'Request')

    & $git init --initial-branch=main --quiet $gitIntegrationRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to create isolated Git integration repository.'
    }
    $gitDirectory = Join-Path $gitIntegrationRoot '.git'
    & $git -C $gitIntegrationRoot config --local commit.template .gitmessage
    & $git -C $gitIntegrationRoot config --local core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to configure isolated Git integration repository.'
    }

    foreach ($branchName in @(
            'main',
            'develop',
            'feature/base-001-governance',
            'release/v1.2.3',
            'hotfix/issue-123'
        )) {
        & $git -C $gitIntegrationRoot symbolic-ref HEAD "refs/heads/$branchName"
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to set an isolated allowed branch.'
        }
        $branchResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
        Assert-PartialBaselineSuccess -Result $branchResult `
            -ExpectedRemoteMarker 'REMOTE_BRANCH_PROTECTION=NOT_RUN (no remote configured)'
    }

    & $git -C $gitIntegrationRoot symbolic-ref HEAD refs/heads/master
    $invalidBranchResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
    $invalidBranchOutput = $invalidBranchResult.Output -join [System.Environment]::NewLine
    Assert-BaselineFailureWithoutPassMarker -Result $invalidBranchResult
    if (-not (
            Test-WrappedOutputContains -Output $invalidBranchOutput `
                -ExpectedText 'Current Git branch does not match the documented branch model'
        )) {
        throw 'Baseline verification accepted a branch outside the documented model.'
    }

    & $git -C $gitIntegrationRoot symbolic-ref HEAD refs/heads/main
    & $git -C $gitIntegrationRoot config --local remote.origin.url `
        'https://example.invalid/finaudit/repository.git'
    $safeRemoteResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
    Assert-PartialBaselineSuccess -Result $safeRemoteResult `
        -ExpectedRemoteMarker 'REMOTE_BRANCH_PROTECTION=NOT_VERIFIED (hosting evidence required)'

    & $git -C $gitIntegrationRoot config --local `
        'url.ext::synthetic-helper.insteadOf' 'https://example.invalid/'
    $insteadOfResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
    Assert-BaselineFailureWithoutPassMarker -Result $insteadOfResult
    $insteadOfOutput = $insteadOfResult.Output -join [System.Environment]::NewLine
    if (-not (
            Test-WrappedOutputContains -Output $insteadOfOutput `
                -ExpectedText 'Git remote configuration resolves to an unsafe URL'
        )) {
        throw 'Baseline verification accepted an unsafe insteadOf remote rewrite.'
    }
    & $git -C $gitIntegrationRoot config --local --unset-all `
        'url.ext::synthetic-helper.insteadOf'

    & $git -C $gitIntegrationRoot config --local `
        'url.ext::synthetic-helper.pushInsteadOf' 'https://example.invalid/'
    $pushInsteadOfResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
    Assert-BaselineFailureWithoutPassMarker -Result $pushInsteadOfResult
    $pushInsteadOfOutput = $pushInsteadOfResult.Output -join [System.Environment]::NewLine
    if (-not (
            Test-WrappedOutputContains -Output $pushInsteadOfOutput `
                -ExpectedText 'Git remote configuration resolves to an unsafe URL'
        )) {
        throw 'Baseline verification accepted an unsafe pushInsteadOf remote rewrite.'
    }
    & $git -C $gitIntegrationRoot config --local --unset-all `
        'url.ext::synthetic-helper.pushInsteadOf'

    foreach ($lineBreak in @("`r", "`n")) {
        & $git -C $gitIntegrationRoot config --local remote.origin.url `
            "https://example.invalid/a.git${lineBreak}https://example.invalid/b.git"
        $multilineRemoteResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
        Assert-BaselineFailureWithoutPassMarker -Result $multilineRemoteResult
        $multilineRemoteOutput = $multilineRemoteResult.Output -join [System.Environment]::NewLine
        if (-not (
                Test-WrappedOutputContains -Output $multilineRemoteOutput `
                    -ExpectedText 'Git remote configuration contains a malformed URL record'
            )) {
            throw 'Baseline verification accepted a multiline Git remote URL record.'
        }
    }

    $syntheticRemoteCredential = 'synthetic-' + ('R' * 24)
    & $git -C $gitIntegrationRoot config --local remote.origin.url `
        "https://user:$syntheticRemoteCredential@example.invalid/finaudit/repository.git"
    $configPath = Join-Path $gitDirectory 'config'
    $headPath = Join-Path $gitDirectory 'HEAD'
    $configHashBefore = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    $headHashBefore = (Get-FileHash -LiteralPath $headPath -Algorithm SHA256).Hash
    $unsafeRemoteResult = Invoke-BaselineAtRoot -CaseRoot $gitIntegrationRoot
    $unsafeRemoteOutput = $unsafeRemoteResult.Output -join [System.Environment]::NewLine
    Assert-BaselineFailureWithoutPassMarker -Result $unsafeRemoteResult
    if (-not (
            Test-WrappedOutputContains -Output $unsafeRemoteOutput `
                -ExpectedText 'Git remote configuration contains an unsafe URL'
        )) {
        throw 'Baseline verification accepted a credential-bearing synthetic remote URL.'
    }
    if (
        Test-WrappedOutputContains -Output $unsafeRemoteOutput `
            -ExpectedText $syntheticRemoteCredential
    ) {
        throw 'Baseline verification exposed synthetic Git remote credential material.'
    }
    $configHashAfter = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    $headHashAfter = (Get-FileHash -LiteralPath $headPath -Algorithm SHA256).Hash
    if ($configHashAfter -ne $configHashBefore -or $headHashAfter -ne $headHashBefore) {
        throw 'Baseline verification modified isolated Git configuration or refs.'
    }

    $redirectedRootResult = Invoke-BaselineAtRoot -CaseRoot $projectRoot -EnvironmentOverrides @{
        GIT_DIR = $gitDirectory
        GIT_WORK_TREE = $projectRoot
    }
    Assert-BaselineFailureWithoutPassMarker -Result $redirectedRootResult
    $redirectedRootOutput = $redirectedRootResult.Output -join [System.Environment]::NewLine
    if (-not (
            Test-WrappedOutputContains -Output $redirectedRootOutput `
                -ExpectedText 'Git environment overrides are not permitted'
        )) {
        throw 'Baseline verification did not reject Git repository environment overrides.'
    }

}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $tempRoot).Path)
        if (-not $resolvedTempRoot.StartsWith($tempBasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove a temp path outside the operating-system temp directory.'
        }
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}

$gitOverridePattern = '^(GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_INDEX_FILE|' +
    'GIT_OBJECT_DIRECTORY|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_NAMESPACE|GIT_PREFIX|' +
    'GIT_CONFIG|GIT_CONFIG_COUNT|GIT_CONFIG_SYSTEM|GIT_CONFIG_GLOBAL|GIT_CONFIG_NOSYSTEM|' +
    'GIT_CONFIG_PARAMETERS|GIT_CONFIG_KEY_[0-9]+|GIT_CONFIG_VALUE_[0-9]+)$'
$leakedGitOverrides = @(
    [System.Environment]::GetEnvironmentVariables([System.EnvironmentVariableTarget]::Process).Keys |
        Where-Object { [string]$_ -imatch $gitOverridePattern }
)
if ($leakedGitOverrides.Count -gt 0) {
    throw "Baseline self-test leaked Git environment override names: $($leakedGitOverrides -join ', ')."
}

$projectRemoteNames = @(& $git -C $projectRoot remote)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inspect current project remotes for the final baseline assertion.'
}
$expectedProjectRemoteMarker = if ($projectRemoteNames.Count -eq 0) {
    'REMOTE_BRANCH_PROTECTION=NOT_RUN (no remote configured)'
}
else {
    'REMOTE_BRANCH_PROTECTION=NOT_VERIFIED (hosting evidence required)'
}

$global:LASTEXITCODE = 0
$baselineOutput = @(
    & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $verifierPath -RootPath $projectRoot 2>&1
)
$baselineExitCode = $LASTEXITCODE
$baselineResult = [pscustomobject]@{
    ExitCode = $baselineExitCode
    Output = $baselineOutput
}
Assert-PartialBaselineSuccess -Result $baselineResult `
    -ExpectedRemoteMarker $expectedProjectRemoteMarker

$global:LASTEXITCODE = 0
'BASELINE_SECRET_NEGATIVE_CASES=PASS'
'BASELINE_GIT_CONFIG_NEGATIVE_CASES=PASS'
