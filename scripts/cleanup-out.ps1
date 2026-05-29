Param(
    [switch]$DryRun = $true
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repoRoot "out"

if (-not (Test-Path $outDir)) {
    Write-Host "No out directory found at: $outDir"
    exit 0
}

# Keep latest + canonical files used by current pipeline.
$keep = @(
    "supplier_daily.csv",
    "supplier_oos.csv",
    "supplier_weekly.csv",
    "shopify_variants.csv",
    "matches_daily.csv",
    "matches_oos.csv",
    "matches_weekly.csv",
    "supplier_full.csv",
    "matches_full.csv",
    "shopify_variants_full.csv",
    "dealernet_alert_state.json",
    "review"
)

$files = Get-ChildItem -Path $outDir -Force
$fileOnly = $files | Where-Object { -not $_.PSIsContainer }

# Keep latest in common families so we don't lose most recent experiments.
$familyPrefixes = @(
    "supplier_",
    "matches_",
    "shopify_variants_"
)
$familyKeeps = @{}
foreach ($prefix in $familyPrefixes) {
    $latest = $fileOnly |
        Where-Object { $_.Name -like "$prefix*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        $familyKeeps[$latest.Name] = $true
    }
}

$toDelete = @()

foreach ($f in $files) {
    if ($keep -contains $f.Name) { continue }
    if ($familyKeeps.ContainsKey($f.Name)) { continue }
    $toDelete += $f
}

if ($toDelete.Count -eq 0) {
    Write-Host "Nothing to clean in out/."
    exit 0
}

Write-Host "Cleanup mode: " -NoNewline
if ($DryRun) { Write-Host "DRY RUN" } else { Write-Host "EXECUTE" }
Write-Host ""
Write-Host "Will remove:"

foreach ($item in $toDelete | Sort-Object LastWriteTime) {
    Write-Host (" - {0}" -f $item.FullName)
}

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run complete. Re-run with -DryRun:`$false to actually delete."
    exit 0
}

foreach ($item in $toDelete) {
    if ($item.PSIsContainer) {
        Remove-Item -Path $item.FullName -Recurse -Force
    } else {
        Remove-Item -Path $item.FullName -Force
    }
}

Write-Host ""
Write-Host "Cleanup complete."

