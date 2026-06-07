from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import SupplierConfig, post_login_url_ok
from .models import SupplierRow
from .utils import normalize_upc, now_utc, parse_money, read_csv_dicts, upcs_from_cell, write_csv


class SupplierScrapeError(RuntimeError):
    pass


def _get_supplier_credentials(config: SupplierConfig) -> tuple[str, str]:
    username = os.getenv(config.username_env, "")
    password = os.getenv(config.password_env, "")
    if not username or not password:
        raise SupplierScrapeError(
            f"Missing supplier credentials in env vars: {config.username_env}, {config.password_env}. "
            f"Copy .env.example to .env and set values (do not put passwords in YAML)."
        )
    return username, password


def _login(page, config: SupplierConfig, username: str, password: str) -> None:
    page.goto(config.login_url)
    _sleep_ms(page, config.step_delay_ms)
    page.fill(config.username_selector, username)
    _sleep_ms(page, config.step_delay_ms)
    page.fill(config.password_selector, password)
    _sleep_ms(page, config.step_delay_ms)
    with page.expect_navigation():
        page.click(config.submit_selector)

    # Broad username selectors often hit the global product search; you then land on search.php?keywordsearch=...
    if "search.php" in page.url and "keywordsearch=" in page.url.lower():
        raise SupplierScrapeError(
            "Redirected to site search (keywordsearch=). The scraper probably filled the header search bar "
            "instead of the login form. Scope login.username_selector / password_selector / submit_selector "
            "to the login card (e.g. under main), not sitewide inputs."
        )

    if not post_login_url_ok(config, page.url):
        raise SupplierScrapeError(
            f"Login may have failed (url={page.url}). Check username, password, submit_selector, "
            f"or add this path to login.success_url_contains_any in your YAML."
        )
    if config.success_selector:
        try:
            page.wait_for_selector(config.success_selector, timeout=config.selector_timeout_ms)
        except PlaywrightTimeoutError as e:
            raise SupplierScrapeError("Login may have failed (success selector not found)") from e


def test_supplier_login(config: SupplierConfig, *, headed: bool = False) -> str:
    """
    Opens the site, fills login form from .env, submits, and checks success_url_contains / success_selector.
    Returns the final URL after login. Raises SupplierScrapeError on failure.
    """
    username, password = _get_supplier_credentials(config)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=config.slow_mo_ms)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(config.navigation_timeout_ms)
        page.set_default_timeout(config.selector_timeout_ms)
        try:
            _login(page, config, username, password)
            url = page.url
        finally:
            browser.close()
    return url


def _sleep_ms(page, ms: int) -> None:
    if ms and ms > 0:
        page.wait_for_timeout(ms)


def _apply_filter_actions(page, actions: list[dict[str, Any]], step_delay_ms: int) -> None:
    for action in actions:
        if "click" in action:
            selector = action["click"]["selector"]
            page.click(selector)
        elif "fill" in action:
            selector = action["fill"]["selector"]
            value = action["fill"].get("value", "")
            page.fill(selector, value)
        elif "fill_relative_date" in action:
            cfg = action["fill_relative_date"]
            selector = cfg["selector"]
            days_ago = int(cfg.get("days_ago", 0))
            fmt = str(cfg.get("format", "%m/%d/%Y"))
            value = (datetime.now() - timedelta(days=days_ago)).strftime(fmt)
            page.fill(selector, value)
        elif "select" in action:
            sel = action["select"]
            selector = sel["selector"]
            value = sel["value"]
            if sel.get("wait_navigation"):
                nav_timeout = int(sel.get("navigation_timeout_ms", 60000))
                try:
                    # Revamped pages may update content without a full page navigation.
                    with page.expect_navigation(timeout=nav_timeout):
                        page.select_option(selector, value=value)
                except PlaywrightTimeoutError:
                    page.select_option(selector, value=value)
            else:
                page.select_option(selector, value=value)
        elif "wait_for_selector" in action:
            selector = action["wait_for_selector"]["selector"]
            timeout_ms = int(action["wait_for_selector"].get("timeout_ms", 30000))
            page.wait_for_selector(selector, timeout=timeout_ms)
        elif "wait_ms" in action:
            ms = int(action["wait_ms"]["ms"])
            _sleep_ms(page, ms)
        else:
            raise SupplierScrapeError(f"Unsupported filter action: {action}")

        _sleep_ms(page, step_delay_ms)


