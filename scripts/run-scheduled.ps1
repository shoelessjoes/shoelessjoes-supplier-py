param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("daily", "oos", "weekly")]
    [string]$Profile,

    [switch]$IncludeReview,
    [switch]$IncludeAlerts,
    [int]$AlertMax = 10,
    [string]$AlertMinBucket = "high",
    [string]$AlertActions = "restock_opportunity,margin_risk,lower_price,raise_price"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    "python"
)

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python") {
        try {
            $null = Get-Command python -ErrorAction Stop
            $pythonExe = "python"
            break
        } catch {
            continue
        }
    } elseif (Test-Path $candidate) {
        $pythonExe = $candidate
        break
    }
}

if (-not $pythonExe) {
    throw "Python not found. Create .venv or ensure python is on PATH."
}

Write-Host "[$(Get-Date -Format s)] Starting profile run: $Profile"
& $pythonExe -m src.main run-profile --profile $Profile

if ($LASTEXITCODE -ne 0) {
    throw "run-profile failed for profile=$Profile"
}

if ($IncludeReview) {
    Write-Host "[$(Get-Date -Format s)] Building review pack for profile: $Profile"
    & $pythonExe -m src.main build-review-pack --matches ("out/matches_{0}.csv" -f $Profile) --out-dir out/review --min-bucket high --top-n 250
    if ($LASTEXITCODE -ne 0) {
        throw "build-review-pack failed for profile=$Profile"
    }
}

if ($IncludeAlerts) {
    Write-Host "[$(Get-Date -Format s)] Executing Dealernet alerts for profile: $Profile (max=$AlertMax)"
    & $pythonExe -m src.main add-alerts --supplier-config ("configs/dealernetx.{0}.yaml" -f $Profile) --matches ("out/matches_{0}.csv" -f $Profile) --price-source suggested --min-priority-bucket $AlertMinBucket --actions $AlertActions --max-alerts $AlertMax --execute
    if ($LASTEXITCODE -ne 0) {
        throw "add-alerts failed for profile=$Profile"
    }
}

Write-Host "[$(Get-Date -Format s)] Scheduled run completed: $Profile"
