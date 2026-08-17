[CmdletBinding()]
param(
    [string]$BackendPythonPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
if ([string]::IsNullOrWhiteSpace($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
}
elseif (-not [System.IO.Path]::IsPathRooted($BackendPythonPath)) {
    $BackendPythonPath = Join-Path $projectRoot $BackendPythonPath
}

$backendPython = [System.IO.Path]::GetFullPath($BackendPythonPath)
$verifierPath = Join-Path $projectRoot 'scripts/verify-remote-branch-protection-fixture.py'
foreach ($path in @($backendPython, $verifierPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Required branch-protection fixture test input is missing.'
    }
}

$expectedSuccess = @(
    'BRANCH_PROTECTION_FIXTURE_VERIFY=PASS',
    'BRANCH_PROTECTION_EVIDENCE_SCOPE=SYNTHETIC_OFFLINE_ONLY',
    'BASELINE_TASK_STATUS=PARTIAL (remote branch protection evidence required)',
    'REMOTE_BRANCH_PROTECTION=NOT_RUN (synthetic fixture only)'
)
$expectedFailure = 'BRANCH_PROTECTION_FIXTURE_VERIFY=FAIL'
$syntheticSecret = 'synthetic-secret-' + ('X' * 24)
$positiveText = @'
{"fixture_version":"branch-protection-fixture-v1","evidence_scope":"synthetic_offline_only","branches":[{"name":"main","allow_force_push":false,"require_pull_request":true,"minimum_independent_reviews":1,"required_check_categories":["static","test"]},{"name":"develop","allow_force_push":false,"require_pull_request":true,"minimum_independent_reviews":1,"required_check_categories":["static","test"]}]}
'@

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)

    if ($Value.IndexOfAny([char[]]@([char]0, [char]10, [char]13, [char]34)) -ge 0) {
        throw 'Native argument contains a forbidden character.'
    }
    return '"' + $Value + '"'
}

function ConvertTo-Utf8Bytes {
    param([Parameter(Mandatory)][string]$Text)

    return [System.Text.UTF8Encoding]::new($false, $true).GetBytes($Text)
}

function Invoke-FixtureVerifier {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][byte[]]$InputBytes,
        [AllowEmptyCollection()][string[]]$Arguments = @('--stdin'),
        [hashtable]$EnvironmentOverrides = @{}
    )

    $payloadBase64 = [System.Convert]::ToBase64String($InputBytes)
    $driverCode = "import base64,subprocess,sys;r=subprocess.run([sys.executable,'-I','-S','-B',sys.argv[1],*sys.argv[3:]],input=base64.b64decode(sys.argv[2]),capture_output=True);sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr);raise SystemExit(r.returncode)"
    $nativeArguments = @(
        '-I', '-S', '-B', '-c', $driverCode, $verifierPath, $payloadBase64
    ) + $Arguments
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $backendPython
    $startInfo.Arguments = (($nativeArguments | ForEach-Object {
                ConvertTo-NativeArgument -Value $_
            }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($entry in $EnvironmentOverrides.GetEnumerator()) {
        $startInfo.EnvironmentVariables[$entry.Key] = [string]$entry.Value
    }

    $process = [System.Diagnostics.Process]::Start($startInfo)
    if ($null -eq $process) {
        throw 'Failed to start the branch-protection fixture verifier.'
    }
    try {
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

function Assert-Success {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$CaseName
    )

    $expectedStdout = ($expectedSuccess -join [System.Environment]::NewLine) +
        [System.Environment]::NewLine
    if ($Result.ExitCode -ne 0 -or $Result.Stdout -cne $expectedStdout -or
        $Result.Stderr -cne '') {
        throw "Valid fixture case '$CaseName' did not produce the exact success contract."
    }
}

function Assert-Failure {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$CaseName
    )

    $expectedStdout = $expectedFailure + [System.Environment]::NewLine
    if ($Result.ExitCode -eq 0 -or $Result.Stdout -cne $expectedStdout -or
        $Result.Stderr -cne '') {
        throw "Invalid fixture case '$CaseName' did not fail with the exact closed contract."
    }
    if ($Result.Stdout.Contains('PASS') -or $Result.Stdout.Contains($syntheticSecret) -or
        $Result.Stderr.Contains($syntheticSecret)) {
        throw "Fixture case '$CaseName' exposed input material or a success marker."
    }
}

function Invoke-InvalidBytesCase {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][AllowEmptyCollection()][byte[]]$Bytes
    )

    Assert-Failure -CaseName $Name -Result (
        Invoke-FixtureVerifier -InputBytes $Bytes
    )
}

function Convert-MutatedDocument {
    param([Parameter(Mandatory)][scriptblock]$Mutation)

    $document = $positiveText | ConvertFrom-Json
    & $Mutation $document
    return ConvertTo-Json -InputObject $document -Depth 10 -Compress
}

