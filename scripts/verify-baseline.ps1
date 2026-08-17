[CmdletBinding()]
param(
    [string]$RootPath,
    [switch]$SecretScanOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RootPath)) {
    $RootPath = Join-Path $PSScriptRoot '..'
}

$projectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $RootPath).Path)
$failures = [System.Collections.Generic.List[string]]::new()
$git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source

function Add-Failure {
    param([Parameter(Mandatory)][string]$Message)
    $failures.Add($Message)
}

function Get-LocalRemoteUrlRecords {
    param([Parameter(Mandatory)][string]$WorkingDirectory)

    $processStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processStartInfo.FileName = $git
    $processStartInfo.WorkingDirectory = $WorkingDirectory
    $processStartInfo.Arguments = 'config --local --null --get-regexp "^remote\..*\.(url|pushurl)$"'
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.CreateNoWindow = $true
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false, $true)

    $process = [System.Diagnostics.Process]::Start($processStartInfo)
    try {
        $rawOutput = $process.StandardOutput.ReadToEnd()
        $null = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $exitCode = $process.ExitCode
    }
    finally {
        $process.Dispose()
    }

    if ($exitCode -eq 1 -and $rawOutput.Length -eq 0) {
        return @()
    }
    if ($exitCode -ne 0) {
        throw 'Unable to read local Git remote URL records.'
    }

    $records = [System.Collections.Generic.List[object]]::new()
    foreach ($record in @(
            $rawOutput.Split(
                [char[]]@([char]0),
                [System.StringSplitOptions]::RemoveEmptyEntries
            )
        )) {
        $separatorIndex = $record.IndexOf("`n", [System.StringComparison]::Ordinal)
        if ($separatorIndex -le 0) {
            throw 'Local Git remote URL record is malformed.'
        }

        $key = $record.Substring(0, $separatorIndex)
        $value = $record.Substring($separatorIndex + 1)
        if ($key -cnotmatch '^remote\.(?<remote>[A-Za-z0-9][A-Za-z0-9._-]*)\.(?<kind>url|pushurl)$' -or
            $value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
            throw 'Local Git remote URL record is malformed.'
        }

        $records.Add([pscustomobject]@{
                Remote = $Matches.remote
                Kind = $Matches.kind
                Value = $value
            })
    }
    return @($records)
}

function Get-SingleEffectiveRemoteUrl {
    param(
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$RemoteName,
        [switch]$Push
    )

    $processStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processStartInfo.FileName = $git
    $processStartInfo.WorkingDirectory = $WorkingDirectory
    $mode = if ($Push) { '--push --all' } else { '--all' }
    $processStartInfo.Arguments = "remote get-url $mode $RemoteName"
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.CreateNoWindow = $true
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false, $true)

    $process = [System.Diagnostics.Process]::Start($processStartInfo)
    try {
        $rawOutput = $process.StandardOutput.ReadToEnd()
        $null = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $exitCode = $process.ExitCode
    }
    finally {
        $process.Dispose()
    }
    if ($exitCode -ne 0) {
        throw 'Unable to resolve effective Git remote URL.'
    }

    $value = if ($rawOutput.EndsWith("`r`n", [System.StringComparison]::Ordinal)) {
        $rawOutput.Substring(0, $rawOutput.Length - 2)
    }
    elseif ($rawOutput.EndsWith("`n", [System.StringComparison]::Ordinal)) {
        $rawOutput.Substring(0, $rawOutput.Length - 1)
    }
    else {
        $rawOutput
    }
    if ([string]::IsNullOrWhiteSpace($value) -or
        $value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw 'Effective Git remote URL is missing or ambiguous.'
    }
    return $value
}

$gitEnvironmentOverridePattern = '^(GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_INDEX_FILE|' +
    'GIT_OBJECT_DIRECTORY|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_NAMESPACE|GIT_PREFIX|' +
    'GIT_CONFIG|GIT_CONFIG_COUNT|GIT_CONFIG_SYSTEM|GIT_CONFIG_GLOBAL|GIT_CONFIG_NOSYSTEM|' +
    'GIT_CONFIG_PARAMETERS|GIT_CONFIG_KEY_[0-9]+|GIT_CONFIG_VALUE_[0-9]+)$'