def _build_header_index(headers: list[str]) -> dict[str, int]:
    idx = {}
    for i, h in enumerate(headers):
        key = (h or "").strip().lower()
        if key and key not in idx:
            idx[key] = i
    return idx


def _discover_results_table_selector(page, expected_headers: list[str]) -> Optional[str]:
    """
    Finds a table whose headers include expected_headers.
    Returns a selector like table:nth-of-type(2), or None.
    """
    expected = {h.strip().lower() for h in expected_headers if h and str(h).strip()}
    if not expected:
        return None

    tables = page.locator("table")
    count = tables.count()
    for i in range(count):
        t = tables.nth(i)
        headers = t.locator("thead th").all_text_contents()
        if not headers:
            headers = t.locator("tr th").all_text_contents()
        normalized = {(h or "").strip().lower() for h in headers if (h or "").strip()}
        if expected.issubset(normalized):
            return f"table:nth-of-type({i + 1})"
    return None


def _get_cell_by_mapping(
    row_cells: list[str],
    mapping_rule: dict[str, Any],
    header_index: dict[str, int],
) -> Optional[str]:
    if "index" in mapping_rule:
        i = int(mapping_rule["index"])
        if 0 <= i < len(row_cells):
            return row_cells[i]
        return None
    if "header" in mapping_rule:
        h = str(mapping_rule["header"]).strip().lower()
        i = header_index.get(h)
        if i is None:
            return None
        if 0 <= i < len(row_cells):
            return row_cells[i]
        return None
    return None


