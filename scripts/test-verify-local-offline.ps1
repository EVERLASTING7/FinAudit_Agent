[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$verifierPath = Join-Path $projectRoot 'scripts/verify-local-offline.ps1'
$expectedVerifierBytes = 9000
$expectedVerifierSha256 = '455ba2ea80534d594dabce6869bc8bf441892ac3f36414783d1c47df90a94f43'
$verifierItem = Get-Item -LiteralPath $verifierPath
$actualVerifierSha256 = (Get-FileHash -LiteralPath $verifierPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (
    $verifierItem.Length -ne $expectedVerifierBytes -or
    $actualVerifierSha256 -cne $expectedVerifierSha256
) {
    throw 'The offline gate changed without refreshing its byte-exact negative-test contract.'
}
$tokens = $null
$parseErrors = $null
$verifierAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $verifierPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw 'The offline gate must be valid PowerShell before its Ruff scope can be verified.'
}

function Get-CommandParameterArgument {
    param(
        [Parameter(Mandatory)]
        [System.Management.Automation.Language.CommandAst]$Command,
        [Parameter(Mandatory)]
        [string]$ParameterName
    )

    for ($index = 0; $index -lt $Command.CommandElements.Count - 1; $index++) {
        $element = $Command.CommandElements[$index]
        if (
            $element -is [System.Management.Automation.Language.CommandParameterAst] -and
            $element.ParameterName -eq $ParameterName
        ) {
            return $Command.CommandElements[$index + 1]
        }
    }
    return $null
}

$offlineStepCommands = @(
    $verifierAst.FindAll(
        {
            param($ast)
            $ast -is [System.Management.Automation.Language.CommandAst] -and
            $ast.GetCommandName() -eq 'Add-OfflineStep'
        },
        $true
    )
)
$expectedBackendCommands = @{
    'backend-pytest' = @('-m', 'pytest')
    'backend-ruff-check' = @('-m', 'ruff', 'check', 'app', 'alembic/versions', 'tests')
    'backend-ruff-format' = @('-m', 'ruff', 'format', '--check', 'app', 'alembic/versions', 'tests')
    'backend-mypy' = @('-m', 'mypy', 'app')
    'backend-pip-check' = @('-m', 'pip', 'check')
}
$backendCommands = @(
    $offlineStepCommands | Where-Object {
        $filePathAst = Get-CommandParameterArgument -Command $_ -ParameterName 'FilePath'
        $null -ne $filePathAst -and $filePathAst.Extent.Text -ceq '$backendPython'
    }
)
if ($backendCommands.Count -ne $expectedBackendCommands.Count) {
    throw "The offline gate must contain exactly five closed backend Python steps; found $($backendCommands.Count)."
}

foreach ($backendCommand in $backendCommands) {
    $nameAst = Get-CommandParameterArgument -Command $backendCommand -ParameterName 'Name'
    $argumentsAst = Get-CommandParameterArgument -Command $backendCommand -ParameterName 'Arguments'
    if ($null -eq $nameAst -or $null -eq $argumentsAst) {
        throw 'Every backend Python step must declare exact Name and Arguments parameters.'
    }
    try {
        $stepName = $nameAst.SafeGetValue()
        $actualArguments = @($argumentsAst.SafeGetValue())
    }
    catch {
        throw 'Backend Python step names and arguments must be static literal values.'
    }
    if (-not $expectedBackendCommands.ContainsKey($stepName)) {
        throw "Unexpected backend Python step name: $stepName"
    }
    $expectedArguments = $expectedBackendCommands[$stepName]
    if ($actualArguments.Count -ne $expectedArguments.Count) {
        throw "The backend Python step '$stepName' has an unexpected argument count."
    }
    for ($index = 0; $index -lt $expectedArguments.Count; $index++) {
        if ($actualArguments[$index] -isnot [string] -or $actualArguments[$index] -cne $expectedArguments[$index]) {
            throw "The backend Python step '$stepName' does not preserve its exact arguments."
        }
    }
    $expectedBackendCommands.Remove($stepName)
}
if ($expectedBackendCommands.Count -ne 0) {
    throw 'The offline gate is missing a required backend Python step.'
}

$pythonModuleCommands = @(
    $verifierAst.FindAll(
        {
            param($ast)
            if ($ast -isnot [System.Management.Automation.Language.CommandAst]) {
                return $false
            }
            return $null -ne $ast.Find(
                {
                    param($child)
                    $child -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
                    $child.Value -ceq '-m'
                },
                $true
            )
        },
        $true
    )
)
if ($pythonModuleCommands.Count -ne $backendCommands.Count) {
    throw 'Every Python -m command must be one of the five closed backend steps.'
}
foreach ($pythonModuleCommand in $pythonModuleCommands) {
    if (-not ($backendCommands.Extent.StartOffset -contains $pythonModuleCommand.Extent.StartOffset)) {
        throw 'A Python -m command exists outside the closed backend steps.'
    }
}

$missingPython = Join-Path (
    [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
) ('finaudit-missing-python-' + [System.Guid]::NewGuid().ToString('N') + '.exe')
if (Test-Path -LiteralPath $missingPython) {
    throw 'The negative-test Python path must not exist.'
}

$expectedFailure = "Backend Python executable does not exist: $missingPython"
$capturedOutput = @()
$capturedError = $null
try {
    $capturedOutput = @(& $verifierPath -BackendPythonPath $missingPython)
}
catch {
    $capturedError = $_
}
if ($null -eq $capturedError) {
    throw 'A missing Backend Python executable unexpectedly passed the offline gate.'
}
if ($capturedOutput.Count -ne 0) {
    throw 'The missing-Python gate emitted output before its expected failure.'
}
if ($capturedError.Exception.Message -cne $expectedFailure) {
    throw 'The offline gate did not fail for the expected missing-Python reason.'
}

$global:LASTEXITCODE = 0
'LOCAL_OFFLINE_NEGATIVE_CASES=PASS'
