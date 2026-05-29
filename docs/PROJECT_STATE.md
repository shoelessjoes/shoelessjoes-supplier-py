# Project State (Cross-PC Handoff)

Last updated: 2026-05-28

This file is the single handoff reference when switching between home/shop PCs.

## Current Goal

Run Dealernet + Shopify sync on schedule, rank opportunities, and submit Dealernet price alerts safely.

## Latest Validation (2026-04-27)

- Scheduler tasks registered: `SupplierDashboard-Daily`, `SupplierDashboard-OOS-Every2Days`, `SupplierDashboard-Weekly`.
- Live alert batch test succeeded: 10 attempted, 10 added, 0 rejected.
- Shopify sync dry-runs:
  - Purchases (`out/dealernet_purchases_raw.csv`): 21 offers seen, 14 mapped, 7 missing product.
  - Sales (`out/dealernet_sales_raw.csv`): 15 offers seen, 10 mapped, 5 missing product.

## Canonical Commands

Run from project root:

```powershell
Set-Location "C:\Users\burke\Git2\shoelessjoes-supplier-py"
```

Related: the Node/Prisma monorepo for Dealernet + Shopify workers lives at `C:\Users\burke\Git2\shoelessjoes-ops` (GitHub: `shoelessjoes/shoelessjoes-ops`). Legacy source: `C:\Users\burke\Git\dealernet-shopify-ops`.

### 1) Login check

```powershell
python -m src.main test-login --supplier-config configs/dealernetx.weekly.yaml
```

### 2) Full weekly pipeline + review outputs

```powershell
python -m src.main run-profile-review --profile weekly --min-bucket high --top-n 250
```

### 3) Daily / OOS runs

```powershell
python -m src.main run-profile --profile daily
python -m src.main run-profile --profile oos
```

### 4) Price alerts

Dry-run first:

```powershell
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --dry-run
```

Execute:

```powershell
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --execute
```

### 5) Register scheduler jobs (daily/oos/weekly)

```powershell
.\scripts\register-scheduled-tasks.ps1
```

With custom times:

```powershell
.\scripts\register-scheduled-tasks.ps1 -DailyTime "06:15" -OosTime "12:15" -WeeklyTime "07:30"
```

## Key Config Files

- `configs/dealernetx.daily.yaml`
- `configs/dealernetx.oos.yaml`
- `configs/dealernetx.weekly.yaml`

Profiles map to:

- `daily` -> `data/upcs_in_stock.csv`
- `oos` -> `data/upcs_out_of_stock.csv`
- `weekly` -> `data/upcs_all_barcodes.csv`

## Core Output Files

Keep these unless intentionally rotating:

- `out/supplier_daily.csv`
- `out/supplier_oos.csv`
- `out/supplier_weekly.csv`
- `out/shopify_variants.csv`
- `out/matches_daily.csv`
- `out/matches_oos.csv`
- `out/matches_weekly.csv`
- `out/review/review_priority.csv`
- `out/review/shopify_price_update_candidates.csv`
- `out/review/email_summary.html`

## Secrets + Multi-PC Notes

- Keep secrets only in local `.env` (never commit).
- `.env.example` is the template to copy on each machine.
- Use GitHub for code/state, not Google Drive for live DB files.
- Sync only reports/exports to Drive if desired (optional).

## Next Major Build Phases

1. Stabilize Dealernet price alert selectors/rules.
2. Cloud-hosted DB/dashboard for home + shop access.
3. Expand channels: eBay/Fanatics and order/email ingestion.
4. Add Dealernet inbox message ingestion to track shipment updates (`tracking_number`, status changes) for incoming shipment dashboard cards.

