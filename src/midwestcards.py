"""Midwest Cards scrape helpers (Playwright + JSON-LD)."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Optional

from src.utils import normalize_upc

PRESell_CATEGORY_URLS = [
    "https://www.midwestcards.com/baseball-cards/?Availability=Presell",
    "https://www.midwestcards.com/basketball-cards/?Availability=Presell",
    "https://www.midwestcards.com/football-cards/?Availability=Presell",
    "https://www.midwestcards.com/hockey-cards/?Availability=Presell",
    "https://www.midwestcards.com/soccer-cards/?Availability=Presell",
]

LISTING_LINKS_JS = """() => {
  const roots = [
    '/baseball-cards/', '/basketball-cards/', '/football-cards/',
    '/hockey-cards/', '/soccer-cards/',
  ];
  const skipSlugs = new Set([
    'new-category', 'new-release', 'boxes', 'cases', 'packs', 'shop', 'presell', 'presale',
  ]);
  const out = new Set();

  const isProductSlug = (rest) => {
    if (!rest || rest.includes('/')) return false;
    if (skipSlugs.has(rest.toLowerCase())) return false;
    if (/^\\d{4}(-\\d{2})?$/.test(rest)) return false;
    if (!/[a-z]/i.test(rest)) return false;
    if (rest.length < 10) return false;
    return true;
  };

  const addFromAnchor = (a) => {
    const href = a.href || '';
    try {
      const u = new URL(href);
      if (!u.hostname.includes('midwestcards.com')) return;
      const path = u.pathname;
      for (const root of roots) {
        if (!path.startsWith(root)) continue;
        const rest = path.slice(root.length).replace(/\\/$/, '');
        if (!isProductSlug(rest)) break;
        out.add(u.origin + path.replace(/\\/$/, '') + '/');
        break;
      }
    } catch {}
  };

  const cardSelectors = [
    'article.card a',
    '.productGrid a',
    'li.product a',
    '[data-product-id] a',
    '.card-figure a',
  ];
  for (const sel of cardSelectors) {
    for (const a of document.querySelectorAll(sel)) addFromAnchor(a);
  }
  if (!out.size) {
    for (const a of document.querySelectorAll('a[href]')) addFromAnchor(a);
  }
  return [...out];
}"""

PRODUCT_EXTRACT_JS = """() => {
  const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
    .filter(Boolean);

  const upcs = new Set();
  const addUpc = (raw) => {
    if (!raw) return;
    const digits = String(raw).replace(/\\D/g, '');
    if (digits.length >= 8 && digits.length <= 14) upcs.add(digits);
  };

  let productName = null;
  let brand = null;
  let image = null;
  let price = null;
  let sku = null;

  for (const block of jsonLd) {
    const items = Array.isArray(block) ? block : [block];
    for (const item of items) {
      if (!item || typeof item !== 'object') continue;
      if (item['@type'] === 'Product' || item.name) {
        productName = productName || item.name || null;
        brand = brand || item.brand?.name || item.brand || null;
        image = image || (Array.isArray(item.image) ? item.image[0] : item.image) || null;
        sku = sku || item.sku || null;
        addUpc(item.gtin14 || item.gtin13 || item.gtin12 || item.gtin);
        const offers = item.offers ? (Array.isArray(item.offers) ? item.offers : [item.offers]) : [];
        for (const o of offers) {
          price = price || o.price || null;
          addUpc(o?.gtin14 || o?.gtin13 || o?.gtin12);
        }
      }
    }
  }

  const body = document.body.innerText || '';
  const specsEls = [...document.querySelectorAll(
    'table, dl, .productView-info, [class*="specification"], [id*="specification"]'
  )];
  const specsText = specsEls.map(el => el.innerText).join('\\n');

  for (const text of [body, specsText]) {
    for (const m of text.matchAll(/(?:UPC|Barcode|GTIN)[\\s:#]*([0-9]{8,14})/gi)) {
      addUpc(m[1]);
    }
  }

  let releaseDateRaw = null;
  const rel = specsText.match(/Release Date[\\s:\\n]*([^\\n]+)/i)
    || body.match(/Release Date[\\s:\\n]*([^\\n]+)/i);
  if (rel) releaseDateRaw = rel[1].trim();

  const sport = (() => {
    const p = location.pathname;
    if (p.includes('/baseball-cards/')) return 'Baseball';
    if (p.includes('/basketball-cards/')) return 'Basketball';
    if (p.includes('/football-cards/')) return 'Football';
    if (p.includes('/hockey-cards/')) return 'Hockey';
    if (p.includes('/soccer-cards/')) return 'Soccer';
    return null;
  })();

  const h1 = document.querySelector('h1')?.textContent?.trim() || '';
    url: location.href,
    upcs: [...upcs],
    releaseDateRaw,
    brand,
    image,
    price,
    sku,
    sport,
    isCase: /\\bcase\\b/i.test(h1),
  };
}"""

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def normalize_gtin(raw: str) -> Optional[str]:
    u = normalize_upc(raw)
    if not u:
        return None
    if len(u) == 14 and u.startswith("00"):
        u = u[2:]
    if len(u) == 13 and u.startswith("0"):
        u = u[1:]
    return u if 8 <= len(u) <= 14 else None


def pick_upc(upcs: list[str]) -> Optional[str]:
    for raw in upcs:
        u = normalize_gtin(str(raw))
        if u:
            return u
    return None


def parse_release_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"tbd", "n/a", "na", "-"}:
        return None
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    m = re.match(
        r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})",
        s,
        re.I,
    )
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
    m2 = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m2:
        return f"{m2.group(3)}-{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
    return None


def load_catalog_upcs(catalog_path: Path) -> dict[str, dict[str, str]]:
    """UPC -> catalog row (ACTIVE, DRAFT, ARCHIVED, etc.)."""
    by_upc: dict[str, dict[str, str]] = {}
    if not catalog_path.is_file():
        return by_upc
    with catalog_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            upc = normalize_upc(row.get("barcode") or row.get("upc"))
            if not upc:
                continue
            by_upc[upc] = {
                "productTitle": row.get("product_title") or row.get("productTitle") or "",
                "status": row.get("status") or "",
            }
    return by_upc


def product_row_from_extract(data: dict[str, Any]) -> dict[str, Any]:
    upc = pick_upc(data.get("upcs") or [])
    release_date = parse_release_date(data.get("releaseDateRaw"))
    return {
        "title": data.get("title") or "",
        "source_url": data.get("url") or "",
        "upc": upc or "",
        "release_date": release_date or "",
        "release_date_raw": data.get("releaseDateRaw") or "",
        "manufacturer": data.get("brand") or "",
        "sport": data.get("sport") or "",
        "mwc_sku": data.get("sku") or "",
        "mwc_price": data.get("price") or "",
        "image_url": data.get("image") or "",
        "is_case": bool(data.get("isCase")),
        "eligible": bool(upc and release_date and not data.get("isCase")),
    }
