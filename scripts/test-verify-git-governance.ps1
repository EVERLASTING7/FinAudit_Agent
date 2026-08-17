[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path)
$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempBasePrefix = $tempBase.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-git-governance-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Temporary test root is outside the operating-system temp directory.'
}

function Invoke-PowerShellScript {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $LiteralPath @Arguments 2>&1
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

function Invoke-TestGit {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $git -C $tempRoot @Arguments 2>&1)
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

function Assert-Success {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$ExpectedMarker
    )

    $outputLines = @($Result.Output | ForEach-Object { [string]$_ })
    if ($Result.ExitCode -ne 0 -or
        $outputLines.Count -ne 1 -or
        $outputLines[0] -cne $ExpectedMarker) {
        throw "Governance self-test did not return the expected marker: $ExpectedMarker"
    }
}

$forgedMarkerRejected = $false
try {
    Assert-Success -Result ([pscustomobject]@{
            ExitCode = 0
            Output = @('prefix-GIT_BRANCH_NAME_VERIFY=PASS-suffix')
        }) -ExpectedMarker 'GIT_BRANCH_NAME_VERIFY=PASS'
}
catch {
    $forgedMarkerRejected = $true
}
if (-not $forgedMarkerRejected) {
    throw 'Governance self-test accepted a forged success-marker substring.'
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    New-Item -ItemType Directory -Path (Join-Path $tempRoot 'scripts') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $tempRoot '.githooks') | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot '.gitmessage') -Destination $tempRoot
    Copy-Item -LiteralPath (Join-Path $projectRoot '.githooks/commit-msg') `
        -Destination (Join-Path $tempRoot '.githooks/commit-msg')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts/setup-git-governance.ps1') `
        -Destination (Join-Path $tempRoot 'scripts/setup-git-governance.ps1')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts/verify-git-governance.ps1') `
        -Destination (Join-Path $tempRoot 'scripts/verify-git-governance.ps1')

    $setupPath = Join-Path $tempRoot 'scripts/setup-git-governance.ps1'
    $verifyPath = Join-Path $tempRoot 'scripts/verify-git-governance.ps1'
    foreach ($attempt in 1..2) {
        $setupResult = Invoke-PowerShellScript -LiteralPath $setupPath -Arguments @('-RootPath', $tempRoot)
        Assert-Success -Result $setupResult -ExpectedMarker 'GIT_GOVERNANCE_SETUP=PASS'
    }

    $branch = (& $git -C $tempRoot branch --show-current).Trim()
    $commitTemplate = (& $git -C $tempRoot config --local --get commit.template).Trim()
    $hooksPath = (& $git -C $tempRoot config --local --get core.hooksPath).Trim()
    if ($branch -ne 'main' -or $commitTemplate -ne '.gitmessage' -or $hooksPath -ne '.githooks') {
        throw 'Empty repository initialization or idempotent configuration is incorrect.'
    }

    & $git -C $tempRoot config --local user.name 'FinAudit Test'
    & $git -C $tempRoot config --local user.email 'finaudit-test@example.invalid'
    & $git -C $tempRoot config --local commit.gpgsign false
    'synthetic test content' | Set-Content -LiteralPath (Join-Path $tempRoot 'sample.txt') -Encoding UTF8
    & $git -C $tempRoot add -- sample.txt

    $invalidCommit = Invoke-TestGit -Arguments @('commit', '--quiet', '-m', 'invalid message')
    if ($invalidCommit.ExitCode -eq 0) {
        throw 'The commit-msg hook accepted an invalid subject.'
    }

    $validCommit = Invoke-TestGit -Arguments @('commit', '--quiet', '-m', 'test(base): verify git governance')
    if ($validCommit.ExitCode -ne 0) {
        throw 'The commit-msg hook rejected a valid Conventional Commit.'
    }
    $headBefore = (& $git -C $tempRoot rev-parse HEAD).Trim()
    $setupAfterCommit = Invoke-PowerShellScript -LiteralPath $setupPath -Arguments @('-RootPath', $tempRoot)
    Assert-Success -Result $setupAfterCommit -ExpectedMarker 'GIT_GOVERNANCE_SETUP=PASS'
    $headAfter = (& $git -C $tempRoot rev-parse HEAD).Trim()
    if ($headAfter -ne $headBefore) {
        throw 'Repeated initialization changed existing repository history.'
    }

    $messagePath = Join-Path $tempRoot '.git/GOVERNANCE_MESSAGE'
    foreach ($message in @(
            "Merge branch 'synthetic'",
            'Revert "synthetic"',
            'fixup! feat(base): synthetic',
            'squash! fix(base): synthetic',
            'amend! docs(base): synthetic'
        )) {
        $message | Set-Content -LiteralPath $messagePath -Encoding UTF8
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-CommitMessageFile', $messagePath)
        Assert-Success -Result $result -ExpectedMarker 'GIT_COMMIT_MESSAGE_VERIFY=PASS'
    }

    foreach ($message in @('', 'feat missing colon', 'FEAT: uppercase type', '<type>(<scope>): <summary>')) {
        $message | Set-Content -LiteralPath $messagePath -Encoding UTF8
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-CommitMessageFile', $messagePath)
        if ($result.ExitCode -eq 0) {
            throw 'An invalid commit message was accepted.'
        }
    }

    foreach ($tag in @('v0.1.0', 'v1.20.300')) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-VersionTag', $tag)
        Assert-Success -Result $result -ExpectedMarker 'GIT_VERSION_TAG_VERIFY=PASS'
    }
    foreach ($tag in @('1.2.3', 'v01.2.3', 'v1.2', 'v1.2.3-rc.1')) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-VersionTag', $tag)
        if ($result.ExitCode -eq 0) {
            throw 'An invalid version tag was accepted.'
        }
    }

    foreach ($branchName in @(
            'main',
            'develop',
            'feature/base-002-backend-scaffold',
            'release/v1.2.3',
            'hotfix/issue-123'
        )) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-BranchName', $branchName)
        Assert-Success -Result $result -ExpectedMarker 'GIT_BRANCH_NAME_VERIFY=PASS'
    }
    foreach ($branchName in @(
            'master',
            'Feature/base-002',
            'feature/',
            'feature/nested/topic',
            'feature/.hidden',
            'feature/foo.lock',
            'release/v1..2',
            'release/release.lock',
            'hotfix/issue.',
            'hotfix/hotfix.lock'
        )) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-BranchName', $branchName)
        if ($result.ExitCode -eq 0) {
            throw 'An invalid branch name was accepted.'
        }
    }

    foreach ($remoteUrl in @(
            'https://example.invalid/finaudit/repository.git',
            'https://example.invalid:8443/finaudit/repository.git',
            'ssh://git@example.invalid/finaudit/repository.git',
            'ssh://git@example.invalid:2222/finaudit/repository.git',
            'git@example.invalid:finaudit/repository.git'
        )) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-RemoteUrl', $remoteUrl)
        Assert-Success -Result $result -ExpectedMarker 'GIT_REMOTE_URL_VERIFY=PASS'
    }

    $syntheticCredential = 'synthetic-' + ('T' * 24)
    foreach ($remoteUrl in @(
            "https://user:$syntheticCredential@example.invalid/finaudit/repository.git",
            "https://$syntheticCredential@example.invalid/finaudit/repository.git",
            "ssh://git:$syntheticCredential@example.invalid/finaudit/repository.git",
            "user:$syntheticCredential@example.invalid:finaudit/repository.git",
            "https://example.invalid/finaudit/repository.git?token=$syntheticCredential",
            'https://example.invalid/finaudit/repository.git#fragment',
            "https://example.invalid/finaudit/repository`n.git",
            "https://example.invalid/finaudit/repository.git`n",
            "ssh://git@example.invalid/finaudit/repository.git`n",
            "git@example.invalid:finaudit/repository.git`n",
            "https://example.invalid/finaudit/repository$([char]0x0085).git",
            "https://example.invalid/finaudit/repository$([char]0x009F).git",
            "https://example.invalid/finaudit/repository$([char]0x2028).git",
            "https://example.invalid/finaudit/repository$([char]0x202E).git",
            'not-a-url',
            'ext::synthetic-helper',
            'synthetic::owner/repo.git',
            '\\attacker.invalid\share\repo.git',
            '-oProxyCommand=synthetic-helper:repo.git',
            'D:\synthetic\repository.git',
            'http://example.invalid/finaudit/repository.git',
            'git://example.invalid/finaudit/repository.git',
            'ftp://example.invalid/finaudit/repository.git',
            'file:///D:/synthetic/repository.git',
            'ssh:///finaudit/repository.git',
            'ssh://user@example.invalid/finaudit/repository.git',
            'git@-example.invalid:finaudit/repository.git',
            'git@example.invalid:../repository.git',
            'https://example.invalid%2f.attacker.invalid/finaudit/repository.git',
            'https://example.invalid/finaudit/repository%2egit',
            'https://example.invalid/finaudit/%2e%2e/repository.git',
            'https://example.invalid/finaudit/repository%00.git',
            'https://example.invalid/finaudit/repository%0a.git',
            'https://example.invalid/finaudit/repository%0d.git',
            'https://example.invalid/finaudit/repository%5c.git',
            'https://example.invalid/finaudit/repository%2fextra.git',
            'https://example.invalid/finaudit/repository%3ftoken.git',
            'https://example.invalid/finaudit/repository%23fragment.git',
            'ssh://git@[fe80::1%25synthetic]/finaudit/repository.git'
        )) {
        $result = Invoke-PowerShellScript -LiteralPath $verifyPath -Arguments @('-RemoteUrl', $remoteUrl)
        $resultText = $result.Output -join [System.Environment]::NewLine
        if ($result.ExitCode -eq 0) {
            throw 'An unsafe Git remote URL was accepted.'
        }
        if ($resultText -match [regex]::Escape($syntheticCredential)) {
            throw 'Git remote URL verification exposed synthetic credential material.'
        }
    }

    if (@(& $git -C $tempRoot remote).Count -ne 0 -or @(& $git -C $tempRoot tag --list).Count -ne 0) {
        throw 'Governance self-test must not create a remote or version tag.'
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $tempRoot).Path)
        if (-not $resolvedTempRoot.StartsWith($tempBasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove a path outside the operating-system temp directory.'
        }
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}

'GIT_GOVERNANCE_TESTS=PASS'
