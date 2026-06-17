# Shoeless Joe's Cards & Collectibles — Master Project Overview

> **Single entry point.** Read this first, then jump to the per-repo entry doc for the area
> you're working in (linked under each repo below).
>
> _Last consolidated: 2026-06-16. This file supersedes the scattered "north star" / "repo map" /
> "don't use old Railway" sections that were previously repeated across ~6 handoff docs._

---

## The business

**Shoeless Joe's Cards & Collectibles** — sports cards & collectibles shop. Buy / sell / trade,
plus PSA (and other graders) submission processing for customers and for the shop's own inventory.

- **Established:** 1992 (brand). Tom Huber era 1997–2025; **Kevin & Dan Burke** (brothers) 2025–present.
- **Address:** 6123 Bridgetown Rd, **Cincinnati, OH 45248** (west side / Bridgetown).
- **Credibility:** PSA Authorized Grading Agent · Official Topps Dealer · Official Panini Dealer ·
  on eBay since 2001 · 1,000+ grading submissions.
- **Operator:** Kevin handles day-to-day — Shopify, PSA submissions, inventory, back-office automation.

Full shop content (hours, About, history, social handles) lives in **storefront `CONTENT.md`** — that
is the source of truth; update there first, then propagate.

---

## Canonical identifiers — use these exact values

| Item | Value |
|---|---|
| myshopify domain | `qebynk-b0.myshopify.com` |
| Public site | `shoelessjoescards.com` |
| Shopify location ID | `72115847233` |
| Shopify Admin API version (storefront / Apps Script) | `2024-10` |
| Vendor name (on products) | `Shoeless Joe's` |
| GitHub org | `shoelessjoes` |
| Local clone root (both machines) | `C:\Users\burke\Git2\` |
| Theme base | Ignite by Benchmark Themes, v2.5.2 |

### Common mistakes (these have actually bitten us)

- **The myshopify handle is `qebynk-b0`, a fixed internal string.** It is **NOT**
  `shoelessjoescards.myshopify.com` — that domain does not exist. (Appears wrong in the old product
  re-org recap.)
- **The shop is in Cincinnati, not Lima.** Any "Lima" reference is stale and already corrected in `CONTENT.md`.
- **Shopify Admin API token is server-side only** (Apps Script Script Property `SHOPIFY_TOKEN`).
  Never put it in the form HTML asset — that's a public theme file. A token leaked this way once and
  was rotated.

---

## Architecture — three repos

| Repo | Role | Status | Entry doc |
|---|---|---|---|
| **shoelessjoes-storefront** | Customer-facing Shopify theme (Ignite) + PSA grading form + Apps Script backend | Active — customer-facing work | `CLAUDE.md` → `HANDOFF.md` |
| **shoelessjoes-ops** | Node monorepo: Dealernet offer ingest, inbox poll, Shopify draft-order/order sync, Postgres, Remix admin, Zhongda vending | Migrated; local dev working | `AGENT_HANDOFF.md` |
| **shoelessjoes-supplier-py** | Python + Playwright: Dealernet **pricing-table** scrape, margin ranking, price alerts (Windows-scheduled) | Migrated from legacy | `PROJECT_STATE.md` |

**Legacy repos — archive on GitHub, do not delete, do not develop in:** `dealernet-shopify-ops`,
`shoeless-joes`, `supplier-price-dashboard`, `shopify`. The **old Railway Postgres** tied to the legacy
repo is a **dead URL** — do not point any `.env` at it (see ops `DATABASE_SETUP.md` / `RAILWAY_FRESH_START.md`).

---

## What each repo is doing right now

### Storefront
- **Done:** Repo scaffold (full Ignite theme + `docs/`, `apps-script/`, `scripts/`, `brand-assets/`).
  Brand foundation (logo files, Bebas Neue / Roboto / Roboto Mono fonts, navy/gold/cream color schemes).
  PSA submission form fully built (cadence gate, per-card $2 Prep / $3 Review add-ons, $2/card markup).
  Apps Script backend creates draft orders, logs to Sheets, sends confirmation email — **connection
  verified (test order #7670)**. Product re-org: 15 smart collections created, 647 products bulk-tagged
  via Matrixify, collections live.
- **Biggest gap:** Homepage. A liked mockup exists but was never assembled into the theme. Header/footer
  chrome and per-section brand schemes still pending.
- **Other pending:** logo SVG from designer; PSA form final go-live (real Apps Script URL into CONFIG +
  end-to-end test); graded-card product-page template; BGS/SGC/TAG forms.

### Ops
- **Working locally:** Docker Postgres + Prisma migrations; `ingest-offers` (23 lines / 17 offers →
  Postgres); `poll-messages`; `report-purchases`; `sync-offers` dry-run. Owner ran a **first live
  purchase `--execute`** ~2026-05-29 — **verify draft orders in Shopify Admin.**
- **Vending (Zhongda):** Phase 1–2 working; CSV import failure diagnosed (needs ≥3 data columns).
- **Not built:** vendor email-invoice ingest (Topps / Panini / GTS — Stream B); scan-to-receive workflow;
  mapping-overrides UI; scheduled jobs in cloud.

### Supplier-py
- Migrated from legacy `shoeless-joes`. Scheduler tasks registered; live alert batch test 10/10;
  pricing dry-runs validated (purchases 14/21 mapped, sales 10/15 mapped).
- **Pending:** re-verify `test-login`, re-register scheduled tasks on the active clone path.

---

## How the three fit together (target architecture)

The unifying goal is **one picture of everything coming in or on order**, so staff can
**scan UPC → receive → adjust Shopify inventory** without re-keying across systems.

```
Inbound sources                     Normalize + match                 Shopify + floor
─────────────────                   ──────────────────                ───────────────
Dealernet offers + inbox  ─┐                                          Draft orders / on-order
Vendor emails (Topps/      ─┼─►  ops: ingest / poll / parse  ─►  match │
  Panini/GTS)               │         │                          (UPC) │
