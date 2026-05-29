# shoelessjoes-supplier-py quick commands
# Copy/paste any single line below in PowerShell.

# Optional: run this first if you're not in the project folder.
Set-Location "C:\Users\burke\Git2\shoelessjoes-supplier-py"

# Login test
python -m src.main test-login --supplier-config configs/dealernetx.weekly.yaml

# Weekly full run + review outputs
python -m src.main run-profile-review --profile weekly --min-bucket high --top-n 250

# Daily profile run
python -m src.main run-profile --profile daily

# OOS profile run
python -m src.main run-profile --profile oos

# Register/update Task Scheduler jobs
.\scripts\register-scheduled-tasks.ps1

# Rebuild review pack from latest ranked file
python -m src.main build-review-pack --matches out/matches_weekly_ranked_v2.csv --out-dir out/review --min-bucket high --top-n 250

# Alerts dry-run (safe preview)
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --dry-run

# Alerts execute (real submit)
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --execute
