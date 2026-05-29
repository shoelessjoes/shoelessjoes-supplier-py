from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class SupplierConfig:
    name: str

    login_url: str
    username_env: str
    password_env: str
    username_selector: str
    password_selector: str
    submit_selector: str
    # If non-empty, final URL after login must contain at least one of these substrings.
    success_url_patterns: Tuple[str, ...]
    success_selector: Optional[str]

    table_url: str
    filter_actions: list[dict[str, Any]]
    table_selector: str
    header_row_selector: str
    body_row_selector: str
    cell_selector: str
    # If true and mapping includes "variation", append non-empty Variation to title: `Product (Variation)`.
    title_append_variation: bool

    upc_lookup_enabled: bool
    upc_csv_path: Optional[str]
    # Optional category IDs to iterate (e.g. 21,23,25...) when scraping broad market tables.
    category_sweep_ids: Tuple[str, ...]
    search_input_selector: Optional[str]
    search_submit_selector: Optional[str]
    search_results_first_link_selector: Optional[str]
    # After search submit, wait until URL contains this substring (e.g. search.php).
    search_wait_url_contains: Optional[str]
    navigate_back_to_table_selector: Optional[str]

    # If set, used to parse the table on the product page after clicking the listing link;
    # otherwise table_page.table_selector is used everywhere.
    table_selector_after_product_link: Optional[str]

    price_alert_url: Optional[str]
    price_alert_type_selector: Optional[str]
    price_alert_price_selector: Optional[str]
    price_alert_add_selector: Optional[str]
    price_alert_feedback_selector: Optional[str]

    mapping: dict[str, dict[str, Any]]

    slow_mo_ms: int
    step_delay_ms: int
    navigation_timeout_ms: int
    selector_timeout_ms: int


def post_login_url_ok(config: SupplierConfig, url: str) -> bool:
    if not config.success_url_patterns:
        return True
    return any(p in url for p in config.success_url_patterns)


def load_supplier_config(path: Path) -> SupplierConfig:
    load_dotenv()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    supplier = raw.get("supplier", {}) or {}
    login = raw.get("login", {}) or {}
    table = raw.get("table_page", {}) or {}
    upc_lookup = raw.get("upc_lookup", {}) or {}
    alerts = raw.get("price_alerts", {}) or {}
    mapping = raw.get("mapping", {}) or {}
    politeness = raw.get("politeness", {}) or {}

    any_patterns = login.get("success_url_contains_any")
    single = login.get("success_url_contains")
    if any_patterns:
        url_patterns = tuple(str(x) for x in any_patterns if x is not None and str(x).strip())
    elif single:
        url_patterns = (str(single),)
    else:
        url_patterns = ()

    return SupplierConfig(
        name=str(supplier.get("name", "Supplier")),
        login_url=str(login["url"]),
        username_env=str(login.get("username_env", "SUPPLIER_USERNAME")),
        password_env=str(login.get("password_env", "SUPPLIER_PASSWORD")),
        username_selector=str(login["username_selector"]),
        password_selector=str(login["password_selector"]),
        submit_selector=str(login["submit_selector"]),
        success_url_patterns=url_patterns,
        success_selector=login.get("success_selector"),
        table_url=str(table["url"]),
        filter_actions=list(table.get("filter_actions", []) or []),
        table_selector=str(table.get("table_selector", "table")),
        header_row_selector=str(table.get("header_row_selector", "thead tr")),
        body_row_selector=str(table.get("body_row_selector", "tbody tr")),
        cell_selector=str(table.get("cell_selector", "td")),
        title_append_variation=bool(table.get("title_append_variation", False)),
        upc_lookup_enabled=bool(upc_lookup.get("enabled", False)),
        upc_csv_path=upc_lookup.get("upc_csv_path"),
        category_sweep_ids=tuple(str(x) for x in (upc_lookup.get("category_sweep_ids", []) or [])),
        search_input_selector=upc_lookup.get("search_input_selector"),
        search_submit_selector=upc_lookup.get("search_submit_selector"),
        search_results_first_link_selector=upc_lookup.get("search_results_first_link_selector"),
        search_wait_url_contains=upc_lookup.get("search_wait_url_contains"),
        navigate_back_to_table_selector=upc_lookup.get("navigate_back_to_table_selector"),
        table_selector_after_product_link=table.get("table_selector_after_product_link"),
        price_alert_url=alerts.get("url"),
        price_alert_type_selector=alerts.get("type_selector"),
        price_alert_price_selector=alerts.get("price_selector"),
        price_alert_add_selector=alerts.get("add_selector"),
        price_alert_feedback_selector=alerts.get("feedback_selector"),
        mapping=dict(mapping),
        slow_mo_ms=int(politeness.get("slow_mo_ms", 150)),
        step_delay_ms=int(politeness.get("step_delay_ms", 250)),
        navigation_timeout_ms=int(politeness.get("navigation_timeout_ms", 60000)),
        selector_timeout_ms=int(politeness.get("selector_timeout_ms", 30000)),
    )

