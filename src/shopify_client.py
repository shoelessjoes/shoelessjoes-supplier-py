from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from .models import ShopifyVariantRow
from .utils import normalize_upc, parse_money, write_csv


class ShopifyError(RuntimeError):
    pass


def _shopify_headers(token: str) -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "supplier-price-dashboard/0.1",
    }


def _parse_link_header(link_header: Optional[str]) -> dict[str, str]:
    """
    Parses Shopify REST Link header.
    Returns mapping rel -> url.
    """
    if not link_header:
        return {}
    parts = [p.strip() for p in link_header.split(",")]
    out: dict[str, str] = {}
    for p in parts:
        if ";" not in p:
            continue
        url_part, rel_part = [x.strip() for x in p.split(";", 1)]
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        url = url_part[1:-1]
        rel = rel_part.replace('rel="', "").replace('"', "").strip()
        if rel:
            out[rel] = url
    return out


def _fetch_sales_by_variant_id(
    session: requests.Session,
    domain: str,
    version: str,
) -> dict[str, dict[str, int]]:
    """
    Pull recent orders and aggregate sold units per variant for 7/30/60 day windows.
    Requires read_orders scope.
    """
    sales: dict[str, dict[str, int]] = {}
    now = datetime.now(timezone.utc)
    created_at_min = (now - timedelta(days=60)).isoformat()
    url: Optional[str] = f"https://{domain}/admin/api/{version}/orders.json"
    first = True
    params = {
        "status": "any",
        "limit": 250,
        "created_at_min": created_at_min,
        "fields": "id,created_at,cancelled_at,line_items",
    }

    while url:
        resp = session.get(url, params=params if first else None, timeout=60)
        first = False
        if resp.status_code != 200:
            # Keep main pipeline usable if read_orders isn't granted yet.
            return sales

        for order in (resp.json().get("orders", []) or []):
            if order.get("cancelled_at"):
                continue
            created_raw = str(order.get("created_at") or "").strip()
            if not created_raw:
                continue
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError:
                continue

            age_days = max((now - created_at).days, 0)
            for line in (order.get("line_items", []) or []):
                variant_id = str(line.get("variant_id") or "").strip()
                if not variant_id:
                    continue
                qty = int(line.get("quantity") or 0)
                if qty <= 0:
                    continue
                bucket = sales.setdefault(variant_id, {"sold_7d": 0, "sold_30d": 0, "sold_60d": 0})
                if age_days <= 7:
                    bucket["sold_7d"] += qty
                if age_days <= 30:
                    bucket["sold_30d"] += qty
                if age_days <= 60:
                    bucket["sold_60d"] += qty

        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")

    return sales


