# Google Apps Script Setup

## Script Included

- `log_vendor_invoices.gs` -> Gmail label (`Invoices/VendorA`) to Drive folder + `raw_email_invoices` sheet rows.

## Setup Steps

1. Create/open your Google Sheet (with `raw_email_invoices` tab and headers).
2. Open **Extensions -> Apps Script**.
3. Paste contents of `log_vendor_invoices.gs`.
4. Run `logVendorAInvoices` once to authorize Gmail/Drive/Sheets access.
5. Add Trigger:
   - Function: `logVendorAInvoices`
   - Event source: Time-driven
   - Frequency: every 10-15 minutes

## Expected Gmail Label

- `Invoices/VendorA`

Set a Gmail filter to auto-apply this label for VendorA invoice emails.

## Expected Sheet Columns

`created_at | vendor | gmail_message_id | gmail_thread_id | email_from | email_subject | email_date | attachment_file_ids | notes | status`

## Notes

- Duplicate protection uses `gmail_message_id`.
- Only PDF attachments are saved/logged in this flow.
- Extend by cloning constants/functions per vendor label.
