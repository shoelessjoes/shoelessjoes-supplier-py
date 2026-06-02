# Handoff to Claude Code — Supplier / Pricing Pipeline

**Last updated:** 2026-05-29  
**Master handoff (Dealernet + vendor email + receiving):** `../../shoelessjoes-ops/docs/AGENT_HANDOFF.md`

---

## This repo (`shoelessjoes-supplier-py`)

Python + Playwright pipeline ported from legacy `C:\Users\burke\Git\shoeless-joes`. Runs on **Windows** via Task Scheduler.

| Command | Purpose |
|---------|---------|
| `test-login` | DealerNet login check |
| `run-profile` / `run-profile-review` | Scrape pricing table → Shopify fetch → match → ranked report |
| `add-alerts` | Submit price alerts on DealerNet |
| `sync-dealernet-shopify` | CSV offers → Shopify draft orders / orders (overlap with ops) |

Configs: `configs/dealernetx.{daily,oos,weekly}.yaml`

---

## Relationship to `shoelessjoes-ops`

| Concern | Use this repo (Python) | Use ops (Node) |
|---------|------------------------|----------------|
| DealerNet **pricing table** / margin ranking | ✅ | — |
| DealerNet **offer lists** (purchases/sales) | CSV legacy | ✅ Postgres ingest |
| **Inbox / tracking messages** | — | ✅ poll-messages |
| **Purchase draft orders** (ACCEPTED offers) | CSV path only | ✅ sync-offers |
| Scheduled on shop PC | ✅ scripts/register-scheduled-tasks.ps1 | Local or future Railway |

---

## Owner direction for Claude

1. **Shared Shopify catalog** — Export all **sealed product** with UPC, variant ID, price, cost, inventory. Both ops (draft PO UPC match) and this repo (pricing scrape match) should use the **same dataset**, not independent live fetches.

2. **Pricing workflow** — Owner wants to evaluate **Claude’s existing Shopify integration** (legacy `shoeless-joes` / related branches) vs maintaining this Python REST client (`src/shopify_client.py`). Pick one; avoid duplicate logic.

3. **Purchases** — Day-to-day buying is still manual at the shop. Automation priority is ops-side (ingest + UPC match + tracking), not the pricing table scrape.

4. **Case lines** — `src/shopify_sync.py` supports `unit_of_measure` / `case_qty_boxes` (aligned with ops).

---

## Local setup

```powershell
cd C:\Users\burke\Git2\shoelessjoes-supplier-py
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env   # SUPPLIER_*, SHOPIFY_*
```

Canonical commands: `docs/PROJECT_STATE.md`, `scripts/quick-commands.ps1`

Stack overview: `docs/DEALERNET_STACK.md`

---

## Legacy sources (reference only)

- `C:\Users\burke\Git\shoeless-joes` — branch `commit-changes` may have Claude WIP
- `dealernet-shopify-ops.zip` — identical to ported ops monorepo (not a different iteration)
