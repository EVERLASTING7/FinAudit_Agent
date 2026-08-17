[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$BackendImage = 'finaudit-backend-local:dev',
    [switch]$RequireExcel,
    [string]$KeepArtifactsAt
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$validatorPath = Join-Path $PSScriptRoot 'verify_report_artifact_compatibility.py'
$runId = [Guid]::NewGuid().ToString('N')
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "FinAuditAgent\report-compat-$runId"
$artifactRoot = if ([string]::IsNullOrWhiteSpace($KeepArtifactsAt)) {
    $temporaryRoot
}
else {
    [IO.Path]::GetFullPath($KeepArtifactsAt)
}
$hostDirectory = Join-Path $artifactRoot 'host'
$containerDirectory = Join-Path $artifactRoot 'container'
$renderDirectory = Join-Path $artifactRoot 'rendered'
$removeArtifacts = [string]::IsNullOrWhiteSpace($KeepArtifactsAt)

function Invoke-Checked([scriptblock]$Command, [string]$FailureMessage) {
    $output = @(& $Command 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage`n$($output -join [Environment]::NewLine)"
    }
    $output
}

function Resolve-CachedImageId([string]$Image) {
    $output = @(docker image inspect $Image --format '{{.Id}}' 2>&1)
    if (
        $LASTEXITCODE -ne 0 -or
        $output.Count -ne 1 -or
        $output[0].Trim() -cnotmatch '^sha256:[0-9a-f]{64}$'
    ) {
        throw 'The requested Backend image is not available as one verified local image; this gate never pulls.'
    }
    $output[0].Trim()
}

function Resolve-PdfToPpmPath {
    $command = Get-Command pdftoppm -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        throw 'Poppler pdftoppm is unavailable.'
    }
    if ([IO.Path]::GetExtension($command.Source) -ieq '.exe') {
        return [IO.Path]::GetFullPath($command.Source)
    }
    $runtimeRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $command.Source) '..\..'))
    $bundledExecutable = Join-Path $runtimeRoot 'native\poppler\Library\bin\pdftoppm.exe'
    if (Test-Path -LiteralPath $bundledExecutable -PathType Leaf) {
        return [IO.Path]::GetFullPath($bundledExecutable)
    }
    return [IO.Path]::GetFullPath($command.Source)
}

function Test-ExcelWorkbook([string]$Path) {
    $excel = $null
    $workbook = $null
    $worksheets = $null
    try {
        $excel = New-Object -ComObject Excel.Application
        $excel.Visible = $false
        $excel.DisplayAlerts = $false
        $excel.EnableEvents = $false
        $excel.AskToUpdateLinks = $false
        $excel.AutomationSecurity = 3
        $worksheets = $excel.Workbooks
        $workbook = $worksheets.Open([IO.Path]::GetFullPath($Path), 0, $true)
        if ($workbook.ReadOnly -ne $true -or $workbook.Worksheets.Count -ne 3) {
            throw 'Excel did not open the workbook in the expected read-only shape.'
        }
        $names = @(
            for ($index = 1; $index -le $workbook.Worksheets.Count; $index++) {
                $sheet = $workbook.Worksheets.Item($index)
                try {
                    [string]$sheet.Name
                }
                finally {
                    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sheet)
                }
            }
        )
        if (($names -join '|') -cne 'Summary|Rules|Risks') {
            throw 'Excel reported an unexpected worksheet contract.'
        }
        $summary = $workbook.Worksheets.Item('Summary')
        $rules = $workbook.Worksheets.Item('Rules')
        $risks = $workbook.Worksheets.Item('Risks')
        try {
            if (
                [string]$summary.Cells.Item(1, 1).Text -cne 'field' -or
                [string]$summary.Cells.Item(1, 2).Text -cne 'value' -or
                [string]$rules.Cells.Item(1, 1).Text -cne 'rule_id' -or
                [string]$risks.Cells.Item(1, 1).Text -cne 'risk_id'
            ) {
                throw 'Excel did not expose the expected report cell values.'
            }
        }
        finally {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($summary)
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($rules)
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($risks)
        }
        $workbook.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
        $workbook = $null
    }
    finally {
        if ($null -ne $workbook) {
            try { $workbook.Close($false) } catch { }
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
        }
        if ($null -ne $worksheets) {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($worksheets)
        }
        if ($null -ne $excel) {
            try { $excel.Quit() } catch { }
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

function Render-Pdf([string]$PdfToPpmPath, [string]$Path, [string]$Prefix) {
    $output = @(& $PdfToPpmPath -png $Path $Prefix 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Poppler could not render the formal PDF.`n$($output -join [Environment]::NewLine)"
    }
    $pages = @(Get-ChildItem -LiteralPath (Split-Path -Parent $Prefix) -Filter "$(Split-Path -Leaf $Prefix)-*.png")
    if ($pages.Count -lt 1 -or @($pages | Where-Object Length -le 0).Count -ne 0) {
        throw 'Poppler did not produce non-empty page renders.'
    }
    $pages.Count
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'The Backend virtual environment is missing.'
    }
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is unavailable.'
    }
    $pdfToPpmPath = Resolve-PdfToPpmPath
    if (Test-Path -LiteralPath $artifactRoot) {
        throw 'The report compatibility artifact directory already exists.'
    }
    New-Item -ItemType Directory -Path $artifactRoot | Out-Null
    New-Item -ItemType Directory -Path $renderDirectory | Out-Null

    $env:PYTHONPATH = Join-Path $projectRoot 'backend'
    try {
        $hostOutput = Invoke-Checked {
            & $pythonPath $validatorPath generate $hostDirectory
        } 'Host report artifact generation failed.'
    }
    finally {
        Remove-Item -LiteralPath 'Env:PYTHONPATH' -ErrorAction SilentlyContinue
    }
    $hostInspection = ($hostOutput -join '') | ConvertFrom-Json

    $imageId = Resolve-CachedImageId $BackendImage
    $containerOutput = Invoke-Checked {
        docker run --pull never --rm --network none --read-only `
            --cap-drop ALL --security-opt no-new-privileges `
            --tmpfs /tmp:rw,noexec,nosuid,size=64m `
            --volume "${projectRoot}:/workspace:ro" `
            --volume "${artifactRoot}:/artifacts" `
            --entrypoint python $imageId `
            /workspace/scripts/verify_report_artifact_compatibility.py `
            generate /artifacts/container
    } 'Backend image report artifact generation failed.'
    $containerInspection = ($containerOutput -join '') | ConvertFrom-Json

    if (
        $hostInspection.schema_version -cne 'report-artifact-compatibility-v1' -or
        $containerInspection.schema_version -cne 'report-artifact-compatibility-v1' -or
        $hostInspection.pdf.text_sha256 -cne $containerInspection.pdf.text_sha256 -or
        $hostInspection.xlsx.content_sha256 -cne $containerInspection.xlsx.content_sha256
    ) {
        throw 'Host and Backend image report semantics differ.'
    }

    $hostPdfPages = Render-Pdf $pdfToPpmPath (Join-Path $hostDirectory 'formal-report.pdf') (Join-Path $renderDirectory 'host')
    $containerPdfPages = Render-Pdf $pdfToPpmPath (Join-Path $containerDirectory 'formal-report.pdf') (Join-Path $renderDirectory 'container')
    if ($hostPdfPages -ne $containerPdfPages -or $hostPdfPages -ne $hostInspection.pdf.page_count) {
        throw 'Host and Backend image PDF page counts differ.'
    }

    $excelType = [type]::GetTypeFromProgID('Excel.Application')
    if ($null -eq $excelType) {
        if ($RequireExcel) {
            throw 'Microsoft Excel is not registered on this host.'
        }
        Write-Output 'EXCEL_OPEN=NOT_RUN (Excel unavailable)'
    }
    else {
        Test-ExcelWorkbook (Join-Path $hostDirectory 'formal-risk-details.xlsx')
        Test-ExcelWorkbook (Join-Path $containerDirectory 'formal-risk-details.xlsx')
        Write-Output 'EXCEL_OPEN_HOST=PASS'
        Write-Output 'EXCEL_OPEN_CONTAINER=PASS'
    }

    $libreOffice = Get-Command soffice -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $libreOffice) {
        Write-Output 'LIBREOFFICE_OPEN=NOT_RUN (LibreOffice unavailable)'
    }
    else {
        Write-Output 'LIBREOFFICE_OPEN=NOT_RUN (no approved headless gate)'
    }
    Write-Output "BACKEND_IMAGE_ID=$imageId"
    Write-Output "HOST_PYTHON_VERSION=$($hostInspection.python_version)"
    Write-Output "CONTAINER_PYTHON_VERSION=$($containerInspection.python_version)"
    Write-Output "PDF_PAGE_COUNT=$hostPdfPages"
    Write-Output "PDF_BYTES_IDENTICAL=$($hostInspection.pdf.sha256 -ceq $containerInspection.pdf.sha256)"
    Write-Output "XLSX_BYTES_IDENTICAL=$($hostInspection.xlsx.sha256 -ceq $containerInspection.xlsx.sha256)"
    Write-Output 'REPORT_ARTIFACT_CROSS_IMAGE_SEMANTICS=PASS'
    Write-Output 'PDF_POPPLER_RENDER=PASS'
    Write-Output 'REPORT_ARTIFACT_COMPATIBILITY=PASS'
}
finally {
    if ($removeArtifacts -and (Test-Path -LiteralPath $artifactRoot)) {
        $resolvedRoot = [IO.Path]::GetFullPath($artifactRoot)
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $resolvedRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove a report artifact directory outside the system temp root.'
        }
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
