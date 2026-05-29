from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from .shopify_client import ShopifyError, _parse_link_header, _shopify_headers
from .utils import normalize_upc, write_csv


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_inventory_available_by_item_id(
    session: requests.Session,
    domain: str,
    version: str,
    inventory_item_ids: list[str],
) -> dict[str, int]:
    """Sums `available` across locations for each inventory_item_id."""
    out: dict[str, int] = {str(i): 0 for i in inventory_item_ids}
    for chunk in _chunked(inventory_item_ids, 50):
        params = {"inventory_item_ids": ",".join(chunk), "limit": 250}
        url = f"https://{domain}/admin/api/{version}/inventory_levels.json"
        resp = session.get(url, params=params, timeout=120)
        if resp.status_code != 200:
            raise ShopifyError(
                f"inventory_levels error {resp.status_code}: {resp.text[:500]}"
            )
        for lvl in resp.json().get("inventory_levels", []) or []:
            iid = str(lvl.get("inventory_item_id", ""))
            avail = int(lvl.get("available", 0) or 0)
            if iid in out:
                out[iid] += avail
            else:
                out[iid] = avail
    return out


def export_upc_tier_csvs(out_dir: Path) -> dict[str, int]:
    """
    Writes three UPC lists for tiered Dealernet runs (column header: upc):

    - upcs_in_stock.csv — sum of available inventory > 0 (good for daily runs)
    - upcs_out_of_stock.csv — barcode present, in catalog, available == 0 (every other day)
    - upcs_all_barcodes.csv — every distinct barcode on a variant (weekly full pass)

    Requires Admin API scopes: read_products, read_inventory (and locations if needed).
    """
    load_dotenv()
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    version = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()
    if not domain or not token:
        raise ShopifyError("Missing SHOPIFY_SHOP_DOMAIN or SHOPIFY_ACCESS_TOKEN in .env")

    session = requests.Session()
    session.headers.update(_shopify_headers(token))

    base = f"https://{domain}/admin/api/{version}/products.json"
    params = {"limit": 250, "fields": "id,title,variants"}
    url: Optional[str] = base
    first = True

    rows: list[dict[str, Any]] = []
    while url:
        resp = session.get(url, params=params if first else None, timeout=120)
        first = False
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify API error {resp.status_code}: {resp.text[:500]}")
        for p in resp.json().get("products", []) or []:
            for v in (p.get("variants", []) or []):
                barcode = normalize_upc(v.get("barcode") or None)
                iid = v.get("inventory_item_id")
                rows.append(
                    {
                        "barcode": barcode,
                        "inventory_item_id": str(iid) if iid else "",
                        "variant_id": str(v.get("id", "")),
                        "product_title": str(p.get("title", "") or ""),
                    }
                )
        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")

    with_barcode = [r for r in rows if r.get("barcode")]
    item_ids = [r["inventory_item_id"] for r in with_barcode if r.get("inventory_item_id")]
    item_ids = list(dict.fromkeys(item_ids))

    available_by_item: dict[str, int] = {}
    if item_ids:
        available_by_item = _fetch_inventory_available_by_item_id(
            session, domain, version, item_ids
        )

    qty_by_upc: dict[str, int] = defaultdict(int)
    for r in with_barcode:
        upc = r["barcode"]
        if not upc:
            continue
        iid = r.get("inventory_item_id") or ""
        qty_by_upc[upc] += available_by_item.get(iid, 0) if iid else 0

    all_upcs = sorted(qty_by_upc.keys())
    in_stock_upcs = sorted(u for u, q in qty_by_upc.items() if q > 0)
    oos_upcs = sorted(u for u, q in qty_by_upc.items() if q == 0)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "upcs_in_stock.csv", [{"upc": u} for u in in_stock_upcs], ["upc"])
    write_csv(out_dir / "upcs_out_of_stock.csv", [{"upc": u} for u in oos_upcs], ["upc"])
    write_csv(out_dir / "upcs_all_barcodes.csv", [{"upc": u} for u in all_upcs], ["upc"])

    return {
        "with_barcode_variants": len(with_barcode),
        "in_stock_upcs": len(in_stock_upcs),
        "out_of_stock_upcs": len(oos_upcs),
        "all_distinct_upcs": len(all_upcs),
    }
