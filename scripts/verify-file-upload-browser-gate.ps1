[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 4173,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$PostgresImage = 'postgres:16-alpine',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')]
    [string]$RedisImage = 'redis:7.4.9-alpine'
)

$ErrorActionPreference = 'Stop'
$gate = Join-Path $PSScriptRoot 'verify-report-browser-gate.ps1'
& $gate -Port $Port -PostgresImage $PostgresImage -Mode FileUpload -RedisImage $RedisImage
