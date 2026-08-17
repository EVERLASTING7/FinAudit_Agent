[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,39}$')]
    [string]$ProjectName = 'finaudit-local',

    [switch]$Purge
)

$ErrorActionPreference = 'Stop'
$markerName = '.finaudit-local-runtime.json'

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
    if ($exitCode -ne 0) {
        throw $FailureMessage
    }
    return (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
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

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composePath = Join-Path $projectRoot 'infra\compose\compose.local.yml'
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw 'The local application data directory is unavailable.'
}
$runtimeBase = [IO.Path]::GetFullPath((Join-Path $localAppData 'FinAuditAgent\runtime'))
$runtimeDirectory = [IO.Path]::GetFullPath((Join-Path $runtimeBase $ProjectName))
if (-not (Test-IsExactChild $runtimeBase $runtimeDirectory)) {
    throw 'The managed runtime directory escaped its approved local application data root.'
}
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
if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is unavailable.'
}

$composeArguments = @(
    'compose',
    '--project-name',
    $ProjectName,
    '--env-file',
    $composeEnvPath,
    '--file',
    $composePath,
    'down',
    '--remove-orphans'
)
if ($Purge) {
    $composeArguments += '--volumes'
}
$null = Invoke-Docker $composeArguments 'The local Compose stack failed to stop.'

if ($Purge) {
    $resolvedRuntime = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $runtimeDirectory).Path
    )
    $resolvedParent = [IO.Path]::GetFullPath((Split-Path -Parent $resolvedRuntime))
    $attributes = (Get-Item -LiteralPath $resolvedRuntime -Force).Attributes
    if (
        $resolvedRuntime -cne $runtimeDirectory -or
        $resolvedParent -cne $runtimeBase -or
        -not (Test-IsExactChild $runtimeBase $resolvedRuntime) -or
        ([IO.Path]::GetFileName($resolvedRuntime)) -cne $ProjectName -or
        ($attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        throw 'The runtime directory failed the purge safety check.'
    }
    $markerBeforePurge = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if (
        $markerBeforePurge.schemaVersion -cne 'finaudit-local-runtime-v1' -or
        $markerBeforePurge.projectName -cne $ProjectName
    ) {
        throw 'The runtime ownership marker changed before purge.'
    }
    Remove-Item -LiteralPath $resolvedRuntime -Recurse -Force
    Write-Output 'LOCAL_STACK_STOP=PASS'
    Write-Output 'LOCAL_STACK_VOLUMES=REMOVED'
    Write-Output 'LOCAL_STACK_RUNTIME_SECRETS=REMOVED'
    Write-Output 'LOCAL_STACK_PURGE_RECOVERABLE=NO'
    exit 0
}

Write-Output 'LOCAL_STACK_STOP=PASS'
Write-Output 'LOCAL_STACK_VOLUMES=PRESERVED'
Write-Output 'LOCAL_STACK_RUNTIME_SECRETS=PRESERVED'
