[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)
$verifierPath = Join-Path $projectRoot 'scripts/verify-cr011-gate-b.ps1'
$vectorPath = Join-Path (
    $projectRoot
) 'docs/change-requests/artifacts/CR-011/ai-policy-v1.negative-vectors.json'
$childPowerShell = (Get-Command powershell -CommandType Application -ErrorAction Stop).Source
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-cr011-gate-b-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'CR-011 Gate B self-test temporary path escaped the system temporary directory.'
}
[void](New-Item -ItemType Directory -Path $tempRoot)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$completedCases = 0

function Invoke-Verifier {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $verifierPath @Arguments 2>&1
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Lines = @($output | ForEach-Object { $_.ToString().TrimEnd("`r") })
    }
}

function Assert-FailsClosed {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    $result = Invoke-Verifier -Arguments $Arguments
    if ($result.ExitCode -eq 0) {
        throw "$Name unexpectedly passed CR-011 Gate B."
    }
    $trustedMarkers = @(
        'CR011_GATE_B_HARNESS=PASS',
        'CR011_GATE_B=PASS',
        'CR011_GATE_B_SCHEMA_ENGINES=2/2'
    )
    foreach ($marker in $trustedMarkers) {
        if ($result.Lines -ccontains $marker) {
            throw "$Name emitted a trusted PASS marker after failure."
        }
    }
    $script:completedCases += 1
}

function Write-JsonFixture {
    param(
        [object]$Value,
        [string]$Path
    )

    $text = $Value | ConvertTo-Json -Depth 100 -Compress
    [System.IO.File]::WriteAllText($Path, $text, $utf8NoBom)
}

