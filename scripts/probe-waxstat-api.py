"""Find Waxstat waxtracker API + UPC on product pages."""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"

from playwright.sync_api import sync_playwright

WEEK_URL = "https://www.waxstat.com/release-dates/june-21-2026-june-27-2026"


def fetch_json(url: str) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def main() -> None:
    waxtracker: list[dict] = []
    product_links: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            u = resp.url
            if "/waxtracker/" in u:
                try:
                    body = resp.text()[:2000]
                except Exception:
                    body = ""
                waxtracker.append({"url": u, "status": resp.status, "body": body})

        page.on("response", on_response)
        page.goto(WEEK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(5000)

        for a in page.locator("a").all():
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()
            if "series 2" in text.lower() and "mega" in text.lower():
                product_links.append(href)
        browser.close()

    print("=== waxtracker XHR ===")
    for hit in waxtracker:
        print(hit["url"], hit["status"])
        if hit["body"].startswith("{"):
            print(hit["body"][:500])

    print("\n=== Series 2 mega links ===")
    for link in product_links[:5]:
        print(link)

    # Probe waxtracker endpoints discovered + common patterns
    paths = sorted({re.sub(r"\?.*", "", h["url"].replace("https://www.waxstat.com", "")) for h in waxtracker})
    guesses = [
        "/waxtracker/release_dates?start_date=2026-06-21&end_date=2026-06-27",
        "/waxtracker/release-dates?start_date=2026-06-21&end_date=2026-06-27",
        "/waxtracker/boxes?start_date=2026-06-21&end_date=2026-06-27",
        "/waxtracker/search?q=series+2+mega",
        "/waxtracker/search_boxes?q=887521164608",
    ]
    print("\n=== direct JSON probes ===")
    for path in paths + guesses:
        url = "https://www.waxstat.com" + path if path.startswith("/") else path
        if "initialize-filter" in url:
            continue
        try:
            status, data = fetch_json(url if url.startswith("http") else "https://www.waxstat.com" + path)
            snippet = json.dumps(data)[:400]
            print(f"OK {path} -> {snippet}")
        except urllib.error.HTTPError as e:
            print(f"{e.code} {path}")
        except Exception as e:
            print(f"ERR {path}: {e}")

    if product_links:
        slug = product_links[0]
        if slug.startswith("/"):
            slug = "https://www.waxstat.com" + slug
        print(f"\n=== product page {slug} ===")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            all_hits: list[str] = []
            page.on(
                "response",
                lambda resp: all_hits.append(f"{resp.status} {resp.url}") if "waxstat.com" in resp.url else None,
            )
            page.goto(slug, wait_until="networkidle", timeout=90_000)
            page.wait_for_timeout(4000)
            body = page.inner_text("body")
            upc_match = re.findall(r"\b\d{12,14}\b", body)
            print("waxstat responses:", [h for h in all_hits if "waxtracker" in h or "/boxes/" in h][:15])
            print("UPC-like in body:", upc_match[:5])
            idx = body.lower().find("upc")
            snippet = body[max(0, idx - 20) : idx + 80] if idx >= 0 else body[:600]
            print("body snippet:", snippet.encode("ascii", "replace").decode())
            # Search raw HTML for embedded product JSON
            html = page.content()
            for needle in ("887521164608", '"upc"', "gtin", "barcode"):
                print(f"html has {needle}:", needle.lower() in html.lower())
            m = re.search(r'"upc"\s*:\s*"([^"]+)"', html, re.I)
            if m:
                print("html upc field:", m.group(1))
            browser.close()


if __name__ == "__main__":
    main()
