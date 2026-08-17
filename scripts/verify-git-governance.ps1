[CmdletBinding(DefaultParameterSetName = 'CommitMessage')]
param(
    [Parameter(Mandatory, ParameterSetName = 'CommitMessage')]
    [string]$CommitMessageFile,

    [Parameter(Mandatory, ParameterSetName = 'VersionTag')]
    [string]$VersionTag,

    [Parameter(Mandatory, ParameterSetName = 'BranchName')]
    [string]$BranchName,

    [Parameter(Mandatory, ParameterSetName = 'RemoteUrl')]
    [string]$RemoteUrl
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSCmdlet.ParameterSetName -eq 'BranchName') {
    $isLongLivedBranch = $BranchName -ceq 'main' -or $BranchName -ceq 'develop'
    $isTopicBranch = $BranchName -cmatch `
        '^(feature|release|hotfix)/[A-Za-z0-9](?:[A-Za-z0-9_-]|\.(?=[A-Za-z0-9_-]))*$'
    $git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    & $git check-ref-format --branch $BranchName 2>$null | Out-Null
    $isNativeGitBranch = $LASTEXITCODE -eq 0
    if ((-not $isLongLivedBranch -and -not $isTopicBranch) -or -not $isNativeGitBranch) {
        throw 'Branch name does not match the documented Git branch model.'
    }

    'GIT_BRANCH_NAME_VERIFY=PASS'
    return
}

if ($PSCmdlet.ParameterSetName -eq 'RemoteUrl') {
    $isSafe = -not [string]::IsNullOrWhiteSpace($RemoteUrl) -and
        $RemoteUrl -cmatch '^[\x21-\x7E]+\z' -and
        -not $RemoteUrl.Contains('\') -and
        -not $RemoteUrl.Contains('?') -and
        -not $RemoteUrl.Contains('#') -and
        -not $RemoteUrl.Contains('%')

    if ($isSafe -and ($RemoteUrl -cmatch '^https://' -or $RemoteUrl -cmatch '^ssh://')) {
        try {
            $uri = [System.Uri]::new($RemoteUrl, [System.UriKind]::Absolute)
        }
        catch {
            $isSafe = $false
        }

        if ($isSafe) {
            $scheme = $uri.Scheme.ToLowerInvariant()
            $userInfo = $uri.UserInfo
            $hostKind = [System.Uri]::CheckHostName($uri.Host)
            if ($uri.Host.StartsWith('-', [System.StringComparison]::Ordinal) -or
                $hostKind -eq [System.UriHostNameType]::Unknown -or
                $uri.AbsolutePath.Length -le 1 -or
                $uri.Authority.Contains('%')) {
                $isSafe = $false
            }
            elseif ($scheme -eq 'https' -and $userInfo) {
                $isSafe = $false
            }
            elseif ($scheme -eq 'ssh' -and $userInfo -cne 'git') {
                $isSafe = $false
            }
        }
    }
    elseif ($isSafe -and $RemoteUrl -cmatch `
            '^git@(?<host>(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])):(?<path>[A-Za-z0-9_~][A-Za-z0-9._~/-]*)$') {
        $scpHost = $Matches.host.Trim('[', ']')
        $hostKind = [System.Uri]::CheckHostName($scpHost)
        if ($hostKind -eq [System.UriHostNameType]::Unknown -or
            $Matches.path -match '(^|/)\.\.(/|$)') {
            $isSafe = $false
        }
    }
    else {
        $isSafe = $false
    }

    if (-not $isSafe) {
        throw 'Git remote URL is unsafe or contains embedded credential material.'
    }

    'GIT_REMOTE_URL_VERIFY=PASS'
    return
}

if ($PSCmdlet.ParameterSetName -eq 'VersionTag') {
    if ($VersionTag -cnotmatch '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw 'Version tags must use vMAJOR.MINOR.PATCH.'
    }

    'GIT_VERSION_TAG_VERIFY=PASS'
    return
}

if (-not (Test-Path -LiteralPath $CommitMessageFile -PathType Leaf)) {
    throw 'Commit message file does not exist.'
}

$subject = Get-Content -LiteralPath $CommitMessageFile -Encoding UTF8 |
    Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith('#') } |
    Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($subject)) {
    throw 'Commit message has no subject line.'
}

$subject = $subject.Trim()
$isConventional = $subject -cmatch '^[a-z][a-z0-9-]*(\([^)]+\))?!?: \S(?:.*\S)?$'
$isGitGenerated = $subject -cmatch '^(Merge|Revert) .+$' -or
    $subject -cmatch '^(fixup|squash|amend)! .+$'

if (-not $isConventional -and -not $isGitGenerated) {
    throw 'Commit message must use the minimal Conventional Commit format or a Git-generated merge, revert, fixup, squash, or amend subject.'
}

'GIT_COMMIT_MESSAGE_VERIFY=PASS'
