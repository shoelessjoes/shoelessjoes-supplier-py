"""Scrape Midwest Cards presell category listings; output rows with UPC + release date only."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.midwestcards import (  # noqa: E402
    LISTING_LINKS_JS,
    PRESell_CATEGORY_URLS,
    PRODUCT_EXTRACT_JS,
    load_catalog_upcs,
    product_row_from_extract,
)
from src.utils import write_csv  # noqa: E402


def with_page_param(url: str, page_num: int) -> str:
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    q["page"] = str(page_num)
    return urlunparse(parsed._replace(query=urlencode(q)))


def wait_past_cloudflare(page, timeout_ms: int) -> bool:
    page.wait_for_timeout(2500)
    if "just a moment" not in (page.title() or "").lower():
        return True
    page.wait_for_timeout(min(timeout_ms, 12_000))
    return "just a moment" not in (page.title() or "").lower()


def category_path_prefix(category_url: str) -> str:
    path = urlparse(category_url).path.strip("/")
    if not path:
        return "/"
    return f"/{path.split('/')[0]}/"


def collect_listing_urls(
    page,
    category_url: str,
    timeout_ms: int,
    max_pages: int,
) -> list[str]:
    prefix = category_path_prefix(category_url)
    found: list[str] = []
    seen: set[str] = set()
    for page_num in range(1, max_pages + 1):
        url = category_url if page_num == 1 else with_page_param(category_url, page_num)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if not wait_past_cloudflare(page, timeout_ms):
            break
        links = page.evaluate(LISTING_LINKS_JS)
        new_links = [u for u in links if u not in seen and urlparse(u).path.startswith(prefix)]
        if not new_links:
            break
        for u in new_links:
            seen.add(u)
            found.append(u)
        page.wait_for_timeout(800)
    return found


def scrape_product_page(page, url: str, timeout_ms: int) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    if not wait_past_cloudflare(page, timeout_ms):
        return {"source_url": url, "error": "cloudflare", "upcs": []}
    try:
        btn = page.get_by_role("button", name=re.compile(r"item specifications", re.I))
        if btn.count() > 0:
            btn.first.click(timeout=3000)
            page.wait_for_timeout(600)
    except Exception:
        pass
    raw = page.evaluate(PRODUCT_EXTRACT_JS)
    row = product_row_from_extract(raw)
    row["source_list"] = "presell_category"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Midwest presell categories (UPC + release date)")
    parser.add_argument(
        "--categories",
        default=",".join(PRESell_CATEGORY_URLS),
        help="Comma-separated presell category URLs",
    )
    parser.add_argument("--max-pages", type=int, default=5, help="Max listing pages per category")
    parser.add_argument("--max-products", type=int, default=0, help="Cap product detail fetches (0=all)")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=90_000)
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parents[2] / "shoelessjoes-ops" / "data" / "sealed-catalog.csv"),
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "out" / "midwest_presells.csv"),
    )
    parser.add_argument("--json-out", default=str(Path(__file__).resolve().parents[1] / "out" / "midwest_presells.json"))
    args = parser.parse_args()

    categories = [u.strip() for u in args.categories.split(",") if u.strip()]
    catalog = load_catalog_upcs(Path(args.catalog))
    print(f"Catalog UPCs loaded: {len(catalog)} (includes archived)", file=sys.stderr)

    all_product_urls: list[str] = []
    rows: list[dict] = []
    stats = {
        "listing_urls": 0,
        "scraped": 0,
        "eligible": 0,
        "skipped_no_upc": 0,
        "skipped_no_release": 0,
        "skipped_case": 0,
        "skipped_in_catalog": 0,
        "errors": 0,
    }

    profile_dir = Path(__file__).resolve().parents[1] / "out" / "mwc-browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=not args.headed,
        )
        page = context.pages[0] if context.pages else context.new_page()

        for cat in categories:
            print(f"Listing: {cat}", file=sys.stderr)
            urls = collect_listing_urls(page, cat, args.timeout_ms, args.max_pages)
            print(f"  {len(urls)} product URL(s)", file=sys.stderr)
            all_product_urls.extend(urls)

        # Dedupe while preserving order
        seen: set[str] = set()
        product_urls = []
        for u in all_product_urls:
            if u in seen:
                continue
            seen.add(u)
            product_urls.append(u)
        stats["listing_urls"] = len(product_urls)

        if args.max_products > 0:
            product_urls = product_urls[: args.max_products]

        for i, url in enumerate(product_urls, 1):
            print(f"[{i}/{len(product_urls)}] {url}", file=sys.stderr)
            row = scrape_product_page(page, url, args.timeout_ms)
            stats["scraped"] += 1
            if row.get("error"):
                rows.append(row)
                stats["errors"] += 1
                page.wait_for_timeout(2500)
                continue

            upc = row.get("upc") or ""
            if row.get("is_case"):
                row["skip_reason"] = "case_unit"
                stats["skipped_case"] += 1
            elif not upc:
                row["skip_reason"] = "no_upc"
                stats["skipped_no_upc"] += 1
            elif not row.get("release_date"):
                row["skip_reason"] = "no_release_date"
                stats["skipped_no_release"] += 1
            elif upc in catalog:
                row["skip_reason"] = "in_catalog"
                row["catalog_match"] = catalog[upc].get("productTitle")
                row["catalog_status"] = catalog[upc].get("status")
                stats["skipped_in_catalog"] += 1
            else:
                row["skip_reason"] = ""
                row["import_action"] = "create_draft"
                stats["eligible"] += 1

            rows.append(row)
            page.wait_for_timeout(2500)

        context.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "title",
        "upc",
        "release_date",
        "release_date_raw",
        "manufacturer",
        "sport",
        "mwc_sku",
        "mwc_price",
        "image_url",
        "source_url",
        "source_list",
        "import_action",
        "skip_reason",
        "catalog_match",
        "catalog_status",
        "error",
    ]
    write_csv(out_path, rows, fieldnames)

    json_path = Path(args.json_out)
    json_path.write_text(json.dumps({"stats": stats, "rows": rows}, indent=2), encoding="utf-8")

    print("\n=== Midwest presell scrape ===", file=sys.stderr)
    print(json.dumps(stats, indent=2))
    print(f"\nWrote {out_path}")
    print(f"Eligible for draft import: {stats['eligible']}")


if __name__ == "__main__":
    main()
