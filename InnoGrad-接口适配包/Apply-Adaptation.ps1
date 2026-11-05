param([string]$Target = 'D:\InnoGrad')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath $Target).Path
$items = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $items) {
    $destination = Join-Path $taskRoot $item.path
    $source = Join-Path (Join-Path $PSScriptRoot 'files') $item.path
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower() -ne $item.new_sha256) { throw "Package checksum mismatch: $($item.path)" }
    if ($null -ne $item.expected_sha256) {
        if (-not (Test-Path -LiteralPath $destination)) { throw "Missing original: $($item.path)" }
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLower() -ne $item.expected_sha256) { throw "File changed since validation: $($item.path). Review before applying." }
    } elseif (Test-Path -LiteralPath $destination) { throw "New file already exists: $($item.path)" }
}
$backupRoot = Join-Path $taskRoot ('backend\runtime\adaptation-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
foreach ($item in $items) {
    $destination = Join-Path $taskRoot $item.path
    if (Test-Path -LiteralPath $destination) {
        $backup = Join-Path $backupRoot $item.path
        New-Item -ItemType Directory -Force -Path (Split-Path $backup) | Out-Null
        Copy-Item -LiteralPath $destination -Destination $backup
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'files') $item.path) -Destination $destination
}
Write-Host "Applied. Originals backed up at $backupRoot"
Write-Host 'Restart the local API and Worker after reviewing the changes.'
