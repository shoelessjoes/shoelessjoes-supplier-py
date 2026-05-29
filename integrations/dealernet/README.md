# Dealernet Integration Starter

This folder is the handoff point for Dealernet collectors.

## Goal

Collect and normalize:

- Internal message events
- Purchases
- Sales

Then feed your existing Shopify-oriented automation.

## Inputs Needed From Browser DevTools

For each page type, capture:

1. row/list selector
2. field selectors (date, title, qty, price, status, tracking, detail URL)
3. pagination/filter controls
4. any hidden IDs in links/attributes

## Files in this folder

- `sheet_headers/dealernet_messages_raw.csv`
- `sheet_headers/dealernet_purchases_raw.csv`
- `sheet_headers/dealernet_sales_raw.csv`
- `sheet_headers/dealernet_events_normalized.csv`

These are header-only templates for Google Sheets or CSV staging.

## Suggested Collector Pattern

1. Login once with stored session
2. Visit source page
3. Parse rows
4. Upsert by external ID/hash
5. Mark rows `new` / `processed`
6. Save run log

## Implemented collectors (Node)

Playwright collectors, Postgres storage, and inbox classification live in **`shoelessjoes-ops`** (`packages/core/src/dealernet/`, worker jobs `ingest-offers`, `poll-messages`). See `docs/DEALERNET_STACK.md`.

## Optional Python collectors

If you need CSV-only staging without Postgres, add:

- `collect_dealernet_messages.py`
- `collect_dealernet_purchases.py`
- `collect_dealernet_sales.py`

Use the schemas above (include `unit_of_measure`, `case_qty_boxes` on offer lines for case expansion).
