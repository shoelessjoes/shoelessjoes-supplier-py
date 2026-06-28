"""Scrape Midwest Cards presell category listings; output rows with UPC + release date only."""

from __future__ import annotations



import argparse

import json

import re

import sys

from pathlib import Path

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse



from playwright.sync_api import sync_playwright



sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.midwest_browser import (  # noqa: E402

    DEFAULT_PROFILE_DIR,

    MWC_HOME,

    launch_midwest_context,

    wait_past_cloudflare,

)

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





def category_path_prefix(category_url: str) -> str:

    path = urlparse(category_url).path.strip("/")

    if not path:

        return "/"

    return f"/{path.split('/')[0]}/"





def listing_links_from_page(page, prefix: str) -> list[str]:

    links = page.evaluate(LISTING_LINKS_JS)

    filtered = [u for u in links if urlparse(u).path.startswith(prefix)]

    if filtered:

        return filtered

    return page.evaluate(

        """(prefix) => {

      const out = new Set();

      for (const a of document.querySelectorAll('a[href]')) {

        try {

          const u = new URL(a.href);

          if (!u.hostname.includes('midwestcards.com')) continue;

          if (!u.pathname.startsWith(prefix)) continue;

          if (!/\\/20\\d{2}-[a-z0-9-]+\\/$/i.test(u.pathname)) continue;

          out.add(u.origin + u.pathname);

        } catch {}

      }

      return [...out];

    }""",

        prefix,

    )





def collect_listing_urls(

    page,

    category_url: str,

    timeout_ms: int,

    max_pages: int,

    *,

    manual_cf: bool,

) -> list[str]:

    prefix = category_path_prefix(category_url)

    found: list[str] = []

    seen: set[str] = set()

    for page_num in range(1, max_pages + 1):

        url = category_url if page_num == 1 else with_page_param(category_url, page_num)

        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        if not wait_past_cloudflare(page, timeout_ms, manual=manual_cf, label=url):

            print(f"  Cloudflare blocked listing page: {url}", file=sys.stderr)

            break

        links = listing_links_from_page(page, prefix)

        new_links = [u for u in links if u not in seen]

        if not new_links:

            break

        for u in new_links:

            seen.add(u)

            found.append(u)

        page.wait_for_timeout(800)

    return found





def scrape_product_page(

    page,

    url: str,

    timeout_ms: int,

    *,

    manual_cf: bool,

) -> dict:

    last: dict = {"source_url": url, "error": "cloudflare", "upcs": []}

    for attempt in range(2):

        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        page.wait_for_timeout(3000 if attempt == 0 else 5000)

        if not wait_past_cloudflare(page, timeout_ms, manual=manual_cf, label=url):

            continue

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

    return last





def main() -> None:

    parser = argparse.ArgumentParser(description="Scrape Midwest presell categories (UPC + release date)")

    parser.add_argument(

        "--categories",

        default=",".join(PRESell_CATEGORY_URLS),

        help="Comma-separated presell category URLs",

    )

    parser.add_argument("--max-pages", type=int, default=5, help="Max listing pages per category")

    parser.add_argument("--max-products", type=int, default=0, help="Cap product detail fetches (0=all)")

    parser.add_argument(

        "--headed",

        action="store_true",

        help="Visible browser (required to pass Cloudflare on shop PC)",

    )

    parser.add_argument(

        "--manual-cf",

        action="store_true",

        help="When headed, wait for you to complete Cloudflare in the browser window",

    )

    parser.add_argument(

        "--browser-profile",

        default=str(DEFAULT_PROFILE_DIR),

        help="Persistent Chromium profile dir (keeps Cloudflare clearance between runs)",

    )

    parser.add_argument(

        "--channel",

        default="",

        help='Installed browser channel, e.g. "chrome" or "msedge" (often passes CF better than bundled Chromium)',

    )

    parser.add_argument("--no-warmup", action="store_true", help="Skip homepage visit before scraping")
    parser.add_argument(
        "--warmup-only",
        action="store_true",
        help="Only open homepage and wait for Cloudflare (saves cookies to profile, then exit)",
    )
    parser.add_argument("--timeout-ms", type=int, default=120_000)

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



    if not args.headed:

        print("Warning: headless mode often fails Cloudflare. Use --headed on the shop PC.", file=sys.stderr)



    manual_cf = args.manual_cf or args.headed
    cf_timeout_ms = max(args.timeout_ms, 300_000) if manual_cf else args.timeout_ms

    profile_dir = Path(args.browser_profile)

    channel = args.channel.strip() or None



    categories = [u.strip() for u in args.categories.split(",") if u.strip()]

    catalog = load_catalog_upcs(Path(args.catalog))

    print(f"Catalog UPCs loaded: {len(catalog)} (includes archived)", file=sys.stderr)

    print(f"Browser profile: {profile_dir}", file=sys.stderr)



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



    with sync_playwright() as p:

        context = launch_midwest_context(

            p,

            headed=args.headed,

            profile_dir=profile_dir,

            channel=channel,

        )

        page = context.pages[0] if context.pages else context.new_page()



        try:

            if not args.no_warmup:
                print(f"Warmup: {MWC_HOME}", file=sys.stderr)
                page.goto(MWC_HOME, wait_until="domcontentloaded", timeout=cf_timeout_ms)
                if not wait_past_cloudflare(page, cf_timeout_ms, manual=manual_cf, label="homepage"):
                    print(
                        "Cloudflare blocked homepage. Run warmup first:\n"
                        f"  {Path(__file__).resolve()} --warmup-only --headed --manual-cf --channel chrome",
                        file=sys.stderr,
                    )
                    context.close()
                    sys.exit(1)
                if args.warmup_only:
                    print("Warmup complete; profile saved.", file=sys.stderr)
                    return



            for cat in categories:

                print(f"Listing: {cat}", file=sys.stderr)

                urls = collect_listing_urls(

                    page,

                    cat,

                    args.timeout_ms,

                    args.max_pages,

                    manual_cf=manual_cf,

                )

                print(f"  {len(urls)} product URL(s)", file=sys.stderr)

                all_product_urls.extend(urls)



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

                row = scrape_product_page(page, url, args.timeout_ms, manual_cf=manual_cf)

                stats["scraped"] += 1

                if row.get("error"):

                    rows.append(row)

                    stats["errors"] += 1

                    page.wait_for_timeout(1500)

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

                page.wait_for_timeout(1500)

        finally:

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

