[CmdletBinding()]
param(
    [switch]$AcquireFromOfficialRegistries,
    [string]$BackendPythonPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$dependencyRoot = Join-Path $projectRoot 'build/cr011-gate-b-dependencies'
$wheelhouse = Join-Path $dependencyRoot 'python-wheelhouse'
$pythonSite = Join-Path $dependencyRoot 'python-site'
$npmCache = Join-Path $dependencyRoot 'npm-cache'
$emptyNpmrc = Join-Path $dependencyRoot 'empty.npmrc'
$requirements = Join-Path $PSScriptRoot 'requirements-cr011-gate-b.txt'
$nodeToolRoot = Join-Path $PSScriptRoot 'cr011-gate-b-node'

if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}
$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
$virtualEnvironmentRoot = (& $backendPython -I -c 'import sys;print(sys.prefix)' 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($virtualEnvironmentRoot)) {
    throw 'CR-011 dependency materialization cannot resolve the Python environment root.'
}
$virtualEnvironmentRoot = [System.IO.Path]::GetFullPath($virtualEnvironmentRoot)
$pipConfigurationFiles = @(
    (Join-Path $env:ProgramData 'pip/pip.ini'),
    (Join-Path $virtualEnvironmentRoot 'pip.ini')
)

foreach ($requiredFile in @(
        $backendPython,
        $requirements,
        (Join-Path $nodeToolRoot 'package.json'),
        (Join-Path $nodeToolRoot 'package-lock.json')
    )) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required CR-011 Gate B dependency input is missing: $requiredFile"
    }
}
foreach ($pipConfigurationFile in $pipConfigurationFiles) {
    if (Test-Path -LiteralPath $pipConfigurationFile -PathType Leaf) {
        throw 'CR-011 dependency materialization forbids global or site pip configuration.'
    }
}

foreach ($poisonedName in @('NODE_OPTIONS', 'NODE_PATH')) {
    if (-not [string]::IsNullOrEmpty(
            [System.Environment]::GetEnvironmentVariable($poisonedName, 'Process')
        )) {
        throw "CR-011 dependency materialization forbids $poisonedName."
    }
}
if (
    [System.Environment]::GetEnvironmentVariable('NPM_CONFIG_GLOBAL', 'Process') -match
    '^(?:1|true)$'
) {
    throw 'CR-011 dependency materialization forbids global npm mode.'
}

$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$node = (Get-Command node.exe -ErrorAction Stop).Source
$pythonVersion = (& $backendPython --version 2>&1).ToString().Trim()
$npmVersion = (& $npm --version).Trim()
$nodeVersion = (& $node --version).Trim()
if ($pythonVersion -notmatch '^Python 3\.10(?:\.|$)') {
    throw "CR-011 Python test dependencies require CPython 3.10; found $pythonVersion."
}
if ($npmVersion -ne '10.8.2' -or $nodeVersion -ne 'v20.19.0') {
    throw "CR-011 Node test dependencies require node v20.19.0 and npm 10.8.2."
}
New-Item -ItemType Directory -Path $dependencyRoot, $wheelhouse, $npmCache -Force |
    Out-Null
if (-not (Test-Path -LiteralPath $emptyNpmrc -PathType Leaf)) {
    New-Item -ItemType File -Path $emptyNpmrc -Force | Out-Null
}

if ($AcquireFromOfficialRegistries) {
    & $backendPython -I -m pip --isolated download `
        --requirement $requirements `
        --require-hashes `
        --only-binary ':all:' `
        --implementation cp `
        --python-version 3.10 `
        --abi cp310 `
        --platform win_amd64 `
        --index-url 'https://pypi.org/simple' `
        --dest $wheelhouse `
        --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw 'CR-011 Python test dependency acquisition failed.'
    }

    Push-Location $nodeToolRoot
    try {
        & $npm ci `
            --ignore-scripts `
            --include=dev `
            --no-audit `
            --no-fund `
            --update-notifier=false `
            --registry='https://registry.npmjs.org/' `
            --cache $npmCache `
            --userconfig $emptyNpmrc
        if ($LASTEXITCODE -ne 0) {
            throw 'CR-011 Node test dependency acquisition failed.'
        }
    }
    finally {
        Pop-Location
    }
}

$temporaryPythonSite = Join-Path $dependencyRoot (
    'python-site-' + [guid]::NewGuid().ToString('N')
)
try {
    & $backendPython -I -m pip --isolated install `
        --requirement $requirements `
        --require-hashes `
        --only-binary ':all:' `
        --no-index `
        --find-links $wheelhouse `
        --target $temporaryPythonSite `
        --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw 'CR-011 Python test dependencies cannot be materialized offline.'
    }

    if (Test-Path -LiteralPath $pythonSite) {
        Remove-Item -LiteralPath $pythonSite -Recurse -Force
    }
    Move-Item -LiteralPath $temporaryPythonSite -Destination $pythonSite
}
finally {
    if (Test-Path -LiteralPath $temporaryPythonSite) {
        Remove-Item -LiteralPath $temporaryPythonSite -Recurse -Force
    }
}

Push-Location $nodeToolRoot
try {
    & $npm ci `
        --offline `
        --ignore-scripts `
        --include=dev `
        --no-audit `
        --no-fund `
        --update-notifier=false `
        --cache $npmCache `
        --userconfig $emptyNpmrc
    if ($LASTEXITCODE -ne 0) {
        throw 'CR-011 Node test dependencies cannot be materialized offline.'
    }
}
finally {
    Pop-Location
}

$versionProbe = @'
import importlib.metadata as metadata
import sys

sys.path.insert(0, sys.argv[1])
from jsonschema import Draft202012Validator

assert metadata.version("jsonschema") == "4.26.0"
assert Draft202012Validator.META_SCHEMA["$id"] == (
    "https://json-schema.org/draft/2020-12/schema"
)
print("PYTHON_JSONSCHEMA_DRAFT202012=4.26.0")
'@
$pythonOutput = @($versionProbe | & $backendPython -I -S - $pythonSite 2>&1)
if ($LASTEXITCODE -ne 0) {
    $pythonOutput | ForEach-Object { $_.ToString() }
    throw 'CR-011 Python Draft 2020-12 dependency probe failed.'
}

Push-Location $nodeToolRoot
try {
    $nodeVersionProbe = @'
const metadata = require('./node_modules/ajv/package.json');
const Ajv2020 = require('ajv/dist/2020').default;
if (metadata.version !== '8.20.0' || !new Ajv2020()) process.exit(1);
console.log('NODE_AJV_DRAFT202012=8.20.0');
'@
    $nodeOutput = @(& $node -e $nodeVersionProbe 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $nodeOutput | ForEach-Object { $_.ToString() }
        throw 'CR-011 Node Draft 2020-12 dependency probe failed.'
    }
}
finally {
    Pop-Location
}

$pythonOutput | ForEach-Object { $_.ToString() }
$nodeOutput | ForEach-Object { $_.ToString() }
if ($AcquireFromOfficialRegistries) {
    'CR011_GATE_B_DEPENDENCY_ACQUISITION=PYPI_AND_NPM_PACKAGE_REGISTRIES_ONLY'
}
else {
    'CR011_GATE_B_DEPENDENCY_ACQUISITION=OFFLINE_CACHE_ONLY'
}
'CR011_GATE_B_TEST_DEPENDENCIES=READY'