def scrape_supplier_table(config: SupplierConfig, out_csv: Path) -> list[SupplierRow]:
    username, password = _get_supplier_credentials(config)

    scraped_at = now_utc()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=config.slow_mo_ms)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(config.navigation_timeout_ms)
        page.set_default_timeout(config.selector_timeout_ms)

        def parse_current_table(*, table_sel: Optional[str] = None) -> list[SupplierRow]:
            tbl = (table_sel or config.table_selector).strip()
            try:
                page.wait_for_selector(tbl)
            except PlaywrightTimeoutError as e:
                expected_headers: list[str] = []
                for key in ("title", "upc", "supplier_price", "variation"):
                    rule = config.mapping.get(key, {})
                    if "header" in rule:
                        expected_headers.append(str(rule["header"]))
                discovered = _discover_results_table_selector(page, expected_headers)
                if discovered:
                    tbl = discovered
                else:
                    raise SupplierScrapeError(
                        f"Results table not found with selector '{tbl}' at url={page.url}. "
                        "No table matched expected mapping headers."
                    ) from e

            header_row = page.locator(f"{tbl} {config.header_row_selector}").first
            header_cells = header_row.locator("th").all_text_contents()
            if not header_cells:
                header_cells = header_row.locator("td").all_text_contents()
            header_cells = [h.strip() for h in header_cells]
            header_index = _build_header_index(header_cells)

            rows = page.locator(f"{tbl} {config.body_row_selector}")
            n = rows.count()
            out: list[SupplierRow] = []
            for i in range(n):
                r = rows.nth(i)
                cells = [c.strip() for c in r.locator(config.cell_selector).all_text_contents()]
                if not any(cells):
                    continue

                upc_raw = _get_cell_by_mapping(cells, config.mapping.get("upc", {}), header_index)
                title_raw = (
                    _get_cell_by_mapping(cells, config.mapping.get("title", {}), header_index) or ""
                )
                var_rule = config.mapping.get("variation", {"header": "Variation"})
                var_raw = _get_cell_by_mapping(cells, var_rule, header_index)
                price_raw = _get_cell_by_mapping(
                    cells, config.mapping.get("supplier_price", {}), header_index
                )
                high_buy_raw = _get_cell_by_mapping(
                    cells, config.mapping.get("supplier_high_buy", {}), header_index
                )
                low_sell_raw = _get_cell_by_mapping(
                    cells, config.mapping.get("supplier_low_sell", {}), header_index
                )

                title = str(title_raw).strip()
                if config.title_append_variation and var_raw and str(var_raw).strip():
                    title = f"{title} ({str(var_raw).strip()})"
                price = parse_money(price_raw)
                high_buy = parse_money(high_buy_raw)
                low_sell = parse_money(low_sell_raw)
                base_raw = {
                    "cells": cells,
                    "headers": header_cells,
                    "url": page.url,
                    "upc_cell": upc_raw,
                }
                codes = upcs_from_cell(upc_raw)
                if not codes:
                    # Do not normalize the whole cell when it held multiple <br>-separated UPCs — that would
                    # merge digits. Single-line odd formats fall through with upc None unless upcs_from_cell parses them.
                    out.append(
                        SupplierRow(
                            upc=None,
                            title=title,
                            supplier_price=price,
                            supplier_high_buy=high_buy,
                            supplier_low_sell=low_sell,
                            raw=base_raw,
                            scraped_at=scraped_at,
                            product_url=page.url,
                        )
                    )
                else:
                    for u in codes:
                        out.append(
                            SupplierRow(
                                upc=u,
                                title=title,
                                supplier_price=price,
                                supplier_high_buy=high_buy,
                                supplier_low_sell=low_sell,
                                raw=base_raw,
                                scraped_at=scraped_at,
                                product_url=page.url,
                            )
                        )
            return out

        _login(page, config, username, password)

        supplier_rows: list[SupplierRow] = []

        # Mode A: UPC-driven lookup via the site's global search bar
        if config.upc_lookup_enabled and config.upc_csv_path:
            raw_path = Path(config.upc_csv_path)
            if raw_path.is_absolute():
                upc_csv = raw_path.resolve()
            else:
                # Relative paths: prefer cwd (run from project root), then repo root when --out out/foo.csv,
                # then beside output (legacy). Avoid wrongly resolving data/file.csv as out/data/file.csv.
                candidates = [
                    (Path.cwd() / raw_path).resolve(),
                    (out_csv.parent.parent / raw_path).resolve(),
                    (out_csv.parent / raw_path).resolve(),
                ]
                upc_csv = next((p for p in candidates if p.exists()), candidates[0])
            if not upc_csv.exists():
                raise SupplierScrapeError(
                    f"UPC CSV not found: {upc_csv}. "
                    f"Expected something like project/data/upcs_pilot.csv (run from project root) "
                    f"or set an absolute path in upc_lookup.upc_csv_path. cwd={Path.cwd()}"
                )

            upc_rows = read_csv_dicts(upc_csv)
            upcs = [normalize_upc(r.get("upc") or "") for r in upc_rows]
            upcs = [u for u in upcs if u]
            if not upcs:
                raise SupplierScrapeError(f"No UPCs found in CSV (expected column 'upc'): {upc_csv}")
            upc_set = set(upcs)

            def run_table_filter_mode() -> list[SupplierRow]:
                page.goto(config.table_url)
                _sleep_ms(page, config.step_delay_ms)
                _apply_filter_actions(page, config.filter_actions, config.step_delay_ms)
                detail_tbl = config.table_selector_after_product_link or config.table_selector
                all_rows = parse_current_table(table_sel=detail_tbl)
                return [r for r in all_rows if r.upc and r.upc in upc_set]

            def run_category_sweep_mode() -> list[SupplierRow]:
                collected: list[SupplierRow] = []
                for category_id in config.category_sweep_ids:
                    page.goto(config.table_url)
                    _sleep_ms(page, config.step_delay_ms)
                    try:
                        page.select_option("#categoryid", value=str(category_id))
                    except PlaywrightTimeoutError:
                        # Skip unknown/missing categories safely.
                        continue
                    _sleep_ms(page, config.step_delay_ms)
                    # Apply the remaining configured actions (date window, waits, etc).
                    _apply_filter_actions(page, config.filter_actions, config.step_delay_ms)
                    detail_tbl = config.table_selector_after_product_link or config.table_selector
                    rows = parse_current_table(table_sel=detail_tbl)
                    collected.extend(r for r in rows if r.upc and r.upc in upc_set)

                # Deduplicate rows that can appear in more than one category view.
                deduped: list[SupplierRow] = []
                seen: set[tuple[str, str, Optional[float], Optional[float]]] = set()
                for r in collected:
                    key = (
                        r.upc or "",
                        (r.title or "").strip().lower(),
                        r.supplier_high_buy,
                        r.supplier_low_sell,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(r)
                return deduped

            search_available = False
            if config.search_input_selector:
                page.goto(config.table_url)
                _sleep_ms(page, config.step_delay_ms)
                _apply_filter_actions(page, config.filter_actions, config.step_delay_ms)
                try:
                    page.locator(config.search_input_selector).first.wait_for(
                        state="visible", timeout=5000
                    )
                    search_available = True
                except PlaywrightTimeoutError:
                    search_available = False

            if config.category_sweep_ids:
                supplier_rows = run_category_sweep_mode()
            elif not config.search_input_selector or not search_available:
                supplier_rows = run_table_filter_mode()
            else:
                for upc in upcs:
                    # Start from a known page each time.
                    page.goto(config.table_url)
                    _sleep_ms(page, config.step_delay_ms)
                    # Price guide filters (category → subcategory → year → box type → dates) belong here,
                    # before the global product search — not after opening a product.
                    _apply_filter_actions(page, config.filter_actions, config.step_delay_ms)

                    page.fill(config.search_input_selector, upc)
                    _sleep_ms(page, config.step_delay_ms)

                    if config.search_submit_selector:
                        page.click(config.search_submit_selector)
                    else:
                        page.keyboard.press("Enter")

                    if config.search_wait_url_contains:
                        try:
                            needle = config.search_wait_url_contains
                            page.wait_for_url(
                                lambda u, n=needle: n in u,
                                timeout=config.selector_timeout_ms,
                            )
                        except PlaywrightTimeoutError:
                            pass

                    _sleep_ms(page, config.step_delay_ms)

                    if config.search_results_first_link_selector:
                        try:
                            link = page.locator(config.search_results_first_link_selector).first
                            link.wait_for(state="visible", timeout=config.selector_timeout_ms)
                            link.click()
                            _sleep_ms(page, config.step_delay_ms)
                        except PlaywrightTimeoutError:
                            continue

                    if config.navigate_back_to_table_selector:
                        try:
                            page.click(config.navigate_back_to_table_selector)
                            _sleep_ms(page, config.step_delay_ms)
                        except PlaywrightTimeoutError:
                            pass

                    detail_tbl = config.table_selector_after_product_link or config.table_selector
                    supplier_rows.extend(parse_current_table(table_sel=detail_tbl))

        # Mode B: scrape current table based on filters on table page
        else:
            page.goto(config.table_url)
            _sleep_ms(page, config.step_delay_ms)
            _apply_filter_actions(page, config.filter_actions, config.step_delay_ms)
            supplier_rows = parse_current_table()

        browser.close()

    # Write CSV
    out_records = [
        {
            "upc": r.upc or "",
            "title": r.title,
            "supplier_price": "" if r.supplier_price is None else r.supplier_price,
            "supplier_high_buy": "" if r.supplier_high_buy is None else r.supplier_high_buy,
            "supplier_low_sell": "" if r.supplier_low_sell is None else r.supplier_low_sell,
            "product_url": r.product_url or "",
            "scraped_at": r.scraped_at.isoformat(),
        }
        for r in supplier_rows
    ]
    write_csv(
        out_csv,
        out_records,
        fieldnames=[
            "upc",
            "title",
            "supplier_price",
            "supplier_high_buy",
            "supplier_low_sell",
            "product_url",
            "scraped_at",
        ],
    )

    # Also write a companion parquet for convenience when iterating locally.
    try:
        df = pd.DataFrame(out_records)
        df.to_parquet(out_csv.with_suffix(".parquet"), index=False)
    except Exception:
        # Parquet is optional; don't fail the scrape if pyarrow/fastparquet isn't installed.
        pass

    return supplier_rows

