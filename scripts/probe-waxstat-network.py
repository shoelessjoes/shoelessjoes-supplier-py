"""Capture Waxstat XHR/fetch URLs via Playwright (headless)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else (
    "https://www.waxstat.com/release-dates/june-21-2026-june-27-2026"
)


def main() -> None:
    hits: list[dict] = []

    def on_response(resp):
        u = resp.url
        if "waxstat.com" in u and u != URL:
            try:
                body = resp.text()[:1200] if resp.ok else ""
            except Exception:
                body = ""
            hits.append({"url": u, "status": resp.status, "body": body})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", on_response)
        page.goto(URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(8000)
        title = page.title()
        cf = "just a moment" in title.lower()
        has_series2 = page.locator("text=Series 2").count()
        has_upc_col = page.locator("text=UPC").count()
        table_text = page.inner_text("body")
        browser.close()

    print(json.dumps({
        "page": URL,
        "title": title,
        "cloudflare_title": cf,
        "series2_mentions": has_series2,
        "upc_column": has_upc_col,
        "xhr_count": len(hits),
        "xhr": hits[:40],
        "body_has_series2": "Series 2" in table_text,
        "body_snippet": table_text[table_text.find("Series 2") - 100: table_text.find("Series 2") + 400] if "Series 2" in table_text else table_text[:1500],
    }, indent=2))


if __name__ == "__main__":
    main()
