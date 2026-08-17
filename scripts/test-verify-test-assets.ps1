[CmdletBinding()]
param(
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Join-Path $PSScriptRoot '..'
}

$root = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRoot).Path)
$verifierPath = Join-Path $root 'scripts/verify-test-assets.ps1'
$fixturesSource = Join-Path $root 'tests/fixtures'
$matrixSource = Join-Path $root 'docs/testing/p0-traceability-matrix.csv'
$childPowerShell = (Get-Command powershell -ErrorAction Stop).Source
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempBasePrefix = $tempBase.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
$tempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $tempBase ('finaudit-test-assets-' + [System.Guid]::NewGuid().ToString('N')))
)
if (-not $tempRoot.StartsWith($tempBasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Temporary test root is outside the operating-system temp directory.'
}

function New-CaseRoot {
    param([Parameter(Mandatory)][string]$Name)

    $caseRoot = Join-Path $tempRoot $Name
    $matrixDirectory = New-Item -ItemType Directory -Path (Join-Path $caseRoot 'docs/testing') -Force
    $testsDirectory = New-Item -ItemType Directory -Path (Join-Path $caseRoot 'tests') -Force
    Copy-Item -LiteralPath $matrixSource -Destination $matrixDirectory.FullName
    Copy-Item -LiteralPath $fixturesSource -Destination $testsDirectory.FullName -Recurse
    return $caseRoot
}

function Invoke-Validator {
    param([Parameter(Mandatory)][string]$CaseRoot)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(
            & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $verifierPath -ProjectRoot $CaseRoot 2>&1
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

function Write-Manifest {
    param(
        [Parameter(Mandatory)][string]$CaseRoot,
        [Parameter(Mandatory)]$Manifest
    )

    $manifestPath = Join-Path $CaseRoot 'tests/fixtures/manifest.json'
    $Manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

function Read-Manifest {
    param([Parameter(Mandatory)][string]$CaseRoot)

    return Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $CaseRoot 'tests/fixtures/manifest.json') |
        ConvertFrom-Json
}

function Update-BinaryMetadata {
    param(
        [Parameter(Mandatory)][string]$CaseRoot,
        [Parameter(Mandatory)][string]$Id
    )

    $manifest = Read-Manifest -CaseRoot $CaseRoot
    $entry = @($manifest.binary_assets | Where-Object { $_.id -ceq $Id })
    if ($entry.Count -ne 1) {
        throw 'Binary fixture metadata target is not unique.'
    }
    $fixturePath = Join-Path $CaseRoot $entry[0].file
    $entry[0].size_bytes = [long](Get-Item -LiteralPath $fixturePath).Length
    $entry[0].sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fixturePath).Hash
    Write-Manifest -CaseRoot $CaseRoot -Manifest $manifest
}

function Update-DatasetHash {
    param(
        [Parameter(Mandatory)][string]$CaseRoot,
        [Parameter(Mandatory)][string]$Id
    )

    $manifest = Read-Manifest -CaseRoot $CaseRoot
    $entry = @($manifest.items | Where-Object { $_.id -ceq $Id })
    if ($entry.Count -ne 1) {
        throw 'Dataset manifest target is not unique.'
    }
    $fixturePath = Join-Path $CaseRoot $entry[0].file
    $entry[0].sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fixturePath).Hash
    Write-Manifest -CaseRoot $CaseRoot -Manifest $manifest
}

$expectedFailurePatterns = @{
    'missing-file' = 'points to a missing file.'
    'extra-file' = 'Fixtures directory files do not match the fixed allowlist.'
    'hash-drift' = 'SHA-256 does not match.'
    'size-drift' = 'byte length does not match.'
    'repository-size-limit' = 'has an invalid required field.'
    'oversized-physical-file' = 'byte length does not match.'
    'signature-mismatch' = 'static structure result does not match.'
    'docx-missing-core-part' = 'static structure result does not match.'
    'path-traversal' = 'has an unsafe relative path.'
    'traceability-drift' = 'does not use its fixed related fixture IDs.'
    'malformed-declared-valid' = 'static structure result does not match.'
    'unknown-manifest-field' = 'fields do not match the fixed contract.'
    'matrix-p0-task-set-drift' = 'Traceability matrix must include TEST-001.'
    'matrix-column-width-drift' = 'Traceability matrix row does not contain exactly six columns.'
    'manifest-collection-drift' = @(
        'Fixture manifest does not contain exactly four fixed datasets.'
        'Fixture manifest does not contain the fixed binary asset set.'
        'Fixture manifest IDs do not match the fixed dataset definitions.'
        'Binary fixture manifest IDs do not match the fixed definitions.'
    )
    'dataset-version-drift' = @(
        'Fixture manifest dataset_version is invalid.'
        'fixture manifest item 1 dataset_version is invalid.'
    )
    'binary-contract-version-drift' = 'Fixture manifest binary contract version is invalid.'
    'boolean-type-drift' = @(
        'Fixture manifest synthetic flag is not true.'
        'fixture manifest item 1 synthetic flag is not true.'
        'binary fixture manifest item 1 synthetic flag is not true.'
        'break-glass record must remain specification_only with independent approval required.'
    )
    'binary-contract-type-drift' = @(
        'binary fixture manifest item 1 size_bytes must be a JSON integer.'
        'binary fixture manifest item 1 related_fixture_ids must be a JSON array.'
        'binary fixture manifest item 1 task_ids must be a JSON array.'
    )
    'account-role-drift' = 'active account roles do not satisfy the formal TEST-001 minimums.'
    'account-boundary-drift' = @(
        'account ACC-SYSTEM-ADMIN fixed active record does not match Request.'
        'account ACC-FINANCE-REVIEWER fixed active record does not match Request.'
    )
    'break-glass-state-drift' = 'break-glass record must remain specification_only'
    'core-business-c001-amount-drift' = 'C-001 fixed contract baseline does not match Request.'
    'core-party-names-drift' = 'C-001 fixed contract baseline does not match Request.'
    'core-business-duplicate-tuple-drift' = 'I-001-DUP duplicate tuple does not match I-001.'
    'core-business-oversized-exception-drift' = 'CHUNK-OVERSIZED-CONTENT is not an unapproved over-maximum chunk.'
    'policy-v2-name-drift' = 'P-001-V2 fixed scalar semantics do not match Request.'
    'policy-v2-clause-5-1-drift' = 'P-001-V2 is missing a fixed Request clause anchor.'
    'security-id-drift' = 'fixture manifest item 4 must contain exactly one NEG-DIRECT-PROMPT-INJECTION fixture.'
    'security-category-drift' = @(
        'security fixture NEG-DIRECT-PROMPT-INJECTION category does not match the fixed semantic contract.'
        'security fixture NEG-PROMPT-INJECTION category does not match the fixed semantic contract.'
        'security fixture NEG-HIDDEN-MARKUP-INSTRUCTION category does not match the fixed semantic contract.'
    )
    'security-forged-citation-drift' = 'security fixture NEG-FORGED-CITATION expected semantics do not match the fixed semantic contract.'
    'security-table-cell-role-override-drift' = 'security fixture NEG-TABLE-CELL-ROLE-OVERRIDE does not match the fixed semantic contract.'
    'security-user-forged-candidate-id-drift' = 'security fixture NEG-USER-FORGED-CANDIDATE-ID does not match the fixed semantic contract.'
    'security-scalar-contract-drift' = @(
        'security fixture NEG-NO-ANSWER input does not match the fixed negative scenario.'
        'security fixture NEG-UNAUTHORIZED input does not match the fixed negative scenario.'
        'security fixture NEG-DIRECT-PROMPT-INJECTION input does not match the fixed negative scenario.'
        'security fixture NEG-PROMPT-INJECTION input does not match the fixed negative scenario.'
        'security fixture NEG-HIDDEN-MARKUP-INSTRUCTION input does not match the fixed negative scenario.'
        'security fixture NEG-CREDENTIAL-EXFILTRATION input does not match the fixed negative scenario.'
        'security fixture NEG-RULE-TAMPERING input does not match the fixed negative scenario.'
        'security fixture NEG-DIRECT-PROMPT-INJECTION expected semantics do not match the fixed semantic contract.'
        'security fixture NEG-HIDDEN-MARKUP-INSTRUCTION expected semantics do not match the fixed semantic contract.'
    )
    'security-structured-input-invalid' = @(
        'security fixture NEG-MISSING-TARGET-FIELD input does not preserve the missing-field scenario.'
        'security fixture NEG-CONFLICTING-AMOUNTS input does not preserve distinct conflicting evidence.'
        'security fixture NEG-FORGED-CITATION input does not preserve an out-of-allowlist candidate.'
    )
    'retrieval-label-drift' = 'retrieval fixture RET-001-01 label does not match the fixed smoke classification.'
    'retrieval-fixed-baseline-drift' = 'retrieval fixture RET-001 fixed baseline does not match Request.'
    'retrieval-top-k-type-drift' = 'retrieval fixture RET-001 fixed baseline does not match Request.'
}

function Invoke-NegativeCase {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Mutation
    )

    $caseRoot = New-CaseRoot -Name $Name
    & $Mutation $caseRoot
    $result = Invoke-Validator -CaseRoot $caseRoot
    if ($result.ExitCode -eq 0) {
        throw "Negative test case unexpectedly passed: $Name"
    }
    if (-not $expectedFailurePatterns.ContainsKey($Name)) {
        throw "Negative test case has no fixed expected failure pattern: $Name"
    }
    $outputText = $result.Output -join [System.Environment]::NewLine
    foreach ($expectedPattern in @($expectedFailurePatterns[$Name])) {
        if ($outputText -notmatch [regex]::Escape($expectedPattern)) {
            throw "Negative test case failed through an unexpected branch: $Name"
        }
    }
}

