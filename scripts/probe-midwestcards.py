"""Probe Midwest Cards product pages (headed) and check UPCs against Shopify catalog."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.midwest_browser import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    launch_midwest_context,
    wait_past_cloudflare,
)
from src.utils import normalize_upc  # noqa: E402

DEFAULT_URLS = [
    "https://www.midwestcards.com/baseball-cards/2026-topps-series-2-baseball-mega-box/",
    "https://www.midwestcards.com/baseball-cards/2026-topps-series-2-baseball-mega-20-box-case/",
]

PAGE_EXTRACT_JS = """() => {
  const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
    .filter(Boolean);

  const upcs = new Set();
  const addUpc = (raw) => {
    if (!raw) return;
    const digits = String(raw).replace(/\\D/g, '');
    if (digits.length >= 8 && digits.length <= 14) upcs.add(digits);
  };

  for (const block of jsonLd) {
    const items = Array.isArray(block) ? block : [block];
    for (const item of items) {
      if (!item || typeof item !== 'object') continue;
      addUpc(item.gtin14 || item.gtin13 || item.gtin12 || item.gtin || item.sku);
      if (item.offers) {
        const offers = Array.isArray(item.offers) ? item.offers : [item.offers];
        for (const o of offers) addUpc(o?.gtin14 || o?.gtin13 || o?.gtin12 || o?.sku);
      }
    }
  }

  const body = document.body.innerText || '';
  for (const m of body.matchAll(/(?:UPC|Barcode|GTIN)[\\s:#]*([0-9]{8,14})/gi)) {
    addUpc(m[1]);
  }

  const specs = [...document.querySelectorAll('table, dl, .productView-info, [class*="specification"]')]
    .map(el => el.innerText)
    .join('\\n');
  for (const m of specs.matchAll(/(?:UPC|Barcode|GTIN)[\\s:#]*([0-9]{8,14})/gi)) {
    addUpc(m[1]);
  }

  const unitLinks = [...document.querySelectorAll('a')]
    .map(a => ({ text: (a.textContent || '').trim(), href: a.href }))
    .filter(x => /^(box|case|pack)$/i.test(x.text) && x.href.includes('midwestcards.com'));

  return {
    title: document.title,
    h1: document.querySelector('h1')?.textContent?.trim() || null,
    url: location.href,
    upcs: [...upcs],
    jsonLd,
    presale: /presale|pre-sale|pre order/i.test(body),
    inStock: /in stock/i.test(body),
    unitLinks,
    priceText: (document.querySelector('[data-product-price], .price, .productView-price')?.textContent || '').trim().slice(0, 80),
  };
}"""


def normalize_gtin(raw: str) -> Optional[str]:
    """GTIN-14 often prefixes UPC-A with 00."""
    u = normalize_upc(raw)
    if not u:
        return None
    if len(u) == 14 and u.startswith("00"):
        u = u[2:]
    if len(u) == 13 and u.startswith("0"):
        u = u[1:]
    return u if 8 <= len(u) <= 14 else None


def upcs_from_result(data: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in data.get("upcs") or []:
        u = normalize_gtin(str(raw))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def load_catalog_upcs(catalog_path: Path) -> dict[str, dict[str, str]]:
    """UPC -> {variantId, productTitle, status, sku}."""
    by_upc: dict[str, dict[str, str]] = {}
    if not catalog_path.is_file():
        return by_upc
    with catalog_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            upc = normalize_upc(row.get("barcode") or row.get("Barcode") or row.get("upc"))
            if not upc:
                continue
            by_upc[upc] = {
                "variantId": row.get("variantId") or row.get("variant_id") or "",
                "productTitle": row.get("productTitle") or row.get("product_title") or row.get("title") or "",
                "status": row.get("status") or "",
                "sku": row.get("sku") or "",
            }
    return by_upc


def scrape_product(
    page,
    url: str,
    timeout_ms: int,
    *,
    manual_cf: bool,
    retries: int = 2,
) -> dict[str, Any]:
    last: dict[str, Any] = {"url": url, "upcs": []}
    for attempt in range(retries):
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(3000 if attempt == 0 else 7000)
        if not wait_past_cloudflare(page, timeout_ms, manual=manual_cf, label=url):
            continue
        try:
            btn = page.get_by_role("button", name=re.compile(r"item specifications", re.I))
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(800)
        except Exception:
            pass
        data = page.evaluate(PAGE_EXTRACT_JS)
        data["url"] = url
        data["upcs"] = upcs_from_result(data)
        last = data
        return data
    last["error"] = "cloudflare_or_timeout"
    return last


def probe_urls(
    urls: list[str],
    headed: bool,
    timeout_ms: int,
    *,
    profile_dir: Path,
    channel: str | None,
    manual_cf: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        context = launch_midwest_context(
            p,
            headed=headed,
            profile_dir=profile_dir,
            channel=channel,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for url in urls:
                try:
                    results.append(
                        scrape_product(page, url, timeout_ms, manual_cf=manual_cf),
                    )
                    page.wait_for_timeout(1500)
                except Exception as e:
                    results.append({"url": url, "error": str(e), "upcs": []})
        finally:
            context.close()
    return results


def enrich_with_catalog(results: list[dict[str, Any]], catalog: dict[str, dict[str, str]]) -> None:
    for row in results:
        checks = []
        for upc in row.get("upcs") or []:
            hit = catalog.get(upc)
            checks.append(
                {
                    "upc": upc,
                    "in_catalog": hit is not None,
                    "productTitle": hit.get("productTitle") if hit else None,
                    "status": hit.get("status") if hit else None,
                    "variantId": hit.get("variantId") if hit else None,
                }
            )
        row["upc_catalog_check"] = checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Midwest Cards and check UPCs vs sealed catalog")
    parser.add_argument("urls", nargs="*", help="Product URLs (default: Series 2 mega box + case)")
    parser.add_argument("--headed", action="store_true", help="Visible browser (required to pass Cloudflare)")
    parser.add_argument("--manual-cf", action="store_true", help="Wait for manual Cloudflare verification")
    parser.add_argument("--browser-profile", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--channel", default="", help='e.g. "chrome" or "msedge"')
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parents[2] / "shoelessjoes-ops" / "data" / "sealed-catalog.csv"),
        help="Path to sealed-catalog.csv from job:export-catalog",
    )
    parser.add_argument("--timeout-ms", type=int, default=90_000)
    parser.add_argument("--json-out", help="Write full JSON results to this path")
    args = parser.parse_args()

    urls = args.urls or DEFAULT_URLS
    catalog_path = Path(args.catalog)
    catalog = load_catalog_upcs(catalog_path)

    print(f"Catalog: {catalog_path} ({len(catalog)} UPCs indexed)", file=sys.stderr)
    print(f"Probing {len(urls)} URL(s) headed={args.headed}...", file=sys.stderr)

    results = probe_urls(
        urls,
        headed=args.headed,
        timeout_ms=args.timeout_ms,
        profile_dir=Path(args.browser_profile),
        channel=args.channel.strip() or None,
        manual_cf=args.manual_cf or args.headed,
    )
    enrich_with_catalog(results, catalog)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}", file=sys.stderr)

    # Human summary
    print("\n=== Midwest Cards UPC probe ===\n")
    for row in results:
        if row.get("error"):
            print(f"FAIL {row['url']}\n  {row['error']}\n")
            continue
        print(f"{row.get('h1') or row.get('title')}")
        print(f"  URL: {row.get('url')}")
        print(f"  Presale: {row.get('presale')}  In stock: {row.get('inStock')}  Price: {row.get('priceText') or '—'}")
        if row.get("unitLinks"):
            print(f"  Unit links: {', '.join(u['text'] for u in row['unitLinks'])}")
        checks = row.get("upc_catalog_check") or []
        if not checks:
            print("  UPC: (none found on page - try Item Specifications or another unit link)")
        for c in checks:
            if c["in_catalog"]:
                print(f"  UPC {c['upc']}: ALREADY IN CATALOG - {c['productTitle']} ({c['status']})")
            else:
                print(f"  UPC {c['upc']}: NEW - safe to draft")
        print()

    new_count = sum(
        1 for row in results for c in (row.get("upc_catalog_check") or []) if not c["in_catalog"]
    )
    existing_count = sum(
        1 for row in results for c in (row.get("upc_catalog_check") or []) if c["in_catalog"]
    )
    print(f"Summary: {new_count} new UPC(s), {existing_count} already in catalog")


if __name__ == "__main__":
    main()
