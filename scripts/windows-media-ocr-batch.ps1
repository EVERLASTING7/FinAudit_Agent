param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-ExactPropertyNames {
    param([Parameter(Mandatory = $true)][object]$Value)

    return @($Value.PSObject.Properties.Name | Sort-Object)
}

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected
    )

    $actual = @(Get-ExactPropertyNames -Value $Value)
    $wanted = @($Expected | Sort-Object)
    if ($actual.Count -ne $wanted.Count -or (Compare-Object $actual $wanted)) {
        throw 'WINDOWS_MEDIA_OCR_MANIFEST_INVALID'
    }
}

$manifestFile = Get-Item -LiteralPath $ManifestPath
if ($manifestFile.Length -le 0 -or $manifestFile.Length -gt 1MB) {
    throw 'WINDOWS_MEDIA_OCR_MANIFEST_INVALID'
}
$manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-ExactProperties -Value $manifest -Expected @('schema_version', 'cases')
if ($manifest.schema_version -ne 'windows-media-ocr-batch-v1') {
    throw 'WINDOWS_MEDIA_OCR_MANIFEST_INVALID'
}
$cases = @($manifest.cases)
if ($cases.Count -lt 1 -or $cases.Count -gt 500) {
    throw 'WINDOWS_MEDIA_OCR_MANIFEST_INVALID'
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1
if ($null -eq $asTask) {
    throw 'WINDOWS_MEDIA_OCR_RUNTIME_UNAVAILABLE'
}

function Wait-WinRtOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)][type]$ResultType
    )

    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

$engines = @{}
$seenIds = @{}
$results = [System.Collections.Generic.List[object]]::new()
foreach ($case in $cases) {
    Assert-ExactProperties -Value $case -Expected @('case_id', 'input_path', 'language')
    if (
        $case.case_id -isnot [string] -or
        $case.case_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$' -or
        $seenIds.ContainsKey($case.case_id) -or
        $case.language -notin @('en-US', 'zh-Hans-CN') -or
        $case.input_path -isnot [string] -or
        -not [IO.Path]::IsPathRooted($case.input_path)
    ) {
        throw 'WINDOWS_MEDIA_OCR_MANIFEST_INVALID'
    }
    $seenIds[$case.case_id] = $true

    $inputFile = Get-Item -LiteralPath $case.input_path
    if ($inputFile.Length -le 0 -or $inputFile.Length -gt 50MB) {
        throw 'WINDOWS_MEDIA_OCR_INPUT_INVALID'
    }
    if ($inputFile.Extension.ToLowerInvariant() -notin @('.jpg', '.jpeg', '.png')) {
        throw 'WINDOWS_MEDIA_OCR_INPUT_INVALID'
    }

    $stream = $null
    $bitmap = $null
    try {
        if (-not $engines.ContainsKey($case.language)) {
            $language = [Windows.Globalization.Language]::new($case.language)
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
            if ($null -eq $engine) {
                throw 'WINDOWS_MEDIA_OCR_LANGUAGE_UNAVAILABLE'
            }
            $engines[$case.language] = $engine
        }
        $engine = $engines[$case.language]
        $file = Wait-WinRtOperation -Operation (
            [Windows.Storage.StorageFile]::GetFileFromPathAsync($inputFile.FullName)
        ) -ResultType ([Windows.Storage.StorageFile])
        $stream = Wait-WinRtOperation -Operation (
            $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        ) -ResultType ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Wait-WinRtOperation -Operation (
            [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        ) -ResultType ([Windows.Graphics.Imaging.BitmapDecoder])
        if (
            $decoder.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or
            $decoder.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
        ) {
            throw 'WINDOWS_MEDIA_OCR_IMAGE_DIMENSION_EXCEEDED'
        }
        $bitmap = Wait-WinRtOperation -Operation (
            $decoder.GetSoftwareBitmapAsync()
        ) -ResultType ([Windows.Graphics.Imaging.SoftwareBitmap])
        $recognized = Wait-WinRtOperation -Operation (
            $engine.RecognizeAsync($bitmap)
        ) -ResultType ([Windows.Media.Ocr.OcrResult])
        $lines = @($recognized.Lines | ForEach-Object { [string]$_.Text })
        $results.Add([pscustomobject]@{
            case_id = $case.case_id
            status = 'succeeded'
            failure_code = $null
            language = $engine.RecognizerLanguage.LanguageTag
            width = [int]$decoder.PixelWidth
            height = [int]$decoder.PixelHeight
            text = [string]$recognized.Text
            lines = $lines
        })
    }
    catch {
        $code = if ($_.Exception.Message -like 'WINDOWS_MEDIA_OCR_*') {
            $_.Exception.Message
        }
        else {
            'WINDOWS_MEDIA_OCR_EXECUTION_FAILED'
        }
        $results.Add([pscustomobject]@{
            case_id = $case.case_id
            status = 'failed'
            failure_code = $code
            language = $case.language
            width = $null
            height = $null
            text = $null
            lines = @()
        })
    }
    finally {
        if ($null -ne $bitmap) {
            $bitmap.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

$output = [pscustomobject]@{
    schema_version = 'windows-media-ocr-batch-result-v1'
    engine = 'windows-media-ocr'
    cases = @($results)
}
$json = $output | ConvertTo-Json -Depth 6 -Compress
[IO.File]::WriteAllText(
    [IO.Path]::GetFullPath($OutputPath),
    $json,
    [Text.UTF8Encoding]::new($false)
)
Write-Output "WINDOWS_MEDIA_OCR_BATCH=PASS cases=$($results.Count)"
