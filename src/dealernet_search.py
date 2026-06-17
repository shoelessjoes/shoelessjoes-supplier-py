"""Dealernet keyword / UPC search and price guide scraping."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse

from playwright.sync_api import Page
from rapidfuzz import fuzz

from .supplier_scraper import _sleep_ms
from .utils import normalize_upc, parse_money

YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
UPC_INPUT_RE = re.compile(r"^\d{8,14}$")
BOX_WORDS = (
    "hobby jumbo",
    "super jumbo",
    "breakers delight",
    "hobby",
    "blaster",
    "mega",
    "hanger",
    "retail",
    "jumbo",
    "gravity",
    "value",
    "tin",
    "pack",
)


def clean_match(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9/ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def year_from_text(s: str) -> str:
    m = YEAR_RE.search(s or "")
    return m.group(1) if m else ""


def year_from_url(url: str) -> str:
    return str(parse_qs(urlparse(url).query).get("year", [""])[0])


def box_phrase_in_text(text: str) -> str:
    t = clean_match(text)
    for phrase in BOX_WORDS:
        if phrase in t:
            return phrase
    return ""


def listing_to_priceguide(url: str) -> str:
    return url.replace("listing.php", "priceguide.php")


def lookup_key_for_input(raw: str) -> str:
    """Stable cache / DB key for a rough name or UPC."""
    s = (raw or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if UPC_INPUT_RE.match(digits):
        upc = normalize_upc(digits)
        if upc:
            return f"upc:{upc}"
    return f"q:{clean_match(s)}"


def search_term_for_input(raw: str) -> str:
    """What to send to Dealernet search.php."""
    s = (raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if UPC_INPUT_RE.match(digits):
        return digits
    return s


def search_url(base: str, query: str) -> str:
    base = (base or "https://www.dealernetx.com/search.php").strip()
    if "keywordsearch=" in base.lower():
        return re.sub(
            r"keywordsearch=[^&]*",
            f"keywordsearch={quote(query)}",
            base,
            count=1,
            flags=re.I,
        )
    join = "&" if "?" in base else "?"
    return f"{base}{join}keywordsearch={quote(query)}"


def canonical_key(
    *,
    upc: str = "",
    product_url: str = "",
    lookup_key: str = "",
) -> str:
    u = normalize_upc(upc) or ""
    if u:
        return f"upc:{u}"
    url = (product_url or "").strip()
    if url:
        return f"url:{url}"
    lk = (lookup_key or "").strip()
    if lk:
        return lk if lk.startswith(("upc:", "q:", "url:")) else f"q:{clean_match(lk)}"
    return ""


@dataclass
class SearchResult:
    rank: int
    product: str
    upc: str
    release_date: str
    factory: str
    listing_url: str
    year: str


def parse_search_results(page: Page) -> list[SearchResult]:
    rows = page.locator("main table tbody tr")
    out: list[SearchResult] = []
    for i in range(rows.count()):
        row = rows.nth(i)
        cells = [c.strip() for c in row.locator("td").all_text_contents()]
        if len(cells) < 4:
            continue
        link = row.locator("a[href*='listing.php']").first
        if link.count() == 0:
            continue
        href = (link.get_attribute("href") or "").strip()
        if not href:
            continue
        listing_url = urljoin(page.url, href)
        product = link.inner_text().strip() or (cells[3] if len(cells) > 3 else "")
        upc = cells[1] if len(cells) > 1 and cells[1] != "-" else ""
        release_date = cells[5] if len(cells) > 5 else ""
        factory = cells[6] if len(cells) > 6 else ""
        out.append(
            SearchResult(
                rank=i + 1,
                product=product,
                upc=upc,
                release_date=release_date,
                factory=factory,
                listing_url=listing_url,
                year=year_from_url(listing_url) or year_from_text(product),
            )
        )
    return out


def score_search_result(query: str, result: SearchResult) -> float:
    q_clean = clean_match(query)
    p_clean = clean_match(result.product.replace("~", " "))
    score = float(fuzz.token_set_ratio(q_clean, p_clean))

    q_year = year_from_text(query)
    if q_year and result.year and q_year != result.year:
        score -= 60.0

    q_box = box_phrase_in_text(query)
    p_box = box_phrase_in_text(result.product)
    if q_box and p_box and q_box != p_box:
        score -= 35.0
    elif q_box and not p_box:
        score -= 15.0

    if q_box and q_box == p_box and len(p_clean) > len(q_clean) + 8:
        score -= 5.0

    return score


def pick_best_result(query: str, results: list[SearchResult]) -> Optional[tuple[SearchResult, float]]:
    if not results:
        return None
    scored = [(r, score_search_result(query, r)) for r in results]
    scored.sort(key=lambda x: (-x[1], x[0].rank))
    return scored[0]


def scrape_priceguide(page: Page, priceguide_url: str, step_delay_ms: int) -> dict[str, Any]:
    page.goto(priceguide_url)
    _sleep_ms(page, step_delay_ms)

    table = page.locator("table").first
    headers = [h.strip().lower() for h in table.locator("thead th").all_text_contents()]
    if not headers:
        headers = [h.strip().lower() for h in table.locator("tr th").all_text_contents()]

    def col_idx(name: str) -> Optional[int]:
        for i, h in enumerate(headers):
            if name in h:
                return i
        return None

    row = table.locator("tbody tr").first
    cells = [c.strip() for c in row.locator("td").all_text_contents()]
    if not cells:
        return {}

    title_i = col_idx("product")
    upc_i = col_idx("upc")
    hb_i = col_idx("current high buy")
    ls_i = col_idx("current low sell")

    return {
        "supplier_title": cells[title_i] if title_i is not None and title_i < len(cells) else "",
        "supplier_upc": cells[upc_i] if upc_i is not None and upc_i < len(cells) else "",
        "supplier_high_buy": parse_money(cells[hb_i]) if hb_i is not None and hb_i < len(cells) else None,
        "supplier_low_sell": parse_money(cells[ls_i]) if ls_i is not None and ls_i < len(cells) else None,
    }


def resolve_on_page(
    page: Page,
    *,
    raw_input: str,
    search_base_url: str,
    step_delay_ms: int,
) -> dict[str, Any]:
    """Search Dealernet for one rough UPC or product name; return a result row dict."""
    raw = (raw_input or "").strip()
    lookup_key = lookup_key_for_input(raw)
    search_term = search_term_for_input(raw)
    row: dict[str, Any] = {
        "input_raw": raw,
        "lookup_key": lookup_key,
        "search_query": search_term,
        "search_status": "error",
        "search_match_score": "",
        "search_result_rank": "",
        "supplier_title": "",
        "supplier_upc": "",
        "supplier_year": "",
        "release_date": "",
        "factory": "",
        "supplier_high_buy": "",
        "supplier_low_sell": "",
        "listing_url": "",
        "product_url": "",
        "canonical_key": "",
        "error": "",
    }
    if not raw:
        row["search_status"] = "empty"
        row["error"] = "blank input"
        return row

    page.goto(search_url(search_base_url, search_term))
    _sleep_ms(page, step_delay_ms)
    results = parse_search_results(page)
    if not results:
        row["search_status"] = "no_results"
        row["error"] = "search returned 0 listing rows"
        row["canonical_key"] = lookup_key
        return row

    picked = pick_best_result(search_term, results)
    if not picked:
        row["search_status"] = "no_results"
        row["canonical_key"] = lookup_key
        return row

    best, score = picked
    row["search_match_score"] = round(score, 2)
    row["search_result_rank"] = best.rank
    row["supplier_title"] = best.product
    row["supplier_upc"] = best.upc
    row["supplier_year"] = best.year
    row["release_date"] = best.release_date
    row["factory"] = best.factory
    row["listing_url"] = best.listing_url
    pg_url = listing_to_priceguide(best.listing_url)
    row["product_url"] = pg_url

    prices = scrape_priceguide(page, pg_url, step_delay_ms)
    if prices.get("supplier_title"):
        row["supplier_title"] = prices["supplier_title"]
    if prices.get("supplier_upc"):
        row["supplier_upc"] = prices["supplier_upc"]
    hb = prices.get("supplier_high_buy")
    ls = prices.get("supplier_low_sell")
    row["supplier_high_buy"] = "" if hb is None else hb
    row["supplier_low_sell"] = "" if ls is None else ls

    if hb is not None or ls is not None:
        row["search_status"] = "ok"
    else:
        row["search_status"] = "no_prices"
        row["error"] = "price guide had no buy/sell cells"

    row["canonical_key"] = canonical_key(
        upc=str(row.get("supplier_upc") or ""),
        product_url=str(row.get("product_url") or ""),
        lookup_key=lookup_key,
    )
    return row
