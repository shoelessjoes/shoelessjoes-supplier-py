# Handoff to Claude Code — Supplier / Pricing Pipeline

**Last updated:** 2026-06-16
> For the cross-repo overview, canonical IDs, and shared gotchas, read **`SHOELESS_JOES_MASTER.md`** first.
> Canonical commands + last validation state for this repo are in **`PROJECT_STATE.md`**.
> Master back-office handoff (Dealernet + vendor email + receiving): `../shoelessjoes-ops/docs/AGENT_HANDOFF.md`.

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
| Scheduled on shop PC | ✅ `scripts/register-scheduled-tasks.ps1` | Local or future Railway |

Full division of labor: `../shared/DEALERNET_STACK.md`.

---

## Owner direction for Claude

1. **Shared Shopify catalog** — export all **sealed product** with UPC, variant ID, price, cost,
   inventory. Both ops (draft-PO UPC match) and this repo (pricing-scrape match) should use the **same
   dataset**, not independent live fetches.
2. **Pricing workflow** — owner wants to evaluate Claude's existing Shopify integration vs maintaining
   this Python REST client (`src/shopify_client.py`). Pick one; avoid duplicate logic.
3. **Purchases** — day-to-day buying is still manual at the shop. Automation priority is ops-side
   (ingest + UPC match + tracking), not the pricing-table scrape.
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

Canonical commands + validation state: `PROJECT_STATE.md`. Stack overview: `../shared/DEALERNET_STACK.md`.

---

## Legacy sources (reference only)

- `C:\Users\burke\Git\shoeless-joes` — branch `commit-changes` may have Claude WIP
- `dealernet-shopify-ops.zip` — identical to the ported ops monorepo (not a different iteration)

> Legacy repos are archive-only; the old Railway DB URL is dead. See `SHOELESS_JOES_MASTER.md`.
