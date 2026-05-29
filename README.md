# Supplier → Shopify Price Checker

Logs into a password-protected supplier site, extracts pricing rows from a table page, pulls your Shopify catalog, then matches **UPC first** and **fuzzy title** as a fallback to produce a comparison report.

## What you get

- **Supplier extract**: normalized rows (`upc`, `title`, `supplier_high_buy`, `supplier_low_sell`, `supplier_price`, …)
- **Shopify extract**: products + variants (barcode/UPC, title, price, cost, inventory, sold 7/30/60d, product recency)
- **Match + report**:
  - Exact UPC matches
  - Fuzzy title matches when UPC is missing (configurable threshold)
  - Action hints (`raise_price`, `lower_price`, `restock_opportunity`, `margin_risk`, `hold`)
  - Priority ranking (`priority_score`, `priority_bucket`) so staff can triage first

## Setup (Windows PowerShell)

From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

## Configure

1. Copy `.env.example` to `.env` and set **`SUPPLIER_USERNAME`** and **`SUPPLIER_PASSWORD`** there. Do **not** put passwords in YAML; the config only names which env vars to read (`username_env` / `password_env`).
2. Copy `configs/dealernetx.example.yaml` to `configs/dealernetx.yaml` (or `configs/supplier.example.yaml` → `supplier.yaml`) and adjust selectors as needed.

### Dealernet Intake (Messages/Purchases/Sales)

Starter docs and sheet headers for the next ops phase are included:

- `docs/dealernet-intake-starter.md`
- `integrations/dealernet/README.md`
- `integrations/dealernet/sheet_headers/*.csv`

## Test login only

After `.env` and your supplier YAML are ready:

```powershell
python -m src.main test-login --supplier-config configs/dealernetx.yaml
```

If something fails, run with a visible browser:

```powershell
python -m src.main test-login --supplier-config configs/dealernetx.yaml --headed
```

## Run

Run the full pipeline (supplier scrape → shopify fetch → match → report):

```powershell
python -m src.main run --supplier-config configs/supplier.yaml --out-dir out
```

Copy/paste one-liner (weekly profile + review pack):

```powershell
python -m src.main run-profile-review --profile weekly --min-bucket high --top-n 250
```

You can run individual steps:

```powershell
python -m src.main scrape-supplier --supplier-config configs/supplier.yaml --out out/supplier.csv
python -m src.main fetch-shopify --out out/shopify_variants.csv
python -m src.main match --supplier out/supplier.csv --shopify out/shopify_variants.csv --out out/matches.csv
```

## Notes on “polite” scraping

This project is configured for low load by default:

- Single browser context
- Human-ish delays between actions
- No concurrent requests

You should still keep scrape frequency reasonable and respect the supplier’s terms.

### Scrapy vs this project

**Scrapy** is great for high-volume HTTP crawling with throttling and politeness built in. DealernetX here is driven by **login + browser UI** (forms, `submit()`, search, tables), so this repo uses **Playwright** for that session. You still control load via **`politeness`** settings in YAML and **how often** you schedule jobs—not by swapping in Scrapy alone.

### How often can we run UPC lookups?

There is no fixed “safe” number: it depends on **how many UPCs per run**, **delays**, and the site’s capacity. Practical approach:

- Prefer **off-peak** windows, **one browser at a time**, and **avoid overlapping** scheduled runs.
- If a full catalog pass is heavy, use **tiered lists** (below) so daily runs stay small.

### Tiered UPC lists from Shopify (inventory-aware)

Export three CSVs (column `upc`) for different schedules:

```powershell
python -m src.main export-upc-tiers --out-dir data
```

Writes:

| File | Meaning | Typical schedule |
|------|---------|------------------|
| `data/upcs_in_stock.csv` | Sum of **available** inventory &gt; 0 | Daily |
| `data/upcs_out_of_stock.csv` | Barcode in catalog, **available == 0** | Every other day |
| `data/upcs_all_barcodes.csv` | Every distinct barcode | Weekly full pass |

Point `upc_csv_path` in `configs/dealernetx.yaml` at the file for that job (or keep three YAML copies that only differ by `upc_csv_path`).

**Shopify app scopes:** `read_products`, `read_inventory`, and `read_orders` (for sold 7/30/60 day velocity).

### Ready-made Dealernet profiles

