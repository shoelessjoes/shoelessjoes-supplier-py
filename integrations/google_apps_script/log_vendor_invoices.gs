/**
 * Gmail -> Drive -> Google Sheet logger for vendor invoice emails.
 *
 * Sheet tab expected: raw_email_invoices
 * Required headers:
 * created_at | vendor | gmail_message_id | gmail_thread_id | email_from | email_subject |
 * email_date | attachment_file_ids | notes | status
 */

const RAW_SHEET_NAME = "raw_email_invoices";
const VENDOR_LABEL_NAME = "Invoices/VendorA";
const VENDOR_NAME = "VendorA";
const VENDOR_FOLDER_NAME = "VendorA_Invoices_Raw";

function logVendorAInvoices() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(RAW_SHEET_NAME);
  if (!sheet) {
    throw new Error(`Sheet '${RAW_SHEET_NAME}' not found.`);
  }

  const data = sheet.getDataRange().getValues();
  if (!data || data.length === 0) {
    throw new Error(`Sheet '${RAW_SHEET_NAME}' needs a header row first.`);
  }

  const header = data[0];
  const messageIdColIndex = header.indexOf("gmail_message_id");
  if (messageIdColIndex === -1) {
    throw new Error("Column 'gmail_message_id' not found.");
  }

  const existingIds = new Set();
  for (let i = 1; i < data.length; i++) {
    const id = data[i][messageIdColIndex];
    if (id) existingIds.add(String(id));
  }

  const label = GmailApp.getUserLabelByName(VENDOR_LABEL_NAME);
  if (!label) {
    Logger.log(`Label '${VENDOR_LABEL_NAME}' not found.`);
    return;
  }

  const threads = label.getThreads(0, 50);
  if (!threads || threads.length === 0) {
    Logger.log(`No threads found for label '${VENDOR_LABEL_NAME}'.`);
    return;
  }

  const folder = getOrCreateFolderByName(VENDOR_FOLDER_NAME);
  const rowsToAppend = [];

  threads.forEach((thread) => {
    const messages = thread.getMessages();
    messages.forEach((msg) => {
      const messageId = msg.getId();
      if (existingIds.has(messageId)) return;
      if (msg.isDraft()) return;

      const attachments = msg.getAttachments({
        includeInlineImages: false,
        includeAttachments: true,
      });

      const pdfFileIds = [];
      attachments.forEach((att) => {
        const contentType = (att.getContentType() || "").toLowerCase();
        const name = (att.getName() || "").toLowerCase();
        const isPdf = contentType.includes("pdf") || name.endsWith(".pdf");
        if (!isPdf) return;

        const file = folder.createFile(att);
        pdfFileIds.push(file.getId());
      });

      // Skip non-PDF messages for this flow.
      if (pdfFileIds.length === 0) return;

      rowsToAppend.push([
        new Date(), // created_at
        VENDOR_NAME, // vendor
        messageId, // gmail_message_id
        thread.getId(), // gmail_thread_id
        msg.getFrom(), // email_from
        msg.getSubject(), // email_subject
        msg.getDate(), // email_date
        pdfFileIds.join(","), // attachment_file_ids
        "", // notes
        "raw_saved", // status
      ]);
    });
  });

  if (rowsToAppend.length === 0) {
    Logger.log("No new invoice messages with PDF attachments.");
    return;
  }

  sheet
    .getRange(sheet.getLastRow() + 1, 1, rowsToAppend.length, rowsToAppend[0].length)
    .setValues(rowsToAppend);

  Logger.log(`Appended ${rowsToAppend.length} new invoice rows.`);
}

function getOrCreateFolderByName(name) {
  const folders = DriveApp.getFoldersByName(name);
  if (folders.hasNext()) {
    return folders.next();
  }
  return DriveApp.createFolder(name);
}
