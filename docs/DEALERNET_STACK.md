# Dealernet stack (Python + Node)

Two repos cover different layers. They complement each other; neither replaces the other.

## `shoelessjoes-supplier-py` (this repo)

**Python + Playwright** — pricing intelligence and scheduled scraping on Windows.

| Capability | CLI / module |
|------------|----------------|
| Login / supplier table scrape | `test-login`, `scrape-supplier`, profiles `daily` / `oos` / `weekly` |
| Shopify catalog fetch + UPC/title match | `fetch-shopify`, `match`, `run-profile-review` |
| Dealernet price alerts | `add-alerts` |
| CSV-based offer → Shopify sync | `sync-dealernet-shopify` (`src/shopify_sync.py`) |

Runs locally via Task Scheduler (`scripts/register-scheduled-tasks.ps1`).

## `shoelessjoes-ops` (Node monorepo)

**Remix app + Postgres workers** — production offer ingest, inbox, and automated sync.

| Job | Purpose |
|-----|---------|
| `job:ingest-offers` | Playwright collect purchases/sales into Postgres (`caseQtyBoxes`, `unitOfMeasure`) |
| `job:poll-messages` | Classify inbox + email digest |
| `job:sync-offers` | Accepted offers → Shopify draft orders / orders |
| `job:dealernet-cycle` | ingest → poll → auto-sync (Railway cron) |

Source: `dealernet-shopify-ops` / `dealernet-shopify-ops.zip` (same tree, commit `5f95a8d`).

## Overlap and division of labor

- **Node** owns live collectors, message classification, DB idempotency, and Railway deployment.
- **Python** owns supplier price tables, margin/priority ranking, review packs, and alert submission.
- **CSV sync** in Python is for dry-runs and legacy `out/dealernet_*_raw.csv` workflows; prefer Node `sync-offers` when Postgres is wired up.

Case-line handling (`unit_of_measure=case`, `case_qty_boxes`) is aligned between both codepaths: expand qty to boxes or skip the line if case size is unknown.

## Credentials

Use the same env names where possible (`DEALERNET_USERNAME`, `DEALERNET_PASSWORD`, `SHOPIFY_*`). See `.env.example` here and `apps/worker/.env.example` in ops.
