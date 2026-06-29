# Start real Chrome for Midwest Cards scraping (pass Cloudflare manually, then attach scraper).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\burke\Git2\shoelessjoes-supplier-py\scripts\launch-chrome-for-midwest.ps1
#
# Leave this Chrome window open. Run scrape with --cdp-url http://127.0.0.1:9222

$ErrorActionPreference = "Stop"

$ProfileDir = "C:\Users\burke\Git2\shoelessjoes-supplier-py\out\mwc-browser-profile"
$CdpPort    = 9222
$StartUrl   = "https://www.midwestcards.com/"

$ChromeCandidates = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$Chrome = $ChromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) {
    throw "Google Chrome not found. Install Chrome or use Edge with a matching launch script."
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

Write-Host "Starting Chrome (NOT Playwright-controlled):" -ForegroundColor Cyan
Write-Host "  Profile: $ProfileDir"
Write-Host "  CDP:     http://127.0.0.1:$CdpPort"
Write-Host ""
Write-Host "1) Pass Cloudflare in the Chrome window (checkbox should stick)."
Write-Host "2) Confirm you see the normal Midwest Cards site."
Write-Host "3) Leave Chrome OPEN and run the scraper with --cdp-url http://127.0.0.1:$CdpPort"
Write-Host ""

Start-Process -FilePath $Chrome -ArgumentList @(
    "--remote-debugging-port=$CdpPort",
    "--user-data-dir=$ProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    $StartUrl
)