try {
    Assert-FailsClosed -Name 'missing isolated Python dependencies' -Arguments @(
        '-PythonSitePath', (Join-Path $tempRoot 'missing-python-site')
    )
    Assert-FailsClosed -Name 'missing npm lock' -Arguments @(
        '-PackageLockPath', (Join-Path $tempRoot 'missing-package-lock.json')
    )

    $deleted = Get-Content -Raw -LiteralPath $vectorPath | ConvertFrom-Json
    $deleted.cases = @($deleted.cases | Select-Object -Skip 1)
    $deletedPath = Join-Path $tempRoot 'deleted-vector.json'
    Write-JsonFixture -Value $deleted -Path $deletedPath
    Assert-FailsClosed -Name 'deleted negative vector' -Arguments @(
        '-NegativeVectorFixturePath', $deletedPath
    )

    $duplicate = Get-Content -Raw -LiteralPath $vectorPath | ConvertFrom-Json
    $duplicate.cases[$duplicate.cases.Count - 1] = $duplicate.cases[0]
    $duplicatePath = Join-Path $tempRoot 'duplicate-vector.json'
    Write-JsonFixture -Value $duplicate -Path $duplicatePath
    Assert-FailsClosed -Name 'duplicate negative vector' -Arguments @(
        '-NegativeVectorFixturePath', $duplicatePath
    )

    Assert-FailsClosed -Name 'always-true Schema adapter' -Arguments @(
        '-SchemaMode', 'always-true'
    )
    Assert-FailsClosed -Name 'missing Node guard' -Arguments @(
        '-NodeGuardPath', (Join-Path $tempRoot 'missing-zero-socket-guard.cjs')
    )

    $duplicateJsonNode = Join-Path $tempRoot 'duplicate-json-node.exe'
    $fakeNodeSource = @'
using System;
using System.Diagnostics;
using System.IO;

public static class Cr011FakeNode
{
    public static int Main(string[] args)
    {
        string name = Path.GetFileNameWithoutExtension(
            Process.GetCurrentProcess().MainModule.FileName
        );
        if (name == "wrong-version-node")
        {
            Console.WriteLine("v99.0.0");
            return 0;
        }
        if (name == "forged-node")
        {
            Console.WriteLine("CR011_GATE_B_HARNESS=PASS");
            Console.WriteLine("CR011_GATE_B=PASS");
            Console.WriteLine("CR011_GATE_B_SCHEMA_ENGINES=2/2");
            return 7;
        }
        if (args.Length == 1 && args[0] == "--version")
        {
            Console.WriteLine("v20.19.0");
            return 0;
        }
        if (args.Length == 1 && Path.GetFileName(args[0]) == "test-validator.cjs")
        {
            Console.WriteLine("CR011_NODE_VALIDATOR_SELF_TEST=PASS");
            return 0;
        }
        if (Array.IndexOf(args, "--eval") >= 0)
        {
            Console.WriteLine(
                "{\"node_version\":\"20.19.0\","
                + "\"guard_id\":\"cr011-zero-socket-guard-v1\","
                + "\"patch_count\":108,\"socket_attempts\":0,\"integrity\":true}"
            );
            return 0;
        }
        if (Array.IndexOf(args, "--probe") >= 0)
        {
            if (name == "null-guard-node")
            {
                Console.WriteLine(
                    "{\"passed\":true,\"attempts\":6,\"integrity\":true,"
                    + "\"patch_count\":108,\"results\":[null,null,null,null,null,null]}"
                );
                return 0;
            }
            Console.WriteLine(
                "{\"passed\":true,\"attempts\":6,\"integrity\":true,"
                + "\"patch_count\":108,\"results\":["
                + "{\"id\":\"tcp\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"},"
                + "{\"id\":\"dns_localhost\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"},"
                + "{\"id\":\"dns_other_hostname\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"},"
                + "{\"id\":\"udp\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"},"
                + "{\"id\":\"windows_named_pipe\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"},"
                + "{\"id\":\"local_socket_path\",\"denied\":true,\"code\":\"CR011_ZERO_SOCKET_DENIED\"}]}"
            );
            return 0;
        }
        Console.WriteLine(
            "{\"engine_id\":\"ajv@8.20.0-draft2020\",\"engine_id\":\"forged\"}"
        );
        return 0;
    }
}
'@
    Add-Type -TypeDefinition $fakeNodeSource `
        -OutputAssembly $duplicateJsonNode `
        -OutputType ConsoleApplication
    $wrongVersionNode = Join-Path $tempRoot 'wrong-version-node.exe'
    $fakeNode = Join-Path $tempRoot 'forged-node.exe'
    $nullGuardNode = Join-Path $tempRoot 'null-guard-node.exe'
    Copy-Item -LiteralPath $duplicateJsonNode -Destination $wrongVersionNode
    Copy-Item -LiteralPath $duplicateJsonNode -Destination $fakeNode
    Copy-Item -LiteralPath $duplicateJsonNode -Destination $nullGuardNode
    Assert-FailsClosed -Name 'wrong Node runtime version' -Arguments @(
        '-NodePath', $wrongVersionNode
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $forgedOutput = @(& $fakeNode 2>&1)
        $forgedExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if (
        $forgedExitCode -ne 7 -or
        @($forgedOutput | ForEach-Object { $_.ToString() }) -cnotcontains 'CR011_GATE_B=PASS'
    ) {
        throw 'The forged PASS self-test executable did not establish its precondition.'
    }
    Assert-FailsClosed -Name 'nonzero Node process with forged PASS output' -Arguments @(
        '-NodePath', $fakeNode
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $duplicateOutput = @(& $duplicateJsonNode --require ignored --eval ignored 2>&1)
        $duplicateExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if (
        $duplicateExitCode -ne 0 -or
        @($duplicateOutput | ForEach-Object { $_.ToString() }) -cnotcontains `
            '{"node_version":"20.19.0","guard_id":"cr011-zero-socket-guard-v1","patch_count":108,"socket_attempts":0,"integrity":true}'
    ) {
        throw 'The exit-zero forged JSON self-test executable did not establish its precondition.'
    }
    Assert-FailsClosed -Name 'exit-zero Node process with duplicate-key JSON' -Arguments @(
        '-NodePath', $duplicateJsonNode
    )
    Assert-FailsClosed -Name 'exit-zero Node guard with null result entries' -Arguments @(
        '-NodePath', $nullGuardNode
    )

    $poisonedNames = @(
        'ALL_PROXY',
        'HTTPS_PROXY',
        'NODE_OPTIONS',
        'NODE_PATH',
        'PYTHONHOME',
        'PYTHONPATH',
        'PYTHONWARNINGS'
    )
    $previousEnvironment = @{}
    foreach ($name in $poisonedNames) {
        $previousEnvironment[$name] = [pscustomobject]@{
            Present = Test-Path "Env:$name"
            Value = [System.Environment]::GetEnvironmentVariable($name, 'Process')
        }
        [System.Environment]::SetEnvironmentVariable(
            $name,
            $(
                if ($name -eq 'NODE_OPTIONS') {
                    '--require=Z:\cr011-gate-b-missing-poison.cjs'
                }
                elseif ($name -eq 'PYTHONWARNINGS') {
                    'error'
                }
                else {
                    'Z:\cr011-gate-b-poison'
                }
            ),
            'Process'
        )
    }
    try {
        $poisonResult = Invoke-Verifier -Arguments @()
    }
    finally {
        foreach ($name in $poisonedNames) {
            $previous = $previousEnvironment[$name]
            [System.Environment]::SetEnvironmentVariable(
                $name,
                $(if ($previous.Present) { $previous.Value } else { $null }),
                'Process'
            )
        }
    }
    if (
        $poisonResult.ExitCode -ne 0 -or
        $poisonResult.Lines.Count -ne 20 -or
        $poisonResult.Lines -cnotcontains 'CR011_GATE_B=PASS' -or
        $poisonResult.Lines -cnotcontains 'CR011_GATE_B_SCHEMA_ENGINES=2/2'
    ) {
        throw 'Environment poisoning prevented the verifier from establishing trusted evidence.'
    }
    $expectedOrderedLines = @{
        0 = 'CR011_GATE_B_STAGE1=PASS'
        3 = 'CR011_GATE_B_STAGE1_ZERO_SOCKET_ATTEMPTS=0'
        4 = 'CR011_GATE_B_STAGE1_NEGATIVE_CASES=PASS'
        5 = 'CR011_NODE_VALIDATOR_SELF_TEST=PASS'
        6 = 'CR011_GATE_B_HARNESS=PASS'
        7 = 'CR011_GATE_B_CASES=27/27'
        8 = 'CR011_GATE_B_NEGATIVE_VECTORS=25/25'
        9 = 'CR011_GATE_B_PYTHON_SCHEMA_CALLS=20'
        10 = 'CR011_GATE_B_NODE_SCHEMA_CALLS=20'
        11 = 'CR011_GATE_B_PYTHON_ENGINE=jsonschema@4.26.0-draft202012'
        12 = 'CR011_GATE_B_NODE_ENGINE=ajv@8.20.0-draft2020'
        13 = 'CR011_ZERO_SOCKET_GUARD=PASS'
        14 = 'CR011_ZERO_SOCKET_ATTEMPTS=0'
        15 = 'CR011_GATE_B=PASS'
        16 = 'CR011_GATE_B_SCHEMA_ENGINES=2/2'
        17 = 'CR011_PROVIDER_NETWORK=NOT_RUN'
        18 = 'CR011_PERSISTENT_RUNTIME=NOT_AUTHORIZED'
        19 = 'CR011_PRODUCTION=NOT_AUTHORIZED'
    }
    foreach ($entry in $expectedOrderedLines.GetEnumerator()) {
        if ($poisonResult.Lines[$entry.Key] -cne $entry.Value) {
            throw 'Environment poisoning run emitted out-of-order final evidence.'
        }
    }
    if (
        $poisonResult.Lines[1] -cnotmatch '^CR011_GATE_B_STAGE1_COLLECTED=(\d+)$' -or
        $poisonResult.Lines[2] -cnotmatch '^CR011_GATE_B_STAGE1_EXECUTED=(\d+)$' -or
        ($poisonResult.Lines[1] -replace '^.*=', '') -cne `
            ($poisonResult.Lines[2] -replace '^.*=', '')
    ) {
        throw 'Environment poisoning run emitted invalid Stage1 counts.'
    }
    $completedCases += 1
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $resolvedTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
        if (-not $resolvedTempRoot.StartsWith(
            $tempBase,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw 'Refusing to remove a CR-011 Gate B self-test path outside the temporary root.'
        }
        Remove-Item -LiteralPath $resolvedTempRoot -Recurse -Force
    }
}

if ($completedCases -ne 11) {
    throw "CR-011 Gate B anti-forgery coverage mismatch: $completedCases/11."
}
$global:LASTEXITCODE = 0
'CR011_GATE_B_NEGATIVE_CASES=11/11'
