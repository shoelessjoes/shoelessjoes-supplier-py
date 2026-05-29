# Google Workspace Automation Starter (Shopify-Centric)

This is a practical starter to run:

- Gmail invoice intake -> Drive
- Raw invoice logging -> Google Sheets
- Normalized purchase queue -> Shopify draft PO flow

Use this as the baseline for VendorA first, then clone for other vendors/sites.

## 1) Suggested Google Sheet Tabs

Create one spreadsheet, e.g. `Shoeless_Automations`, with these tabs:

### `raw_email_invoices`

Headers:

`created_at | vendor | gmail_message_id | gmail_thread_id | email_from | email_subject | email_date | attachment_file_ids | notes | status`

Status examples:

- `raw_saved` (logged, waiting parse)
- `parsed` (normalized row created)
- `error`

### `normalized_purchases`

Headers:

`id | source | vendor | external_id | purchase_date | currency | subtotal | tax | shipping | total | line_items_json | raw_email_row_id | shopify_po_status | shopify_po_id | shopify_po_url | last_updated_at`

Status examples:

- `ready_for_po`
- `po_created`
- `error`

### `sku_mapping`

Headers:

`vendor | vendor_sku | vendor_description | shopify_sku | shopify_variant_id | notes`

### `shopify_po_log` (optional but recommended)

Headers:

`log_timestamp | vendor | external_id | normalized_purchase_id | shopify_po_id | shopify_po_url | status | message`

## 2) Apps Script Job (Gmail -> Drive -> raw_email_invoices)

Use `integrations/google_apps_script/log_vendor_invoices.gs`.

What it does:

- Reads Gmail messages in `Invoices/VendorA`
- Saves PDF attachments to Drive folder `VendorA_Invoices_Raw`
- Writes one row per new message in `raw_email_invoices`
- Avoids duplicates via `gmail_message_id`

## 3) Make Scenario Blueprint

### Scenario A: Parse raw invoice rows

1. Trigger: scheduled run (every 10-15 min)
2. Sheets: search `raw_email_invoices` where `status=raw_saved` and `vendor=VendorA`
3. Drive: fetch PDF by file ID
4. Parse PDF (Make parser or external parser service)
5. Write parsed record to `normalized_purchases` with `shopify_po_status=ready_for_po`
6. Update original `raw_email_invoices` row to `status=parsed`

### Scenario B: Create Shopify draft PO/order

1. Trigger: scheduled run
2. Sheets: search `normalized_purchases` where `shopify_po_status=ready_for_po`
3. Parse `line_items_json`
4. Resolve SKU mapping from `sku_mapping`
5. Create Shopify draft order (or PO flow, depending on your process)
6. Update `normalized_purchases` with `po_created`, IDs/URL
7. Append audit row in `shopify_po_log`

## 4) Security Notes

- Never place secrets in Sheets.
- Keep Shopify token + mailbox credentials in secure stores:
  - Apps Script Properties (`PropertiesService`) or
  - Make secure connections / secrets.
- Keep `.env` local for Python services and never commit it.

## 5) Next Evolution

After VendorA works, repeat the same pattern for:

- Dealernet purchases/sales collector
- Other vendor invoice inboxes
- PDF parser microservice (if parser complexity increases)

The same normalized schema should feed all sources.