$gitEnvironmentOverrides = @(
    [System.Environment]::GetEnvironmentVariables([System.EnvironmentVariableTarget]::Process).Keys |
        Where-Object { [string]$_ -imatch $gitEnvironmentOverridePattern }
)
if ($gitEnvironmentOverrides.Count -gt 0) {
    Write-Error 'Git environment overrides are not permitted during baseline verification.'
    exit 1
}

if (-not $SecretScanOnly) {
    $topLevelOutput = @(& $git -C $projectRoot rev-parse --show-toplevel 2>$null)
    $topLevelExitCode = $LASTEXITCODE
    $gitDirectoryOutput = @(& $git -C $projectRoot rev-parse --absolute-git-dir 2>$null)
    $gitDirectoryExitCode = $LASTEXITCODE
    try {
        $actualTopLevel = if ($topLevelOutput.Count -eq 1) {
            [System.IO.Path]::GetFullPath([string]$topLevelOutput[0])
        }
        else {
            $null
        }
        $actualGitDirectory = if ($gitDirectoryOutput.Count -eq 1) {
            [System.IO.Path]::GetFullPath([string]$gitDirectoryOutput[0])
        }
        else {
            $null
        }
    }
    catch {
        $actualTopLevel = $null
        $actualGitDirectory = $null
    }

    $expectedGitDirectory = [System.IO.Path]::GetFullPath((Join-Path $projectRoot '.git'))
    if ($topLevelExitCode -ne 0 -or $gitDirectoryExitCode -ne 0 -or
        -not [string]::Equals($actualTopLevel, $projectRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals(
            $actualGitDirectory,
            $expectedGitDirectory,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
        Write-Error 'Git repository metadata is not bound to the requested project root.'
        exit 1
    }
}

function Test-HighConfidenceSecret {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Pattern
    )

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $encodingCandidates = @(
        [pscustomobject]@{
            Encoding = [System.Text.UTF8Encoding]::new($false, $false)
            Offsets = @(0)
        }
    )
    if ($bytes -contains [byte]0) {
        $encodingCandidates += @(
            [pscustomobject]@{
                Encoding = [System.Text.UnicodeEncoding]::new($false, $false, $false)
                Offsets = @(0, 1)
            },
            [pscustomobject]@{
                Encoding = [System.Text.UnicodeEncoding]::new($true, $false, $false)
                Offsets = @(0, 1)
            },
            [pscustomobject]@{
                Encoding = [System.Text.UTF32Encoding]::new($false, $false, $false)
                Offsets = @(0, 1, 2, 3)
            },
            [pscustomobject]@{
                Encoding = [System.Text.UTF32Encoding]::new($true, $false, $false)
                Offsets = @(0, 1, 2, 3)
            }
        )
    }

    foreach ($candidate in $encodingCandidates) {
        foreach ($offset in $candidate.Offsets) {
            if ($offset -ge $bytes.Length) {
                continue
            }
            $text = $candidate.Encoding.GetString($bytes, $offset, $bytes.Length - $offset)
            if ([regex]::IsMatch($text, $Pattern)) {
                return $true
            }
        }
    }
    return $false
}

Push-Location $projectRoot
try {
    if (-not $SecretScanOnly) {
        if (-not (Test-Path -LiteralPath '.git' -PathType Container)) {
            Add-Failure 'Git repository is not initialized.'
        }

        $branch = & $git -C $projectRoot branch --show-current 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
            Add-Failure 'Unable to determine the current Git branch.'
        }
        else {
            try {
                $branchVerification = @(
                    & (Join-Path $projectRoot 'scripts/verify-git-governance.ps1') `
                        -BranchName ([string]$branch) 2>&1
                )
                if ($branchVerification.Count -ne 1 -or
                    [string]$branchVerification[0] -cne 'GIT_BRANCH_NAME_VERIFY=PASS') {
                    Add-Failure 'Current Git branch does not match the documented branch model.'
                }
            }
            catch {
                Add-Failure 'Current Git branch does not match the documented branch model.'
            }
        }

        $commitTemplate = & $git -C $projectRoot config --local --get commit.template 2>$null
        if ($LASTEXITCODE -ne 0 -or $commitTemplate -ne '.gitmessage') {
            Add-Failure "Expected local commit.template '.gitmessage'."
        }

        $hooksPath = & $git -C $projectRoot config --local --get core.hooksPath 2>$null
        if ($LASTEXITCODE -ne 0 -or $hooksPath -ne '.githooks') {
            Add-Failure "Expected local core.hooksPath '.githooks'."
        }

        $requiredPaths = @(
            'backend',
            'frontend',
            'infra',
            'docs',
            'scripts',
            'Request',
            'Demo',
            'README.md',
            'CHANGELOG.md',
            'AGENTS.md',
            'MEMORY.md',
            '.gitignore',
            '.gitmessage',
            '.githooks/commit-msg',
            'docs/baseline-manifest.md',
            'docs/request-manifest.md',
            'docs/development-workflow.md',
            '.github/pull_request_template.md',
            'scripts/setup-git-governance.ps1',
            'scripts/verify-git-governance.ps1',
            'scripts/test-verify-git-governance.ps1'
        )

        foreach ($path in $requiredPaths) {
            if (-not (Test-Path -LiteralPath $path)) {
                Add-Failure "Missing required path: $path"
            }
        }

        $remotes = @(& $git -C $projectRoot remote 2>$null)
        if ($LASTEXITCODE -ne 0) {
            Add-Failure 'Unable to enumerate Git remotes.'
        }
        try {
            $remoteUrlRecords = @(Get-LocalRemoteUrlRecords -WorkingDirectory $projectRoot)
        }
        catch {
            $remoteUrlRecords = @()
            Add-Failure 'Git remote configuration contains a malformed URL record.'
        }
        foreach ($remote in $remotes) {
            if ($remote -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
                Add-Failure 'Git remote configuration contains an invalid remote name.'
                continue
            }

            $remoteRecords = @($remoteUrlRecords | Where-Object { $_.Remote -ceq $remote })
            $remoteUrls = @($remoteRecords | ForEach-Object { $_.Value } | Select-Object -Unique)
            if (@($remoteRecords | Where-Object { $_.Kind -ceq 'url' }).Count -eq 0 -or
                $remoteUrls.Count -eq 0) {
                Add-Failure 'Git remote configuration has no readable URL.'
                continue
            }

            foreach ($remoteUrl in $remoteUrls) {
                try {
                    $urlVerification = @(
                        & (Join-Path $projectRoot 'scripts/verify-git-governance.ps1') `
                            -RemoteUrl ([string]$remoteUrl) 2>&1
                    )
                    if ($urlVerification.Count -ne 1 -or
                        [string]$urlVerification[0] -cne 'GIT_REMOTE_URL_VERIFY=PASS') {
                        Add-Failure 'Git remote configuration contains an unsafe URL.'
                    }
                }
                catch {
                    Add-Failure 'Git remote configuration contains an unsafe URL.'
                }
            }

            try {
                $effectiveUrls = @(
                    Get-SingleEffectiveRemoteUrl -WorkingDirectory $projectRoot -RemoteName $remote
                    Get-SingleEffectiveRemoteUrl -WorkingDirectory $projectRoot -RemoteName $remote -Push
                ) | Select-Object -Unique
                foreach ($effectiveUrl in @($effectiveUrls)) {
                    $urlVerification = @(
                        & (Join-Path $projectRoot 'scripts/verify-git-governance.ps1') `
                            -RemoteUrl ([string]$effectiveUrl) 2>&1
                    )
                    if ($urlVerification.Count -ne 1 -or
                        [string]$urlVerification[0] -cne 'GIT_REMOTE_URL_VERIFY=PASS') {
                        Add-Failure 'Git remote configuration resolves to an unsafe URL.'
                    }
                }
            }
            catch {
                Add-Failure 'Git remote configuration resolves to an unsafe URL.'
            }
        }

        $manifestPath = 'docs/request-manifest.md'
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            $expected = @{}
            foreach ($line in Get-Content -LiteralPath $manifestPath -Encoding UTF8) {
                if ($line -match '^\| `(?<name>[^`]+)` \| (?<bytes>\d+) \| `(?<hash>[A-F0-9]{64})` \|$') {
                    $expected[$Matches.name] = @{
                        Bytes = [int64]$Matches.bytes
                        Hash = $Matches.hash
                    }
                }
            }

            $requestFiles = @(Get-ChildItem -LiteralPath 'Request' -File -Filter '*.md')
            if ($expected.Count -ne $requestFiles.Count) {
                Add-Failure "Manifest contains $($expected.Count) documents; Request contains $($requestFiles.Count)."
            }

            foreach ($file in $requestFiles) {
                if (-not $expected.ContainsKey($file.Name)) {
                    Add-Failure "Request document missing from manifest: $($file.Name)"
                    continue
                }

                $entry = $expected[$file.Name]
                if ($file.Length -ne $entry.Bytes) {
                    Add-Failure "Size mismatch: $($file.Name)"
                }

                $actualHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
                if ($actualHash -ne $entry.Hash) {
                    Add-Failure "SHA-256 mismatch: $($file.Name)"
                }
            }
        }
    }

    $scanExtensions = @('.conf', '.csv', '.html', '.ini', '.js', '.json', '.key', '.md', '.pem', '.ps1', '.py', '.sh', '.toml', '.ts', '.txt', '.vue', '.yaml', '.yml')
    $privateKeyPattern = '-----BEGIN ' + '(RSA |EC |OPENSSH )?PRIVATE KEY-----'
    $openAiLikePattern = ('s' + 'k-') + '[A-Za-z0-9_-]{20,}'
    $awsLikePattern = ('A' + 'KIA') + '[0-9A-Z]{16}'
    $secretPattern = "$privateKeyPattern|$openAiLikePattern|$awsLikePattern"

    Get-ChildItem -LiteralPath $projectRoot -Recurse -File -Force | ForEach-Object {
        $relativePath = $_.FullName.Substring($projectRoot.Length).TrimStart('\', '/')
        if ($relativePath -match '^(\.git|frontend[\\/]node_modules|backend[\\/]\.venv)([\\/]|$)') {
            return
        }

        $isEnvExample = $_.Name -ceq '.env.example'
        if ($_.Name -match '^\.env($|\.)' -and -not $isEnvExample) {
            & $git -C $projectRoot check-ignore --quiet -- $relativePath
            if ($LASTEXITCODE -ne 0) {
                Add-Failure "Secret-like configuration file is not ignored: $relativePath"
            }
            return
        }

        if (-not $isEnvExample -and $scanExtensions -notcontains $_.Extension.ToLowerInvariant()) {
            return
        }

        $hasHighConfidenceSecret = Test-HighConfidenceSecret `
            -Path $_.FullName -Pattern $secretPattern
        if ($hasHighConfidenceSecret) {
            Add-Failure "Potential high-confidence secret in: $relativePath"
        }
    }

    if ($failures.Count -gt 0) {
        $failures | ForEach-Object { Write-Error $_ }
        exit 1
    }

    if ($SecretScanOnly) {
        'SECRET_SCAN_VERIFY=PASS'
    }
    else {
        'BASELINE_LOCAL_VERIFY=PASS'
        'BASELINE_TASK_STATUS=PARTIAL (remote branch protection evidence required)'
        if ($remotes.Count -eq 0) {
            'REMOTE_BRANCH_PROTECTION=NOT_RUN (no remote configured)'
        }
        else {
            'REMOTE_BRANCH_PROTECTION=NOT_VERIFIED (hosting evidence required)'
        }
    }
}
finally {
    Pop-Location
}
