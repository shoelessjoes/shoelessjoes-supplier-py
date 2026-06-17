"""
Resolve a rough list of product names or UPCs to Dealernet market prices.

Input: CSV (column input/query/name/upc or first column) or .txt one item per line.
Output: out/market_resolve.csv + cache at out/market_resolve_cache.csv (resumable).

Then import to Postgres:
  cd ../shoelessjoes-ops
  npm run job:import-market-catalog
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_supplier_config
from src.dealernet_search import lookup_key_for_input, resolve_on_page
from src.supplier_scraper import _get_supplier_credentials, _login
from src.utils import ensure_parent_dir

INPUT_COLS = ("input", "query", "name", "upc", "product", "search_query", "title")


def load_inputs(path: Path) -> list[str]:
    if path.suffix.lower() == ".txt":
        lines = path.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip()]

    df = pd.read_csv(path)
    col = next((c for c in INPUT_COLS if c in df.columns), None)
    if col is None:
        col = df.columns[0]
    return (
        df[col]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .tolist()
    )


def load_resume_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        prev = pd.read_csv(path)
    except Exception:
        return set()
    if "lookup_key" not in prev.columns or "search_status" not in prev.columns:
        return set()
    ok = prev[prev["search_status"].isin(["ok", "no_results", "no_prices"])]
    return set(ok["lookup_key"].astype(str).tolist())


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve rough UPCs/names via Dealernet search")
    parser.add_argument("--input", required=True, help="CSV or .txt list of names/UPCs")
    parser.add_argument("--output", default="out/market_resolve.csv")
    parser.add_argument("--cache", default="out/market_resolve_cache.csv")
    parser.add_argument("--config", default="configs/dealernetx.daily.yaml")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--import-db", action="store_true", help="Run ops import after resolve")
    args = parser.parse_args()

    root = Path(".")
    inp = root / args.input
    if not inp.exists():
        raise SystemExit(f"Missing input: {inp}")

    raw_inputs = load_inputs(inp)
    seen: set[str] = set()
    unique_inputs: list[str] = []
    for item in raw_inputs:
        key = lookup_key_for_input(item)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_inputs.append(item)

    if args.limit > 0:
        unique_inputs = unique_inputs[: args.limit]

    cache_path = root / args.cache
    done = load_resume_done(cache_path)
    pending = [x for x in unique_inputs if lookup_key_for_input(x) not in done]
    print(f"inputs: {len(raw_inputs)} | unique: {len(unique_inputs)} | cached: {len(done)} | pending: {len(pending)}")

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

            for idx, raw in enumerate(pending, start=1):
                print(f"[{idx}/{len(pending)}] {raw}", flush=True)
                try:
                    row = resolve_on_page(
                        page,
                        raw_input=raw,
                        search_base_url=cfg.search_url or "",
                        step_delay_ms=cfg.step_delay_ms,
                    )
                except Exception as exc:
                    row = {
                        "input_raw": raw,
                        "lookup_key": lookup_key_for_input(raw),
                        "search_query": raw,
                        "search_status": "error",
                        "error": str(exc)[:300],
                        "canonical_key": lookup_key_for_input(raw),
                    }
                row["scraped_at"] = scraped_at
                row["source"] = "search"
                cache_rows.append(row)

            browser.close()

    if cache_rows:
        if cache_path.exists():
            prev = pd.read_csv(cache_path)
            merged = pd.concat([prev, pd.DataFrame(cache_rows)], ignore_index=True)
            merged = merged.drop_duplicates(subset=["lookup_key"], keep="last")
        else:
            merged = pd.DataFrame(cache_rows)
        ensure_parent_dir(cache_path)
        merged.to_csv(cache_path, index=False)

    cache = pd.read_csv(cache_path) if cache_path.exists() else pd.DataFrame()
    inputs_df = pd.DataFrame({"input_raw": raw_inputs})
    inputs_df["lookup_key"] = inputs_df["input_raw"].map(lookup_key_for_input)
    joined = inputs_df.merge(cache, on="lookup_key", how="left", suffixes=("", "_cache"))

    out_path = root / args.output
    ensure_parent_dir(out_path)
    joined.to_csv(out_path, index=False)

    ok = int((cache.get("search_status") == "ok").sum()) if not cache.empty else 0
    print(f"cache -> {cache_path}")
    print(f"output -> {out_path} ({len(joined)} rows, {ok} ok in cache)")

    if args.import_db:
        import subprocess

        ops = root.parent / "shoelessjoes-ops"
        if not ops.is_dir():
            print("warn: shoelessjoes-ops not found beside supplier-py; skip --import-db")
            return
        subprocess.run(["npm", "run", "job:import-market-catalog"], cwd=ops, check=True)


if __name__ == "__main__":
    main()