$negativeCaseCount = 0
$isolatedPositiveCase = 'NOT_RUN'
$directoryReparseCase = 'NOT_RUN'
$reparseCase = 'NOT_RUN'
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $positive = Invoke-Validator -CaseRoot $root
    if ($positive.ExitCode -ne 0) {
        throw 'Positive test asset verification failed before negative tests.'
    }

    $isolatedPositiveRoot = New-CaseRoot -Name 'positive-isolated'
    $isolatedPositive = Invoke-Validator -CaseRoot $isolatedPositiveRoot
    if ($isolatedPositive.ExitCode -ne 0) {
        throw 'Unmodified isolated fixture copy failed before negative tests.'
    }
    $isolatedPositiveCase = 'PASS'

    Invoke-NegativeCase -Name 'missing-file' -Mutation {
        param($caseRoot)
        Remove-Item -LiteralPath (Join-Path $caseRoot 'tests/fixtures/invoice-i001-clear.png')
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'extra-file' -Mutation {
        param($caseRoot)
        [System.IO.File]::WriteAllBytes(
            (Join-Path $caseRoot 'tests/fixtures/unregistered.bin'),
            [byte[]](0x46, 0x49, 0x58, 0x54, 0x55, 0x52, 0x45)
        )
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'hash-drift' -Mutation {
        param($caseRoot)
        $path = Join-Path $caseRoot 'tests/fixtures/invoice-i001-clear.png'
        [byte[]]$bytes = [System.IO.File]::ReadAllBytes($path)
        $byteIndex = [int]($bytes.Count / 2)
        $bytes[$byteIndex] = $bytes[$byteIndex] -bxor 0x01
        [System.IO.File]::WriteAllBytes($path, $bytes)
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'size-drift' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = @($manifest.binary_assets | Where-Object { $_.id -ceq 'BIN-IMAGE-INVOICE-I001-CLEAR' })[0]
        $entry.size_bytes = [long]$entry.size_bytes + 1
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'repository-size-limit' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = @($manifest.binary_assets | Where-Object { $_.id -ceq 'BIN-IMAGE-INVOICE-I001-CLEAR' })[0]
        $entry.size_bytes = 1MB + 1
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'oversized-physical-file' -Mutation {
        param($caseRoot)
        $path = Join-Path $caseRoot 'tests/fixtures/invoice-i001-clear.png'
        $stream = [System.IO.FileStream]::new(
            $path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $stream.SetLength(1MB + 1)
        }
        finally {
            $stream.Dispose()
        }
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'signature-mismatch' -Mutation {
        param($caseRoot)
        Copy-Item -LiteralPath (Join-Path $caseRoot 'tests/fixtures/invoice-i002-blurred.jpg') `
            -Destination (Join-Path $caseRoot 'tests/fixtures/invoice-i001-clear.png') -Force
        Update-BinaryMetadata -CaseRoot $caseRoot -Id 'BIN-IMAGE-INVOICE-I001-CLEAR'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'docx-missing-core-part' -Mutation {
        param($caseRoot)
        $path = Join-Path $caseRoot 'tests/fixtures/contract-c002-complex.docx'
        $archive = [System.IO.Compression.ZipFile]::Open($path, [System.IO.Compression.ZipArchiveMode]::Update)
        try {
            $entry = $archive.GetEntry('word/document.xml')
            if ($null -eq $entry) {
                throw 'DOCX core part is already absent.'
            }
            $entry.Delete()
        }
        finally {
            $archive.Dispose()
        }
        Update-BinaryMetadata -CaseRoot $caseRoot -Id 'BIN-DOCX-COMPLEX-C002'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'path-traversal' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = @($manifest.binary_assets | Where-Object { $_.id -ceq 'BIN-PDF-TEXT-P001-V2' })[0]
        $entry.file = '../outside.pdf'
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'traceability-drift' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = @($manifest.binary_assets | Where-Object { $_.id -ceq 'BIN-PDF-TEXT-P001-V2' })[0]
        $entry.related_fixture_ids = @('C-002')
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'malformed-declared-valid' -Mutation {
        param($caseRoot)
        Copy-Item -LiteralPath (Join-Path $caseRoot 'tests/fixtures/pdf-damaged.pdf') `
            -Destination (Join-Path $caseRoot 'tests/fixtures/policy-p001-v2-text.pdf') -Force
        Update-BinaryMetadata -CaseRoot $caseRoot -Id 'BIN-PDF-TEXT-P001-V2'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'unknown-manifest-field' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $manifest.binary_assets[0] | Add-Member -NotePropertyName 'ignored_field' -NotePropertyValue 'not-allowed'
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'matrix-p0-task-set-drift' -Mutation {
        param($caseRoot)
        $matrixPath = Join-Path $caseRoot 'docs/testing/p0-traceability-matrix.csv'
        @(
            Get-Content -Encoding UTF8 -LiteralPath $matrixPath |
                Where-Object { $_ -notmatch '^TEST-001,' }
        ) | Set-Content -Encoding UTF8 -LiteralPath $matrixPath
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'matrix-column-width-drift' -Mutation {
        param($caseRoot)
        $matrixPath = Join-Path $caseRoot 'docs/testing/p0-traceability-matrix.csv'
        $matrixLines = @(Get-Content -Encoding UTF8 -LiteralPath $matrixPath)
        $targetIndexes = @(
            0..($matrixLines.Count - 1) | Where-Object { $matrixLines[$_] -match '^AI-002,' }
        )
        if ($targetIndexes.Count -ne 1) {
            throw 'Matrix width mutation target is not unique.'
        }
        $matrixLines[$targetIndexes[0]] += ',unexpected-extra-column'
        $matrixLines | Set-Content -Encoding UTF8 -LiteralPath $matrixPath
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'manifest-collection-drift' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $manifest.items = @($manifest.items | Select-Object -Skip 1)
        $manifest.binary_assets = @($manifest.binary_assets | Select-Object -Skip 1)
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'dataset-version-drift' -Mutation {
        param($caseRoot)
        $accountsPath = Join-Path $caseRoot 'tests/fixtures/accounts.json'
        $accounts = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountsPath | ConvertFrom-Json
        $accounts.dataset_version = 'TEST-DATASET-VERSION-DRIFT'
        $accounts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $accountsPath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-ACCOUNTS'

        $manifest = Read-Manifest -CaseRoot $caseRoot
        $manifest.dataset_version = 'TEST-DATASET-VERSION-DRIFT'
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'binary-contract-version-drift' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $manifest.binary_fixture_contract_version = 'TEST-BINARY-CONTRACT-VERSION-DRIFT'
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'boolean-type-drift' -Mutation {
        param($caseRoot)
        $accountsPath = Join-Path $caseRoot 'tests/fixtures/accounts.json'
        $accounts = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountsPath | ConvertFrom-Json
        $accounts.synthetic = 'True'
        $breakGlass = @($accounts.items | Where-Object { $_.id -ceq 'ACC-BREAK-GLASS' })[0]
        $breakGlass.independent_approval_record_required = 'True'
        $accounts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $accountsPath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-ACCOUNTS'

        $manifest = Read-Manifest -CaseRoot $caseRoot
        $manifest.synthetic = 'True'
        $manifest.binary_assets[0].synthetic = 'True'
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'binary-contract-type-drift' -Mutation {
        param($caseRoot)
        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = $manifest.binary_assets[0]
        $entry.size_bytes = [string]$entry.size_bytes
        $entry.related_fixture_ids = [string]$entry.related_fixture_ids[0]
        $entry.task_ids = [string]$entry.task_ids[0]
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'account-role-drift' -Mutation {
        param($caseRoot)
        $accountsPath = Join-Path $caseRoot 'tests/fixtures/accounts.json'
        $accounts = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountsPath | ConvertFrom-Json
        $account = @($accounts.items | Where-Object { $_.id -ceq 'ACC-CONTRACT-ADMIN' })[0]
        $account.role = 'read_only'
        $accounts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $accountsPath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-ACCOUNTS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'account-boundary-drift' -Mutation {
        param($caseRoot)
        $accountsPath = Join-Path $caseRoot 'tests/fixtures/accounts.json'
        $accounts = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountsPath | ConvertFrom-Json
        $account = @($accounts.items | Where-Object { $_.id -ceq 'ACC-SYSTEM-ADMIN' })[0]
        $account.expected_boundary = 'may_change_business_facts_and_finalize_high_risk'
        $financeAccount = @(
            $accounts.items | Where-Object { $_.id -ceq 'ACC-FINANCE-REVIEWER' }
        )[0]
        $lockedAccount = @($accounts.items | Where-Object { $_.id -ceq 'ACC-LOCKED' })[0]
        $financeAccount.state = 'locked'
        $lockedAccount.state = 'active'
        $accounts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $accountsPath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-ACCOUNTS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'break-glass-state-drift' -Mutation {
        param($caseRoot)
        $accountsPath = Join-Path $caseRoot 'tests/fixtures/accounts.json'
        $accounts = Get-Content -Raw -Encoding UTF8 -LiteralPath $accountsPath | ConvertFrom-Json
        $account = @($accounts.items | Where-Object { $_.id -ceq 'ACC-BREAK-GLASS' })[0]
        $account.state = 'active'
        $accounts | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $accountsPath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-ACCOUNTS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'core-business-c001-amount-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        @($fixture.items | Where-Object { $_.id -ceq 'C-001' })[0].amount = '99999.99'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'core-party-names-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $contract = @($fixture.items | Where-Object { $_.id -ceq 'C-001' })[0]
        $contract | Add-Member -NotePropertyName 'party_a_name' -NotePropertyValue 'not-the-request-party-a' -Force
        $contract | Add-Member -NotePropertyName 'party_b_name' -NotePropertyValue 'not-the-request-party-b' -Force
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'core-business-duplicate-tuple-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        @($fixture.items | Where-Object { $_.id -ceq 'I-001-DUP' })[0].invoice_number = '00000009'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'core-business-oversized-exception-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $construction = @(
            $fixture.items | Where-Object { $_.id -ceq 'CHUNK-OVERSIZED-CONTENT' }
        )[0].construction
        $construction.approved_table_exception = $true
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'policy-v2-name-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $policy = @($fixture.items | Where-Object { $_.id -ceq 'P-001-V2' })[0]
        $policy | Add-Member -NotePropertyName 'name' -NotePropertyValue 'not-the-request-name' -Force
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'policy-v2-clause-5-1-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/core_business.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $policy = @($fixture.items | Where-Object { $_.id -ceq 'P-001-V2' })[0]
        $clause = @($policy.clauses | Where-Object { $_.anchor -ceq '5.1' })
        if ($clause.Count -eq 0) {
            $policy.clauses = @($policy.clauses) + [pscustomobject]@{
                anchor = '5.1'
                page = 4
                text = 'not-the-request-clause'
            }
        }
        else {
            $clause[0].text = 'not-the-request-clause'
        }
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-CORE-BUSINESS'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-category-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        foreach ($id in @(
            'NEG-DIRECT-PROMPT-INJECTION',
            'NEG-PROMPT-INJECTION',
            'NEG-HIDDEN-MARKUP-INSTRUCTION'
        )) {
            @($fixture.items | Where-Object { $_.id -ceq $id })[0].category = 'no_answer'
        }
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-id-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-DIRECT-PROMPT-INJECTION' }
        )[0].id = 'NEG-DIRECT-PROMPT-INJECTION-DRIFT'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8

        $manifest = Read-Manifest -CaseRoot $caseRoot
        $entry = @(
            $manifest.items | Where-Object { $_.id -ceq 'DATASET-SECURITY-NEGATIVE' }
        )[0]
        $entry.required_ids = @(
            $entry.required_ids | ForEach-Object {
                if ($_ -ceq 'NEG-DIRECT-PROMPT-INJECTION') {
                    'NEG-DIRECT-PROMPT-INJECTION-DRIFT'
                }
                else {
                    $_
                }
            }
        )
        Write-Manifest -CaseRoot $caseRoot -Manifest $manifest
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-forged-citation-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $expected = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-FORGED-CITATION' }
        )[0].expected
        $expected.accepted = $true
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-table-cell-role-override-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $item = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-TABLE-CELL-ROLE-OVERRIDE' }
        )[0]
        $item.input.location = 'paragraph'
        $item.input.cell_text = 'safe'
        $item.expected = 'unsafe'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-user-forged-candidate-id-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $item = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-USER-FORGED-CANDIDATE-ID' }
        )[0]
        $item.input.user_candidate_id = $item.input.authorized_candidate_ids[0]
        $item.expected = 'unsafe'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-scalar-contract-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        foreach ($id in @(
            'NEG-NO-ANSWER',
            'NEG-UNAUTHORIZED',
            'NEG-DIRECT-PROMPT-INJECTION',
            'NEG-PROMPT-INJECTION',
            'NEG-HIDDEN-MARKUP-INSTRUCTION',
            'NEG-CREDENTIAL-EXFILTRATION',
            'NEG-RULE-TAMPERING'
        )) {
            @($fixture.items | Where-Object { $_.id -ceq $id })[0].input = 'x'
        }
        foreach ($id in @(
            'NEG-DIRECT-PROMPT-INJECTION',
            'NEG-HIDDEN-MARKUP-INSTRUCTION'
        )) {
            @($fixture.items | Where-Object { $_.id -ceq $id })[0].expected = 'unsafe'
        }
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'security-structured-input-invalid' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/security_negative.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        $missingInput = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-MISSING-TARGET-FIELD' }
        )[0].input
        $missingInput.target_field = ''
        $missingInput.document_text = ''
        $conflictInput = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-CONFLICTING-AMOUNTS' }
        )[0].input
        $conflictInput.evidence_candidates = @('100.00', '100.00')
        $forgedInput = @(
            $fixture.items | Where-Object { $_.id -ceq 'NEG-FORGED-CITATION' }
        )[0].input
        $forgedInput.model_candidate_id = $forgedInput.allowed_candidate_ids[0]
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-SECURITY-NEGATIVE'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'retrieval-label-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/retrieval_ret_001.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        @($fixture.items | Where-Object { $_.id -ceq 'RET-001-01' })[0].label = 'no_answer'
        @($fixture.items | Where-Object { $_.id -ceq 'RET-001-04' })[0].label = 'answerable'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-RETRIEVAL-RET-001'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'retrieval-fixed-baseline-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/retrieval_ret_001.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        foreach ($item in @($fixture.items)) {
            $item.question = 'not-the-request-question'
            if ($item.label -ceq 'answerable') {
                $item.expected_policy_version = 'P-999-V9'
                $item.expected_anchor = '9.9'
                $item.expected_top_k = 999
            }
        }
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-RETRIEVAL-RET-001'
    }
    $negativeCaseCount++

    Invoke-NegativeCase -Name 'retrieval-top-k-type-drift' -Mutation {
        param($caseRoot)
        $fixturePath = Join-Path $caseRoot 'tests/fixtures/retrieval_ret_001.json'
        $fixture = Get-Content -Raw -Encoding UTF8 -LiteralPath $fixturePath | ConvertFrom-Json
        @($fixture.items | Where-Object { $_.id -ceq 'RET-001-01' })[0].expected_top_k = '5'
        $fixture | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        Update-DatasetHash -CaseRoot $caseRoot -Id 'DATASET-RETRIEVAL-RET-001'
    }
    $negativeCaseCount++

    $junctionRoot = New-CaseRoot -Name 'reparse-directory'
    $junctionPath = Join-Path $junctionRoot 'tests/fixtures'
    $junctionTargetPath = Join-Path $junctionRoot 'tests/fixtures-target'
    Move-Item -LiteralPath $junctionPath -Destination $junctionTargetPath
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionTargetPath -ErrorAction Stop | Out-Null
    try {
        $junctionResult = Invoke-Validator -CaseRoot $junctionRoot
        if ($junctionResult.ExitCode -eq 0) {
            throw 'Directory reparse-point negative test unexpectedly passed.'
        }
        if (($junctionResult.Output -join [System.Environment]::NewLine) -notmatch 'must not be a reparse point\.') {
            throw 'Directory reparse-point test failed through an unexpected branch.'
        }
        $directoryReparseCase = 'PASS'
        $negativeCaseCount++
    }
    finally {
        if (Test-Path -LiteralPath $junctionPath) {
            [System.IO.Directory]::Delete($junctionPath)
        }
    }

    $reparseRoot = New-CaseRoot -Name 'reparse-file'
    $linkPath = Join-Path $reparseRoot 'tests/fixtures/invoice-i001-clear.png'
    $targetPath = Join-Path $reparseRoot 'linked-invoice-i001-clear.png'
    Move-Item -LiteralPath $linkPath -Destination $targetPath
    $symlinkCreated = $false
    try {
        New-Item -ItemType SymbolicLink -Path $linkPath -Target $targetPath -ErrorAction Stop | Out-Null
        $symlinkCreated = $true
    }
    catch {
        if (
            $_.Exception -is [System.UnauthorizedAccessException] -or
            $_.FullyQualifiedErrorId -match 'PrivilegeNotHeld|UnauthorizedAccess|NotSupported'
        ) {
            $reparseCase = 'NOT_RUN'
        }
        else {
            throw
        }
    }
    if ($symlinkCreated) {
        $reparseResult = Invoke-Validator -CaseRoot $reparseRoot
        if ($reparseResult.ExitCode -eq 0) {
            throw 'Reparse-point negative test unexpectedly passed.'
        }
        if (($reparseResult.Output -join [System.Environment]::NewLine) -notmatch 'must not be a reparse point\.') {
            throw 'File reparse-point test failed through an unexpected branch.'
        }
        $reparseCase = 'PASS'
    }

    'TEST_ASSET_NEGATIVE_CASES=PASS'
    "NEGATIVE_CASES=$negativeCaseCount"
    "ISOLATED_POSITIVE_CASE=$isolatedPositiveCase"
    "DIRECTORY_REPARSE_CASE=$directoryReparseCase"
    "REPARSE_CASE=$reparseCase"
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
