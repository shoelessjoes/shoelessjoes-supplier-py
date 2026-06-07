"""One-off probe: login + search.php UPC lookup + first result click."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_supplier_config
from src.supplier_scraper import _get_supplier_credentials, _login, _sleep_ms
from playwright.sync_api import sync_playwright


def main() -> None:
    upc = sys.argv[1] if len(sys.argv) > 1 else "887521158119"
    cfg = load_supplier_config(Path("configs/dealernetx.daily.yaml"))
    user, pw = _get_supplier_credentials(cfg)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=cfg.slow_mo_ms)
        page = browser.new_page()
        page.set_default_navigation_timeout(cfg.navigation_timeout_ms)
        page.set_default_timeout(cfg.selector_timeout_ms)
        _login(page, cfg, user, pw)
        print("logged in:", page.url)
        page.goto(f"https://www.dealernetx.com/search.php?keywordsearch={upc}")
        _sleep_ms(page, cfg.step_delay_ms)
        print("search url:", page.url)
        for sel in [
            cfg.search_results_first_link_selector,
            "table tbody tr td:nth-child(2) a",
            "table tbody tr td:nth-child(3) a",
            "table tbody tr a[href*='priceguide']",
            "a[href*='priceguide.php']",
            "main table a",
        ]:
            if not sel:
                continue
            n = page.locator(sel).count()
            print(f"  {sel!r}: {n}")
        sel = cfg.search_results_first_link_selector or "table tbody tr a[href*='priceguide']"
        link = page.locator(sel).first
        print("using:", sel, "count:", page.locator(sel).count())
        main_a = page.locator("main table a")
        for i in range(main_a.count()):
            print(f"  main table a {i}:", main_a.nth(i).get_attribute("href"), main_a.nth(i).inner_text()[:60])
        pg_links = page.locator("a[href*='priceguide.php']")
        for i in range(pg_links.count()):
            print(f"  priceguide link {i}:", pg_links.nth(i).get_attribute("href"))
        sel = "main table tbody tr a"
        link = page.locator(sel).first
        print("using:", sel, "count:", page.locator(sel).count())
        if link.count():
            href = link.get_attribute("href")
            print("first href:", href)
            link.click()
            _sleep_ms(page, cfg.step_delay_ms)
            print("product url:", page.url)
            print("tables:", page.locator("table").count())
            print("caption tables:", page.locator("table:has(caption)").count())
            for i in range(page.locator("table").count()):
                t = page.locator("table").nth(i)
                cap = t.locator("caption").first
                cap_txt = cap.inner_text() if cap.count() else ""
                headers = t.locator("thead th").all_text_contents()
                if not headers:
                    headers = t.locator("tr th").all_text_contents()
                print(f"  table {i} caption={cap_txt!r} headers={headers[:8]}")
        browser.close()


if __name__ == "__main__":
    main()