$positiveBytes = ConvertTo-Utf8Bytes -Text $positiveText
$maxSizeValidBytes = [byte[]]::new(16384)
if ($positiveBytes.Length -ge $maxSizeValidBytes.Length) {
    throw 'Positive fixture unexpectedly exceeds the maximum fixture size.'
}
[System.Array]::Copy($positiveBytes, $maxSizeValidBytes, $positiveBytes.Length)
for ($index = $positiveBytes.Length; $index -lt $maxSizeValidBytes.Length; $index++) {
    $maxSizeValidBytes[$index] = 0x20
}
$tooLargeValidBytes = [byte[]]::new(16385)
[System.Array]::Copy($maxSizeValidBytes, $tooLargeValidBytes, $maxSizeValidBytes.Length)
$tooLargeValidBytes[$tooLargeValidBytes.Length - 1] = 0x20

Assert-Success -CaseName 'positive' -Result (
    Invoke-FixtureVerifier -InputBytes $positiveBytes
)
Assert-Success -CaseName 'maximum-size-valid' -Result (
    Invoke-FixtureVerifier -InputBytes $maxSizeValidBytes
)
Assert-Success -CaseName 'poisoned-environment' -Result (
    Invoke-FixtureVerifier -InputBytes $positiveBytes -EnvironmentOverrides @{
        PATH = 'Z:\synthetic-no-tools'
        GIT_DIR = $syntheticSecret
        GIT_WORK_TREE = $syntheticSecret
        GITHUB_TOKEN = $syntheticSecret
        GITLAB_TOKEN = $syntheticSecret
        HTTPS_PROXY = 'http://' + $syntheticSecret + '.invalid'
        PYTHONPATH = $syntheticSecret
        PYTHONINSPECT = '1'
    }
)

Assert-Failure -CaseName 'missing-stdin-mode' -Result (
    Invoke-FixtureVerifier -InputBytes ([byte[]]@()) -Arguments ([string[]]@())
)
Assert-Failure -CaseName 'path-like-argument' -Result (
    Invoke-FixtureVerifier -InputBytes ([byte[]]@()) -Arguments @(
        '\\attacker.invalid\share\fixture.json'
    )
)
Assert-Failure -CaseName 'extra-argument' -Result (
    Invoke-FixtureVerifier -InputBytes ([byte[]]@()) -Arguments @(
        '--stdin', $syntheticSecret
    )
)

Invoke-InvalidBytesCase -Name 'empty' -Bytes ([byte[]]@())
Invoke-InvalidBytesCase -Name 'whitespace' -Bytes (ConvertTo-Utf8Bytes -Text '   ')
Invoke-InvalidBytesCase -Name 'too-large-valid' -Bytes $tooLargeValidBytes
Invoke-InvalidBytesCase -Name 'too-large-invalid-json' -Bytes ([byte[]]::new(16385))
Invoke-InvalidBytesCase -Name 'bom' -Bytes ([byte[]]@(
        0xEF, 0xBB, 0xBF
    ) + $positiveBytes)
Invoke-InvalidBytesCase -Name 'invalid-utf8' -Bytes ([byte[]]@(
        0x7B, 0x22, 0x78, 0x22, 0x3A, 0xFF, 0x7D
    ))
Invoke-InvalidBytesCase -Name 'invalid-utf8-before-valid-json' -Bytes (
    [byte[]]@(0xFF) + $positiveBytes
)
Invoke-InvalidBytesCase -Name 'utf16-le' -Bytes (
    [System.Text.Encoding]::Unicode.GetBytes($positiveText)
)
Invoke-InvalidBytesCase -Name 'utf16-be' -Bytes (
    [System.Text.Encoding]::BigEndianUnicode.GetBytes($positiveText)
)
Invoke-InvalidBytesCase -Name 'nul' -Bytes ($positiveBytes + [byte[]]@(0))
Invoke-InvalidBytesCase -Name 'comment' -Bytes (
    ConvertTo-Utf8Bytes -Text ('{/* synthetic */' + $positiveText.Substring(1))
)
Invoke-InvalidBytesCase -Name 'trailing-document' -Bytes (
    ConvertTo-Utf8Bytes -Text ($positiveText + '{}')
)
Invoke-InvalidBytesCase -Name 'root-array' -Bytes (ConvertTo-Utf8Bytes -Text '[]')
Invoke-InvalidBytesCase -Name 'root-null' -Bytes (ConvertTo-Utf8Bytes -Text 'null')

foreach ($constant in @('NaN', 'Infinity', '-Infinity')) {
    Invoke-InvalidBytesCase -Name ('constant-' + $constant.Replace('-', 'negative')) -Bytes (
        ConvertTo-Utf8Bytes -Text (
            $positiveText.Replace('"minimum_independent_reviews":1',
                '"minimum_independent_reviews":' + $constant)
        )
    )
}

