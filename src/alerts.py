from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import SupplierConfig, post_login_url_ok
from .utils import normalize_upc, parse_money, read_csv_dicts


class PriceAlertError(RuntimeError):
    pass


def _set_alert_type(page, selector: str, alert_type: str) -> None:
    # Try legacy dropdown first.
    try:
        page.select_option(selector, label=alert_type)
        return
    except Exception:
        pass
    try:
        page.select_option(selector, value=alert_type)
        return
    except Exception:
        pass

    # Dealernet revamp uses radios: <input type="radio" name="type" value="Wanted|For Sale">
    radio_selector = f"input[type='radio'][name='type'][value='{alert_type}']"
    try:
        page.check(radio_selector)
        return
    except Exception:
        pass
    try:
        page.click(radio_selector)
        return
    except Exception as e:
        raise PriceAlertError(f"Could not set alert type to '{alert_type}'") from e


def _fill_alert_price(page, preferred_selector: str, value: float) -> None:
    val = f"{value:.2f}"
    candidates = [
        preferred_selector,
        "input[name='dprice']",
        "input#dprice",
        "input[name='price']",
        "input#price",
    ]
    for sel in candidates:
        try:
            page.fill(sel, val)
            return
        except Exception:
            continue
    raise PriceAlertError("Could not fill alert price field")


def _bucket_rank(bucket: str) -> int:
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return order.get((bucket or "").strip().lower(), 99)


def _safe_int(v: str | None) -> int:
    try:
        return int(str(v or "").strip())
    except (TypeError, ValueError):
        return 0


def add_price_alerts_from_csv(
    config: SupplierConfig,
    *,
    matches_csv: Path,
    match_types: set[str],
    alert_type: str,
    # You can decide alert price from either supplier or shopify; by default use supplier.
    price_source: str = "supplier",
    min_priority_bucket: Optional[str] = None,
    allowed_actions: Optional[set[str]] = None,
    require_in_stock: bool = False,
    min_sold_30d: int = 0,
    max_alerts: int = 200,
    dry_run: bool = True,
) -> dict[str, int]:
    """
    Reads `matches.csv` and creates alerts for rows with desired match_types.

    This is intentionally conservative: it does not try to outsmart site constraints.
    If the site rejects an alert (range check), we count it as rejected.
    """
    if not config.price_alert_url:
        raise PriceAlertError("price_alerts.url is not set in supplier config")
    if not (config.price_alert_type_selector and config.price_alert_price_selector and config.price_alert_add_selector):
        raise PriceAlertError("price alert selectors not fully set (type_selector/price_selector/add_selector)")

    username = os.getenv(config.username_env, "")
    password = os.getenv(config.password_env, "")
    if not username or not password:
        raise PriceAlertError(
            f"Missing supplier credentials in env vars: {config.username_env}, {config.password_env}"
        )

    source = (price_source or "supplier").strip().lower()
    if source not in {"supplier", "shopify", "suggested"}:
        raise PriceAlertError("price_source must be one of: supplier, shopify, suggested")

    min_bucket_rank: Optional[int] = None
    if min_priority_bucket and min_priority_bucket.strip():
        b = min_priority_bucket.strip().lower()
        if b not in {"urgent", "high", "medium", "low"}:
            raise PriceAlertError("min_priority_bucket must be one of: urgent, high, medium, low")
        min_bucket_rank = _bucket_rank(b)

    actions = {(a or "").strip() for a in (allowed_actions or set()) if (a or "").strip()}
    rows = read_csv_dicts(matches_csv)
    targets = []
    seen_keys: set[tuple[str, str]] = set()
    filtered_out = 0
    for r in rows:
        if (r.get("match_type") or "").strip() not in match_types:
            filtered_out += 1
            continue
        if actions and (r.get("action") or "").strip() not in actions:
            filtered_out += 1
            continue
        if min_bucket_rank is not None and _bucket_rank(r.get("priority_bucket") or "") > min_bucket_rank:
            filtered_out += 1
            continue

        inv = _safe_int(r.get("shopify_inventory_quantity"))
        if require_in_stock and inv <= 0:
            filtered_out += 1
            continue

        sold_30d = _safe_int(r.get("sold_30d"))
        if sold_30d < int(min_sold_30d):
            filtered_out += 1
            continue

        supplier_title = (r.get("supplier_title") or "").strip()
        supplier_upc = normalize_upc(r.get("supplier_upc") or "")
        supplier_price = parse_money(r.get("supplier_price"))
        shopify_price = parse_money(r.get("shopify_price"))
        suggested_price = parse_money(r.get("suggested_price"))
        if source == "supplier":
            price = supplier_price
        elif source == "shopify":
            price = shopify_price
        else:
            price = suggested_price
        if price is None:
            filtered_out += 1
            continue

        dedupe_key = (supplier_upc or "", f"{price:.2f}")
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        targets.append({"upc": supplier_upc, "title": supplier_title, "price": round(price, 2)})
        if max_alerts > 0 and len(targets) >= max_alerts:
            break

    stats = {
        "rows_total": len(rows),
        "rows_filtered_out": filtered_out,
        "planned": len(targets),
        "attempted": 0,
        "added": 0,
        "rejected": 0,
        "skipped": 0,
    }
    if not targets:
        stats["skipped"] = 1
        return stats
    if dry_run:
        return stats

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=config.slow_mo_ms)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(config.navigation_timeout_ms)
        page.set_default_timeout(config.selector_timeout_ms)

        # Login
        page.goto(config.login_url)
        page.wait_for_timeout(config.step_delay_ms)
        page.fill(config.username_selector, username)
        page.wait_for_timeout(config.step_delay_ms)
        page.fill(config.password_selector, password)
        page.wait_for_timeout(config.step_delay_ms)
        with page.expect_navigation():
            page.click(config.submit_selector)

        if not post_login_url_ok(config, page.url):
            raise PriceAlertError(f"Login may have failed (url={page.url})")

        for t in targets:
            stats["attempted"] += 1
            page.goto(config.price_alert_url)
            page.wait_for_timeout(config.step_delay_ms)

            _set_alert_type(page, config.price_alert_type_selector, alert_type)

            page.wait_for_timeout(config.step_delay_ms)
            _fill_alert_price(page, config.price_alert_price_selector, float(t["price"]))
            page.wait_for_timeout(config.step_delay_ms)

            page.click(config.price_alert_add_selector)
            page.wait_for_timeout(config.step_delay_ms)

            # If feedback selector is configured, use it to detect acceptance vs rejection.
            if config.price_alert_feedback_selector:
                try:
                    msg = page.locator(config.price_alert_feedback_selector).first.inner_text().strip()
                    if msg:
                        # Heuristic: presence of "error" / "range" implies rejection
                        if any(x in msg.lower() for x in ["error", "range", "invalid", "must be"]):
                            stats["rejected"] += 1
                        else:
                            stats["added"] += 1
                        continue
                except PlaywrightTimeoutError:
                    pass

            # No feedback selector: assume added (best-effort).
            stats["added"] += 1

        browser.close()

    return stats

