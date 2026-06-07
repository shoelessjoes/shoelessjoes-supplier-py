# After scrape-supplier: match vs Shopify, sanity-check product_url, dry-run or post price alerts.
param(
    [string]$Profile = "daily",
    [string]$AlertType = "For Sale",
    [string]$PriceSource = "suggested",
    [string]$MinPriorityBucket = "high",
    [int]$MaxAlerts = 1,
    [switch]$Execute,
    [switch]$SkipMatch
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$config = "configs/dealernetx.$Profile.yaml"
$supplierCsv = "out/supplier_$Profile.csv"
$shopifyCsv = "out/shopify_variants.csv"
$matchesCsv = "out/matches_$Profile.csv"

if (-not (Test-Path $supplierCsv)) {
    throw "Missing $supplierCsv - run scrape-supplier first."
}
if (-not (Test-Path $shopifyCsv)) {
    throw "Missing $shopifyCsv - copy from ops export or run run-dealernet-pricing.ps1 from shoelessjoes-ops."
}
if (-not (Test-Path $config)) {
    throw "Missing config: $config"
}

if (-not $SkipMatch) {
    Write-Host "[$(Get-Date -Format s)] match: $supplierCsv -> $matchesCsv"
    & $python -m src.main match --supplier $supplierCsv --shopify $shopifyCsv --out $matchesCsv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "Sample product_url rows (supplier CSV):"
$withUrl = Import-Csv $supplierCsv | Where-Object { $_.product_url -and $_.product_url.Trim() }
$urlCount = @($withUrl).Count
$totalRows = @(Import-Csv $supplierCsv).Count
Write-Host "  $urlCount / $totalRows supplier rows have product_url"
$withUrl | Select-Object -First 3 upc, title, product_url | Format-Table -AutoSize

if ($urlCount -eq 0) {
    Write-Warning "No product_url values - re-run scrape-supplier (category sweep + listing URL enrichment)."
}

$alertArgs = @(
    "-m", "src.main", "add-alerts",
    "--supplier-config", $config,
    "--matches", $matchesCsv,
    "--alert-type", $AlertType,
    "--price-source", $PriceSource,
    "--min-priority-bucket", $MinPriorityBucket,
    "--max-alerts", "$MaxAlerts"
)
if ($Execute) {
    $alertArgs += "--execute"
} else {
    $alertArgs += "--dry-run"
}

Write-Host ""
Write-Host "[$(Get-Date -Format s)] add-alerts $(if ($Execute) { 'EXECUTE' } else { 'dry-run' }) (max=$MaxAlerts, type=$AlertType)"
& $python @alertArgs
exit $LASTEXITCODE
