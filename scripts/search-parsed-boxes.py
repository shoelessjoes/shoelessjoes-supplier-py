"""
Look up parsed box inventory on Dealernet via search.php keyword search.

Reads data/parsed_boxes_formatted.csv (search_query column), runs each unique query
against Dealernet, picks the best search result, and scrapes Current High Buy /
Current Low Sell from the product price guide page.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_supplier_config
from src.dealernet_search import (
    canonical_key,
    lookup_key_for_input,
    resolve_on_page,
)
from src.supplier_scraper import _get_supplier_credentials, _login
from src.utils import ensure_parent_dir

# Re-export for backwards compatibility with any external imports.
from src.dealernet_search import (  # noqa: F401
    SearchResult,
    parse_search_results,
    pick_best_result,
    scrape_priceguide,
    search_url,
)


def load_resume_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        prev = pd.read_csv(path)
    except Exception:
        return set()
    if "search_query" not in prev.columns or "search_status" not in prev.columns:
        return set()
    ok = prev[prev["search_status"] == "ok"]
    return set(ok["search_query"].astype(str).tolist())


def resolve_query_on_page(
    page: Page,
    query: str,
    *,
    search_base_url: str,
    step_delay_ms: int,
) -> dict[str, Any]:
    row = resolve_on_page(
        page,
        raw_input=query,
        search_base_url=search_base_url,
        step_delay_ms=step_delay_ms,
    )
    row["search_query"] = query
    if not row.get("lookup_key"):
        row["lookup_key"] = lookup_key_for_input(query)
    if not row.get("canonical_key"):
        row["canonical_key"] = canonical_key(
            upc=str(row.get("supplier_upc") or ""),
            product_url=str(row.get("product_url") or ""),
            lookup_key=str(row.get("lookup_key") or ""),
        )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/parsed_boxes_formatted.csv")
    parser.add_argument("--output", default="out/parsed_boxes_search_prices.csv")
    parser.add_argument("--cache", default="out/parsed_boxes_search_cache.csv")
    parser.add_argument("--config", default="configs/dealernetx.daily.yaml")
    parser.add_argument("--limit", type=int, default=0, help="Max unique search queries (0 = all)")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    root = Path(".")
    inp = root / args.input
    if not inp.exists():
        raise SystemExit(f"Missing input: {inp}")

    boxes = pd.read_csv(inp)
    if "search_query" not in boxes.columns:
        raise SystemExit("Input must include search_query column (run strict-fuzzy-market-match.py first)")

    unique_queries = (
        boxes["search_query"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .tolist()
    )
    if args.limit > 0:
        unique_queries = unique_queries[: args.limit]

    cache_path = root / args.cache
    done = load_resume_done(cache_path)
    pending = [q for q in unique_queries if q not in done]
    print(f"unique queries: {len(unique_queries)} | resume skip: {len(done)} | pending: {len(pending)}")

    cfg = load_supplier_config(root / args.config)
    user, pw = _get_supplier_credentials(cfg)
    cache_rows: list[dict[str, Any]] = []

    if pending:
        scraped_at = datetime.now(timezone.utc).isoformat()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed, slow_mo=cfg.slow_mo_ms)
            page = browser.new_page()
            page.set_default_navigation_timeout(cfg.navigation_timeout_ms)
            page.set_default_timeout(cfg.selector_timeout_ms)
            _login(page, cfg, user, pw)

            for idx, query in enumerate(pending, start=1):
                print(f"[{idx}/{len(pending)}] {query}", flush=True)
                try:
                    row = resolve_query_on_page(
                        page,
                        query,
                        search_base_url=cfg.search_url or "",
                        step_delay_ms=cfg.step_delay_ms,
                    )
                except Exception as exc:
                    row = {
                        "search_query": query,
                        "lookup_key": lookup_key_for_input(query),
                        "search_status": "error",
                        "error": str(exc)[:300],
                    }
                row["scraped_at"] = scraped_at
                row["source"] = "search"
                cache_rows.append(row)

            browser.close()

    if cache_rows:
        if cache_path.exists():
            prev = pd.read_csv(cache_path)
            merged = pd.concat([prev, pd.DataFrame(cache_rows)], ignore_index=True)
            merged = merged.drop_duplicates(subset=["search_query"], keep="last")
        else:
            merged = pd.DataFrame(cache_rows)
        ensure_parent_dir(cache_path)
        merged.to_csv(cache_path, index=False)

    cache = pd.read_csv(cache_path) if cache_path.exists() else pd.DataFrame()
    joined = boxes.merge(cache, on="search_query", how="left", suffixes=("", "_cache"))

    out_path = root / args.output
    ensure_parent_dir(out_path)
    joined.to_csv(out_path, index=False)

    ok = int((cache.get("search_status") == "ok").sum()) if not cache.empty else 0
    print(f"cache -> {cache_path}")
    print(f"joined output -> {out_path} ({len(joined)} rows, {ok} ok lookups)")


if __name__ == "__main__":
    main()
