[CmdletBinding()]
param(
    [string]$RootPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RootPath)) {
    $RootPath = Join-Path $PSScriptRoot '..'
}

if (-not (Test-Path -LiteralPath $RootPath -PathType Container)) {
    throw 'Git governance root directory does not exist.'
}

$projectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $RootPath).Path)
$requiredPaths = @(
    '.gitmessage',
    '.githooks/commit-msg',
    'scripts/verify-git-governance.ps1'
)
foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $path) -PathType Leaf)) {
        throw "Missing Git governance file: $path"
    }
}

$git = (Get-Command git -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.git'))) {
    & $git -C $projectRoot init --initial-branch=main --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'Git repository initialization failed.'
    }
}

$gitRootText = & $git -C $projectRoot rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to resolve the Git repository root.'
}
$gitRoot = [System.IO.Path]::GetFullPath(([string]$gitRootText).Trim())
if (-not $gitRoot.Equals($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'RootPath must be the Git repository root.'
}

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $git -C $projectRoot rev-parse --verify HEAD 2>$null | Out-Null
    $headExists = $LASTEXITCODE -eq 0
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if (-not $headExists) {
    $branch = & $git -C $projectRoot branch --show-current 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to read the current branch of the empty repository.'
    }
    if ($branch -ne 'main') {
        & $git -C $projectRoot branch -m main
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to set the empty repository branch to main.'
        }
    }
}

& $git -C $projectRoot config --local commit.template .gitmessage
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to configure local commit.template.'
}
& $git -C $projectRoot config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to configure local core.hooksPath.'
}

$commitTemplate = & $git -C $projectRoot config --local --get commit.template
$hooksPath = & $git -C $projectRoot config --local --get core.hooksPath
if ($commitTemplate -ne '.gitmessage' -or $hooksPath -ne '.githooks') {
    throw 'Git local governance configuration verification failed.'
}

'GIT_GOVERNANCE_SETUP=PASS'
