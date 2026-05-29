# Dealernet Intake Starter (Messages + Purchases + Sales)

This starter defines a clean ingestion pattern for Dealernet events so they can feed:

- Shopify purchase-order/inventory receive flow
- Shopify sales/fulfillment flow
- Daily ops dashboard and exceptions queue

## Dealernet Source Pages

- Price alerts page: `priceAlert.php`
- Purchases: `offers.php?offerfilter=PURCHASESUNRATED`
- Sales: `offers.php?offerfilter=SALESUNRATED`
- Internal inbox/messages: message list + detail pages

## 1) Suggested Intake Tabs (Google Sheet or DB tables)

Use these as raw-stage tables first.

### `dealernet_messages_raw`

Headers:

`captured_at | message_id | message_datetime | subject | message_type | message_text | message_url | is_read | raw_html_hash | status | notes`

Status:

- `new`
- `processed`
- `error`

### `dealernet_purchases_raw`

Headers:

`captured_at | dealernet_event_id | event_datetime | counterparty | product_title | upc | qty | unit_price | total_price | offer_status | tracking_number | detail_url | raw_html_hash | status | notes`

### `dealernet_sales_raw`

Headers:

`captured_at | dealernet_event_id | event_datetime | counterparty | product_title | upc | qty | unit_price | total_price | offer_status | tracking_number | detail_url | raw_html_hash | status | notes`

## 2) Normalized Event Table

Create one normalized table your automations consume:

### `dealernet_events_normalized`

Headers:

`id | source | event_type | external_id | event_datetime | counterparty | title | upc | qty | unit_price | total_price | tracking_number | raw_ref | parse_confidence | shopify_action_status | shopify_reference_id | last_updated_at | error_message`

Recommended values:

- `event_type`: `message_alert`, `purchase`, `sale`
- `shopify_action_status`: `ready`, `queued`, `done`, `error`, `manual_review`
- `parse_confidence`: `0-100`

## 3) Mapping to Shopify Actions

### Purchase Event -> Inventory Receive / PO

When `event_type = purchase`:

- Match UPC/SKU to Shopify variant.
- If mapped, create/update purchase intake record.
- Mark `shopify_action_status=ready`.
- Downstream job can create draft PO/receiving record.

### Sale Event -> Order/Fulfillment Workflow

When `event_type = sale`:

- Match UPC/SKU to Shopify variant.
- Create order/fulfillment task with tracking.
- Ensure inventory deduction occurs in Shopify process.

### Message Event -> Notification Queue

When `event_type = message_alert`:

- Add to alert queue.
- Link to related purchase/sale if possible by ID/title.

## 4) Polling Plan

Start simple and stable:

- Inbox/messages every 10-15 minutes
- Purchases every 30 minutes
- Sales every 30 minutes
- Normalize + Shopify sync every 10 minutes

## 5) Idempotency Rules (Critical)

- Deduplicate by stable `external_id` when present.
- If no stable ID, dedupe by hash of key fields:
  - `event_datetime + title + counterparty + qty + total_price`
- Never create duplicate Shopify records if row already has `shopify_reference_id`.

## 6) Exceptions Queue

Rows must go to `manual_review` when:

- no UPC and no strong title match
- missing quantity/price
- contradictory status data
- tracking format invalid

## 7) Implementation Sequence

1. Build collector for messages page -> `dealernet_messages_raw`
2. Build collector for purchases/sales pages -> raw tabs
3. Build normalizer -> `dealernet_events_normalized`
4. Connect normalized rows to existing Shopify PO/sales handlers
5. Add review output in daily dashboard/email summary

## 8) Security + Operational Notes

- Keep Dealernet credentials in `.env` only.
- Respect site terms and keep polite scrape intervals.
- Do not run concurrent collectors against same pages.
- Persist last successful run timestamp per collector.