Pricing-table alerts       ─┘         ▼                                ▼
  (supplier-py, optional)        Postgres (offers + inbound)    Inventory @ 72115847233
                                       ▲                                ▲
                          Shared SEALED-PRODUCT CATALOG EXPORT          │
                          (UPC + variant ID + cost/price/qty)    scan UPC → receive
```

**The linchpin / top cross-repo priority:** a **shared sealed-product catalog export** (UPC, variant ID,
price, cost, inventory, sealed-only filter). Both ops (purchase-sync UPC matching) and supplier-py
(pricing match) should consume the **same dataset** instead of each doing its own live full-catalog
fetch. Until it lands, both fall back to live Shopify lookups (works, slower).

---

## Cross-cutting rules & hard-won gotchas (deduped)

- **Secrets:** never commit. `.env` is gitignored; 1Password is the source of truth (see storefront
  `CREDENTIALS.md`). The ops worker uses a **separate** Admin token from the form's, so they rotate
  independently.
- **Repo → Shopify is one-directional.** Package from repo, upload to Shopify. **Never** paste export/
  theme zips back into the repo (this caused a 452-file mess once). `.gitignore` now ignores all `*.zip`.
- **Theme work targets the unpublished theme,** never the live one, until ready to publish.
- **PowerShell `Compress-Archive` writes backslash zip paths Shopify rejects** ("missing
  layout/theme.liquid"). Use `scripts/package-theme.ps1` (forces forward slashes) or zip via Explorer.
- **Two-machine workflow (home + shop PC):** pull before starting, commit + push before leaving.
- **Don't run `sync-offers sale --execute`** without explicit approval — it creates paid orders and
  decrements inventory.
- **Matrixify bulk tag imports:** use the `MERGE` command with `Handle, Tags Command, Tags` format so
  existing tags aren't overwritten.

---

## Doc index — where to find what

**Storefront**
- `CLAUDE.md` — master dev context (read first) · `HANDOFF.md` — done/pending + gotchas
- `BRAND.md` — colors/fonts/voice/logo · `CONTENT.md` — real shop copy (source of truth)
- `PSA_FORM.md` — form architecture · `PSA_PRICING.md` — authoritative tier pricing
- `DEPLOYMENT.md` — ship theme + Apps Script · `CREDENTIALS.md` — credential map (no secrets)
- `GRADED_CARDS.md` — graded-card product spec (SKU, metafields, title format, import workflows)
- `COLLECTIONS.md` — smart-collection GIDs, handles, tag-mapping logic

**Ops**
- `AGENT_HANDOFF.md` — master back-office handoff (all streams + priorities)
- `RUNBOOK.md` — purchase/sale job sequences + first-cutover steps
- `WORK_QUEUE.md` — operational dashboard/queue model
- `DEALERNET_OFFER_PAGE.md` — offer-page probe matrix · `VENDING_ZHONGDA.md` — Zhongda integration
- `DATABASE_SETUP.md` — local Docker Postgres · `RAILWAY_FRESH_START.md` — optional cloud deploy

**Supplier-py**
- `PROJECT_STATE.md` — canonical commands + last validation · `HANDOFF_CLAUDE.md` — agent intro

**Shared**
- `DEALERNET_STACK.md` — Python vs Node division of labor · `google-workspace-automation-starter.md` —
  Gmail invoice intake starter (pairs with ops Stream B)

---

## Consolidated open priorities

1. **Shared sealed-product catalog export** (cross-repo linchpin) — define format, sealed-only filter,
   scheduled refresh; wire both ops sync and supplier-py match to it.
2. **Storefront homepage** — assemble `index.json` from Ignite sections + header/footer chrome + brand schemes.
3. **Verify ops first live run** in Shopify Admin (draft orders, partial offers, case-qty skips).
4. **PSA form go-live** — real Apps Script URL into CONFIG, end-to-end test (tag + add-ons + Sheet + email).
5. **Vendor email-invoice ingest** (Topps / Panini / GTS) — Phase 1 Gmail→DB.
6. **Scan-to-receive workflow** — link inbound line → scan UPC → adjust Shopify inventory.
7. **In-Stock tag lifecycle automation** (Shopify Flow or scheduled Matrixify) + tag out-of-stock products.
