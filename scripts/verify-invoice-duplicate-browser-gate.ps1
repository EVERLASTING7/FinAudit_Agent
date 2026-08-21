[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 4173,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$PostgresImage = 'postgres:16-alpine'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$gate = Join-Path $PSScriptRoot 'verify-report-browser-gate.ps1'
& $gate -Port $Port -PostgresImage $PostgresImage -Mode InvoiceDuplicate |
    Tee-Object -Variable gateOutput
$gateOutput = @($gateOutput)

if ($gateOutput -cnotcontains 'INVOICE_DUPLICATE_BROWSER_GATE=PASS') {
    throw 'The invoice duplicate browser gate did not report PASS.'
}

$postgresImageIds = @(
    $gateOutput |
        Where-Object { $_ -cmatch '^POSTGRESQL_IMAGE_ID=sha256:[0-9a-f]{64}$' } |
        ForEach-Object { $_.Substring('POSTGRESQL_IMAGE_ID='.Length) }
)
if ($postgresImageIds.Count -ne 1) {
    throw 'The invoice duplicate browser gate did not report one PostgreSQL image identity.'
}

$evidencePath = Join-Path $projectRoot 'tests\evaluation\local-invoice-duplicate-browser-v1.json'
$evidence = Get-Content -Raw -LiteralPath $evidencePath | ConvertFrom-Json
$evidence.browser.surface = 'google_chrome_cdp'
$sourcePaths = [ordered]@{
    runner = 'backend\tests\manual_financial_read_browser.py'
    browser_runner = 'scripts\run-browser-gate.cjs'
    shared_wrapper = 'scripts\verify-report-browser-gate.ps1'
    entry_wrapper = 'scripts\verify-invoice-duplicate-browser-gate.ps1'
    frontend_view = 'frontend\src\views\InvoiceDetailView.vue'
}
foreach ($entry in $sourcePaths.GetEnumerator()) {
    $path = Join-Path $projectRoot $entry.Value
    $payload = [IO.File]::ReadAllBytes($path)
    $evidence.source_binding."$($entry.Key)_path" = $entry.Value.Replace('\', '/')
    $evidence.source_binding."$($entry.Key)_bytes" = $payload.Length
    $evidence.source_binding."$($entry.Key)_sha256" = (
        Get-FileHash -LiteralPath $path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}
$evidence.recorded_on = [DateTimeOffset]::Now.ToString('yyyy-MM-dd')
$evidence.runtime_identity.http_port = $Port
$evidence.runtime_identity.postgresql_image_id = $postgresImageIds[0]

$temporaryEvidencePath = "$evidencePath.$PID.tmp"
try {
    $json = $evidence | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText(
        $temporaryEvidencePath,
        $json + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporaryEvidencePath -Destination $evidencePath -Force
}
finally {
    Remove-Item -LiteralPath $temporaryEvidencePath -Force -ErrorAction SilentlyContinue
}

Write-Output 'INVOICE_DUPLICATE_BROWSER_EVIDENCE=UPDATED'