def fetch_shopify_variants(out_csv: Path) -> list[ShopifyVariantRow]:
    load_dotenv()
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    version = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()
    if not domain or not token:
        raise ShopifyError("Missing SHOPIFY_SHOP_DOMAIN or SHOPIFY_ACCESS_TOKEN in .env")

    base = f"https://{domain}/admin/api/{version}/products.json"
    params = {
        "limit": 250,
        "fields": "id,title,created_at,status,product_type,variants",
    }

    session = requests.Session()
    session.headers.update(_shopify_headers(token))

    variants: list[ShopifyVariantRow] = []
    inventory_item_ids: set[str] = set()
    url: Optional[str] = base
    first = True

    while url:
        resp = session.get(url, params=params if first else None, timeout=60)
        first = False
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify API error {resp.status_code}: {resp.text[:500]}")

        payload = resp.json()
        products = payload.get("products", []) or []

        for p in products:
            product_id = str(p.get("id", ""))
            product_title = str(p.get("title", "") or "")
            product_created_at = str(p.get("created_at", "") or "") or None
            product_status = str(p.get("status", "") or "") or None
            product_type = str(p.get("product_type", "") or "") or None
            for v in (p.get("variants", []) or []):
                variant_id = str(v.get("id", ""))
                variant_title = str(v.get("title", "") or "")
                sku = v.get("sku") or None
                barcode = normalize_upc(v.get("barcode") or None)
                price = parse_money(v.get("price"))
                compare_at = parse_money(v.get("compare_at_price"))
                inventory_item_id = str(v.get("inventory_item_id")) if v.get("inventory_item_id") else None
                if inventory_item_id:
                    inventory_item_ids.add(inventory_item_id)

                variants.append(
                    ShopifyVariantRow(
                        product_id=product_id,
                        variant_id=variant_id,
                        product_title=product_title,
                        product_created_at=product_created_at,
                        product_status=product_status,
                        product_type=product_type,
                        variant_title=variant_title,
                        sku=str(sku) if sku else None,
                        barcode=barcode,
                        price=price,
                        compare_at_price=compare_at,
                        cost=None,
                        inventory_quantity=v.get("inventory_quantity"),
                        sold_7d=0,
                        sold_30d=0,
                        sold_60d=0,
                        inventory_item_id=inventory_item_id,
                        raw={"product": {"id": product_id, "title": product_title}, "variant": v},
                    )
                )

        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")

    # Fill inventory item costs in batches.
    cost_by_inventory_item: dict[str, Optional[float]] = {}
    inventory_ids = sorted(inventory_item_ids)
    for i in range(0, len(inventory_ids), 100):
        chunk = inventory_ids[i : i + 100]
        resp = session.get(
            f"https://{domain}/admin/api/{version}/inventory_items.json",
            params={"ids": ",".join(chunk), "fields": "id,cost"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify inventory_items error {resp.status_code}: {resp.text[:500]}")
        for item in (resp.json().get("inventory_items", []) or []):
            item_id = str(item.get("id") or "")
            if item_id:
                cost_by_inventory_item[item_id] = parse_money(item.get("cost"))

    sales_by_variant = _fetch_sales_by_variant_id(session, domain, version)

    variants = [
        ShopifyVariantRow(
            product_id=v.product_id,
            variant_id=v.variant_id,
            product_title=v.product_title,
            product_created_at=v.product_created_at,
            product_status=v.product_status,
            product_type=v.product_type,
            variant_title=v.variant_title,
            sku=v.sku,
            barcode=v.barcode,
            price=v.price,
            compare_at_price=v.compare_at_price,
            cost=cost_by_inventory_item.get(v.inventory_item_id or ""),
            inventory_quantity=v.inventory_quantity,
            sold_7d=sales_by_variant.get(v.variant_id, {}).get("sold_7d", 0),
            sold_30d=sales_by_variant.get(v.variant_id, {}).get("sold_30d", 0),
            sold_60d=sales_by_variant.get(v.variant_id, {}).get("sold_60d", 0),
            inventory_item_id=v.inventory_item_id,
            raw=v.raw,
        )
        for v in variants
    ]

    out_records = []
    for r in variants:
        out_records.append(
            {
                "product_id": r.product_id,
                "variant_id": r.variant_id,
                "product_title": r.product_title,
                "product_created_at": r.product_created_at or "",
                "product_status": r.product_status or "",
                "product_type": r.product_type or "",
                "variant_title": r.variant_title,
                "sku": r.sku or "",
                "barcode": r.barcode or "",
                "price": "" if r.price is None else r.price,
                "compare_at_price": "" if r.compare_at_price is None else r.compare_at_price,
                "cost": "" if r.cost is None else r.cost,
                "inventory_quantity": ""
                if r.inventory_quantity is None
                else r.inventory_quantity,
                "sold_7d": "" if r.sold_7d is None else r.sold_7d,
                "sold_30d": "" if r.sold_30d is None else r.sold_30d,
                "sold_60d": "" if r.sold_60d is None else r.sold_60d,
            }
        )

    write_csv(
        out_csv,
        out_records,
        fieldnames=[
            "product_id",
            "variant_id",
            "product_title",
            "product_created_at",
            "product_status",
            "product_type",
            "variant_title",
            "sku",
            "barcode",
            "price",
            "compare_at_price",
            "cost",
            "inventory_quantity",
            "sold_7d",
            "sold_30d",
            "sold_60d",
        ],
    )

    return variants