This repo now includes three schedule-ready configs so you do not need to edit `upc_csv_path` each run:

- `configs/dealernetx.daily.yaml` → `data/upcs_in_stock.csv`
- `configs/dealernetx.oos.yaml` → `data/upcs_out_of_stock.csv`
- `configs/dealernetx.weekly.yaml` → `data/upcs_all_barcodes.csv`

Run sequence for any profile:

```powershell
python -m src.main export-upc-tiers --out-dir data
python -m src.main scrape-supplier --supplier-config configs/dealernetx.daily.yaml --out out/supplier_daily.csv
python -m src.main fetch-shopify --out out/shopify_variants.csv
python -m src.main match --supplier out/supplier_daily.csv --shopify out/shopify_variants.csv --out out/matches_daily.csv
```

Swap `dealernetx.daily.yaml` for `dealernetx.oos.yaml` or `dealernetx.weekly.yaml` and update output filenames accordingly.

Or run one command:

```powershell
python -m src.main run-profile --profile daily
python -m src.main run-profile --profile oos
python -m src.main run-profile --profile weekly

# Run profile + generate manager review pack in one shot
python -m src.main run-profile-review --profile weekly --min-bucket high --top-n 250
```

Build a manager-friendly review pack (CSV + email-ready HTML with category grouping and color-coded priority):

```powershell
python -m src.main build-review-pack --matches out/matches_weekly_ranked.csv --out-dir out/review --min-bucket high --top-n 250
```

Outputs:

- `out/review/review_priority.csv` (team review list)
- `out/review/shopify_price_update_candidates.csv` (price-change candidates)
- `out/review/email_summary.html` (copy/paste into email body)

### Windows Task Scheduler (ready-to-use)

Register/update tasks on this machine:

```powershell
.\scripts\register-scheduled-tasks.ps1
```

Default tasks created:

- `SupplierDashboard-Daily` (daily) -> `run-profile --profile daily`
- `SupplierDashboard-OOS-Every2Days` (every 2 days) -> `run-profile --profile oos`
- `SupplierDashboard-Weekly` (weekly) -> `run-profile --profile weekly`, then review pack, then live alerts (`--max-alerts 10`)

Customize times when registering:

```powershell
.\scripts\register-scheduled-tasks.ps1 -DailyTime "06:15" -OosTime "12:15" -WeeklyTime "07:30"
```

Disable live weekly alerts in scheduler:

```powershell
.\scripts\register-scheduled-tasks.ps1 -SkipWeeklyAlerts
```

### Data-pull checklist (before price alerts)

1. `.env` has supplier + Shopify credentials; `test-login` works.
2. `dealernetx.yaml` has correct **category/year** `filter_actions` for the products you scrape.
3. `mapping` matches the box-price table headers; `table_selector` finds the captioned table.
4. `export-upc-tiers` runs; `data/upcs_*.csv` look right.
5. `scrape-supplier` produces `out/supplier.csv` with sensible rows; then `match` / `run` as needed.

### Price alert rules (recommended start)

Use `add-alerts` in dry-run mode first (default), then switch to execute once the planned count looks right.

```powershell
# 1) Plan alerts only (no submit)
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --dry-run

# 2) Execute same rules for real
python -m src.main add-alerts --supplier-config configs/dealernetx.weekly.yaml --matches out/matches_weekly_ranked_v2.csv --price-source suggested --min-priority-bucket high --actions restock_opportunity,margin_risk,lower_price,raise_price --max-alerts 150 --execute
```

Notes:

- `--price-source suggested` uses the matcher's computed target price.
- `--require-in-stock` can narrow to inventory > 0 if you only want active sellable rows.
- `--min-sold-30d` can reduce noise on slower SKUs.
- Keep `--max-alerts` capped while tuning.

### Quick copy/paste commands

Use `scripts/quick-commands.ps1` for ready-to-paste one-liners.

### Cross-PC handoff + output cleanup

- Handoff status lives in `docs/PROJECT_STATE.md`.
- Safe output cleanup script:

```powershell
# Preview only
.\scripts\cleanup-out.ps1

# Actually delete non-core out/ files
.\scripts\cleanup-out.ps1 -DryRun:$false
```

### Ops reminder

- Keep a follow-up task to review the vending site and sync costs/prices there after this alert flow is stable.