foreach ($key in @('fixture_version', 'evidence_scope', 'branches')) {
    $duplicate = '{"' + $key + '":null,' + $positiveText.Substring(1)
    Invoke-InvalidBytesCase -Name ('duplicate-root-' + $key) -Bytes (
        ConvertTo-Utf8Bytes -Text $duplicate
    )
}
$escapedDuplicate = '{"\u0066ixture_version":null,' + $positiveText.Substring(1)
Invoke-InvalidBytesCase -Name 'duplicate-root-escaped-key' -Bytes (
    ConvertTo-Utf8Bytes -Text $escapedDuplicate
)

foreach ($key in @(
        'name', 'allow_force_push', 'require_pull_request',
        'minimum_independent_reviews', 'required_check_categories'
    )) {
    $needle = '"' + $key + '":'
    $index = $positiveText.IndexOf($needle, [System.StringComparison]::Ordinal)
    if ($index -lt 0) {
        throw 'Positive fixture does not contain an expected branch key.'
    }
    $duplicate = $positiveText.Insert($index, '"' + $key + '":null,')
    Invoke-InvalidBytesCase -Name ('duplicate-branch-' + $key) -Bytes (
        ConvertTo-Utf8Bytes -Text $duplicate
    )
}

$mutations = @(
    @{ Name = 'missing-root-key'; Apply = { param($d) $d.PSObject.Properties.Remove('evidence_scope') } },
    @{ Name = 'extra-root-key'; Apply = { param($d) $d | Add-Member -NotePropertyName 'extra' -NotePropertyValue $syntheticSecret } },
    @{ Name = 'wrong-version'; Apply = { param($d) $d.fixture_version = 'v2' } },
    @{ Name = 'wrong-scope'; Apply = { param($d) $d.evidence_scope = 'remote_verified' } },
    @{ Name = 'branches-object'; Apply = { param($d) $d.branches = [pscustomobject]@{} } },
    @{ Name = 'branch-missing'; Apply = { param($d) $d.branches = @($d.branches[0]) } },
    @{ Name = 'branch-duplicate'; Apply = { param($d) $d.branches = @($d.branches[0], $d.branches[0]) } },
    @{ Name = 'branch-reversed'; Apply = { param($d) $d.branches = @($d.branches[1], $d.branches[0]) } },
    @{ Name = 'branch-extra'; Apply = { param($d) $d.branches += $d.branches[0] } },
    @{ Name = 'branch-case'; Apply = { param($d) $d.branches[0].name = 'Main' } },
    @{ Name = 'branch-whitespace'; Apply = { param($d) $d.branches[0].name = ' main' } },
    @{ Name = 'branch-homoglyph'; Apply = { param($d) $d.branches[0].name = "ma$([char]0x0131)n" } },
    @{ Name = 'missing-branch-key'; Apply = { param($d) $d.branches[0].PSObject.Properties.Remove('name') } },
    @{ Name = 'extra-branch-key'; Apply = { param($d) $d.branches[0] | Add-Member -NotePropertyName 'provider' -NotePropertyValue $syntheticSecret } },
    @{ Name = 'force-push-true'; Apply = { param($d) $d.branches[0].allow_force_push = $true } },
    @{ Name = 'force-push-zero'; Apply = { param($d) $d.branches[0].allow_force_push = 0 } },
    @{ Name = 'force-push-null'; Apply = { param($d) $d.branches[0].allow_force_push = $null } },
    @{ Name = 'force-push-empty-string'; Apply = { param($d) $d.branches[0].allow_force_push = '' } },
    @{ Name = 'force-push-string'; Apply = { param($d) $d.branches[0].allow_force_push = 'false' } },
    @{ Name = 'pull-request-false'; Apply = { param($d) $d.branches[0].require_pull_request = $false } },
    @{ Name = 'pull-request-integer'; Apply = { param($d) $d.branches[0].require_pull_request = 1 } },
    @{ Name = 'reviews-zero'; Apply = { param($d) $d.branches[0].minimum_independent_reviews = 0 } },
    @{ Name = 'reviews-boolean'; Apply = { param($d) $d.branches[0].minimum_independent_reviews = $true } },
    @{ Name = 'reviews-string'; Apply = { param($d) $d.branches[0].minimum_independent_reviews = '1' } },
    @{ Name = 'checks-missing'; Apply = { param($d) $d.branches[0].required_check_categories = @('static') } },
    @{ Name = 'checks-reversed'; Apply = { param($d) $d.branches[0].required_check_categories = @('test', 'static') } },
    @{ Name = 'checks-duplicate'; Apply = { param($d) $d.branches[0].required_check_categories = @('static', 'test', 'test') } },
    @{ Name = 'checks-extra'; Apply = { param($d) $d.branches[0].required_check_categories = @('static', 'test', 'lint') } },
    @{ Name = 'checks-string'; Apply = { param($d) $d.branches[0].required_check_categories = 'static+test' } }
)
foreach ($mutation in $mutations) {
    Invoke-InvalidBytesCase -Name $mutation.Name -Bytes (
        ConvertTo-Utf8Bytes -Text (Convert-MutatedDocument -Mutation $mutation.Apply)
    )
}

foreach ($numberToken in @('1.0', '1e0', 'null')) {
    Invoke-InvalidBytesCase -Name ('reviews-token-' + $numberToken.Replace('.', '-')) -Bytes (
        ConvertTo-Utf8Bytes -Text (
            $positiveText.Replace('"minimum_independent_reviews":1',
                '"minimum_independent_reviews":' + $numberToken)
        )
    )
}

$markerInjection = Convert-MutatedDocument -Mutation {
    param($d)
    $d | Add-Member -NotePropertyName 'marker' -NotePropertyValue (
        'BRANCH_PROTECTION_FIXTURE_VERIFY=PASS ' + $syntheticSecret
    )
}
Invoke-InvalidBytesCase -Name 'marker-injection' -Bytes (
    ConvertTo-Utf8Bytes -Text $markerInjection
)

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $verifierPath
$sourceBase64 = [System.Convert]::ToBase64String(
    [System.Text.UTF8Encoding]::new($false, $true).GetBytes($source)
)
$astAuditCode = @'
import ast
import base64
import sys

tree = ast.parse(base64.b64decode(sys.argv[1]).decode('utf-8'))
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imports.extend(('import', item.name, item.asname) for item in node.names)
    elif isinstance(node, ast.ImportFrom):
        imports.extend(
            ('from', node.module, item.name, item.asname, node.level)
            for item in node.names
        )
expected_imports = {
    ('from', '__future__', 'annotations', None, 0),
    ('import', 'json', None),
    ('import', 'sys', None),
    ('from', 'typing', 'Any', None, 0),
}
allowed_calls = {
    'FixtureError',
    'SystemExit',
    '_parse_fixture',
    '_read_fixture',
    '_validate_branch',
    'json.loads',
    'len',
    'main',
    'payload.decode',
    'payload.startswith',
    'print',
    'set',
    'sys.stdin.buffer.read',
    'type',
    'validate_fixture',
}
calls = {
    ast.unparse(node.func)
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
}
if set(imports) != expected_imports or not calls <= allowed_calls:
    raise SystemExit(1)
print('SOURCE_BOUNDARY=PASS')
'@
$astCodeBase64 = [System.Convert]::ToBase64String(
    [System.Text.UTF8Encoding]::new($false, $true).GetBytes($astAuditCode)
)
$astBootstrapCode = "import base64,sys;exec(compile(base64.b64decode(sys.argv.pop(1)),'<source-audit>','exec'))"
$astArguments = @(
    '-I', '-S', '-B', '-c', $astBootstrapCode, $astCodeBase64, $sourceBase64
)
$astStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$astStartInfo.FileName = $backendPython
$astStartInfo.Arguments = (($astArguments | ForEach-Object {
            ConvertTo-NativeArgument -Value $_
        }) -join ' ')
$astStartInfo.UseShellExecute = $false
$astStartInfo.CreateNoWindow = $true
$astStartInfo.RedirectStandardOutput = $true
$astStartInfo.RedirectStandardError = $true
$astProcess = [System.Diagnostics.Process]::Start($astStartInfo)
if ($null -eq $astProcess) {
    throw 'Failed to start the branch-protection source boundary audit.'
}
try {
    $astStdout = $astProcess.StandardOutput.ReadToEnd()
    $astStderr = $astProcess.StandardError.ReadToEnd()
    $astProcess.WaitForExit()
    $astExitCode = $astProcess.ExitCode
}
finally {
    $astProcess.Dispose()
}
$expectedAstStdout = 'SOURCE_BOUNDARY=PASS' + [System.Environment]::NewLine
if ($astExitCode -ne 0 -or $astStdout -cne $expectedAstStdout -or $astStderr -cne '') {
    throw 'Branch-protection fixture verifier AST boundary changed.'
}
if ($source -notmatch 'sys\.stdin\.buffer\.read\(MAX_FIXTURE_BYTES \+ 1\)' -or
    $source -notmatch 'sys\.argv != \[sys\.argv\[0\], "--stdin"\]') {
    throw 'Branch-protection fixture verifier I/O boundary changed.'
}

'BRANCH_PROTECTION_FIXTURE_TESTS=PASS'
