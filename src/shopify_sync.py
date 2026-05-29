from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from .shopify_client import ShopifyError, _parse_link_header, _shopify_headers
from .utils import normalize_upc, parse_money, read_csv_dicts


@dataclass(frozen=True)
class OfferLine:
    offer_id: str
    status: str
    dealer: str
    created_at: str
    title: str
    upc: Optional[str]
    qty: int
    unit_price: Optional[float]
    per_box_unit_price: Optional[float]
    unit_of_measure: Optional[str]
    case_qty_boxes: Optional[int]
    tracking_number: Optional[str]


def sync_dealernet_offers_to_shopify(
    *,
    offers_csv: Path,
    mode: str,
    dry_run: bool = True,
    create_missing_products: bool = True,
    accepted_only: bool = True,
    max_offers: Optional[int] = None,
) -> dict[str, int]:
    load_dotenv()
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    version = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()
    if not domain or not token:
        raise ShopifyError("Missing SHOPIFY_SHOP_DOMAIN or SHOPIFY_ACCESS_TOKEN in .env")

    mode_key = mode.strip().lower()
    if mode_key not in {"purchase", "sale"}:
        raise ShopifyError("mode must be one of: purchase, sale")

    session = requests.Session()
    session.headers.update(_shopify_headers(token))

    by_barcode, by_title = _fetch_variant_index(session, domain, version)
    rows = read_csv_dicts(offers_csv)
    lines = _load_offer_lines(rows, accepted_only=accepted_only)
    by_offer: dict[str, list[OfferLine]] = defaultdict(list)
    for line in lines:
        by_offer[line.offer_id].append(line)

    if max_offers and max_offers > 0:
        limited: dict[str, list[OfferLine]] = {}
        for offer_id in list(by_offer.keys())[:max_offers]:
            limited[offer_id] = by_offer[offer_id]
        by_offer = limited

    stats = {
        "offers_seen": len(by_offer),
        "offers_created": 0,
        "offers_updated": 0,
        "lines_seen": len(lines),
        "lines_mapped": 0,
        "products_created": 0,
        "lines_skipped_missing_product": 0,
        "lines_skipped_uncertain_case_qty": 0,
        "offers_skipped_no_lines": 0,
    }

    for offer_id, offer_lines in by_offer.items():
        line_items: list[dict] = []
        case_expansion_notes: list[str] = []
        dealer = ""
        created_at = ""
        tracking = ""

        for line in offer_lines:
            dealer = dealer or line.dealer
            created_at = created_at or line.created_at
            tracking = tracking or (line.tracking_number or "")

            is_case = (line.unit_of_measure or "").strip().lower() == "case"
            effective_qty = line.qty
            effective_unit_price = line.unit_price
            if is_case:
                if line.case_qty_boxes and line.case_qty_boxes > 0:
                    effective_qty = line.qty * line.case_qty_boxes
                    effective_unit_price = (
                        line.per_box_unit_price if line.per_box_unit_price is not None else line.unit_price
                    )
                    price_note = (
                        f" @ ${effective_unit_price}/box" if effective_unit_price is not None else ""
                    )
                    case_expansion_notes.append(
                        f"{line.qty} case = {effective_qty} boxes{price_note} ({line.title})"
                    )
                else:
                    stats["lines_skipped_uncertain_case_qty"] += 1
                    continue

            variant_id = _match_variant(line, by_barcode, by_title)
            if not variant_id and create_missing_products and line.title:
                created_variant_id = _create_variant_for_line(
                    session=session,
                    domain=domain,
                    version=version,
                    line=line,
                    dry_run=dry_run,
                    unit_price=effective_unit_price,
                )
                if created_variant_id:
                    variant_id = created_variant_id
                    stats["products_created"] += 1
                    _index_variant(by_barcode, by_title, line, variant_id)

            if not variant_id:
                stats["lines_skipped_missing_product"] += 1
                continue

            line_item = {"variant_id": int(variant_id), "quantity": effective_qty}
            price = (
                effective_unit_price
                if effective_unit_price is not None
                else (line.per_box_unit_price if line.per_box_unit_price is not None else line.unit_price)
            )
            if price is not None:
                line_item["price"] = str(price)
            line_items.append(line_item)
            stats["lines_mapped"] += 1

        if not line_items:
            stats["offers_skipped_no_lines"] += 1
            continue

        note = f"Dealernet offer {offer_id} ({mode_key})"
        if dealer:
            note += f" | Dealer: {dealer}"
        if created_at:
            note += f" | Created: {created_at}"
        if tracking:
            note += f" | Tracking: {tracking}"
        if case_expansion_notes:
            note += f" | Case expansion: {'; '.join(case_expansion_notes)}"
        tags = _dealernet_tags(mode_key=mode_key, offer_id=offer_id, status=offer_lines[0].status, tracking=tracking)

        if mode_key == "purchase":
            existing_draft_id = _find_existing_draft_order_id(session, domain, version, offer_id)
            if existing_draft_id:
                _update_draft_order_metadata(
                    session=session,
                    domain=domain,
                    version=version,
                    draft_order_id=existing_draft_id,
                    note=note,
                    tags=tags,
                    dry_run=dry_run,
                )
                stats["offers_updated"] += 1
                continue
            _create_draft_order(session, domain, version, offer_id, line_items, note, tags, dry_run)
        else:
            existing_order_id = _find_existing_order_id(session, domain, version, offer_id)
            if existing_order_id:
                _update_order_metadata(
                    session=session,
                    domain=domain,
                    version=version,
                    order_id=existing_order_id,
                    note=note,
                    tags=tags,
                    dry_run=dry_run,
                )
                stats["offers_updated"] += 1
                continue
            _create_order(session, domain, version, offer_id, line_items, note, tags, dry_run)
        stats["offers_created"] += 1

    return stats


def _load_offer_lines(rows: list[dict[str, str]], *, accepted_only: bool) -> list[OfferLine]:
    out: list[OfferLine] = []
    for row in rows:
        offer_id = str(row.get("offer_id") or "").strip()
        if not offer_id:
            continue
        status = str(row.get("status") or "").strip()
        if accepted_only and status.upper() != "ACCEPTED":
            continue
        try:
            qty = int(float(str(row.get("qty") or "0").strip()))
        except ValueError:
            qty = 0
        if qty <= 0:
            continue
        case_qty_raw = str(
            row.get("case_qty_boxes") or row.get("case_qty") or ""
        ).strip()
        case_qty_boxes: Optional[int] = None
        if case_qty_raw:
            try:
                parsed_case_qty = int(float(case_qty_raw))
                if parsed_case_qty > 0:
                    case_qty_boxes = parsed_case_qty
            except ValueError:
                case_qty_boxes = None
        out.append(
            OfferLine(
                offer_id=offer_id,
                status=status,
                dealer=str(row.get("dealer") or "").strip(),
                created_at=str(row.get("created_at") or "").strip(),
                title=str(row.get("title") or "").strip(),
                upc=normalize_upc(row.get("upc") or None),
                qty=qty,
                unit_price=parse_money(row.get("unit_price")),
                per_box_unit_price=parse_money(row.get("per_box_unit_price")),
                unit_of_measure=str(
                    row.get("unit_of_measure") or row.get("unitOfMeasure") or ""
                ).strip()
                or None,
                case_qty_boxes=case_qty_boxes,
                tracking_number=str(row.get("tracking_number") or "").strip() or None,
            )
        )
    return out


def _fetch_variant_index(
    session: requests.Session, domain: str, version: str
) -> tuple[dict[str, str], dict[str, str]]:
    by_barcode: dict[str, str] = {}
    by_title: dict[str, str] = {}
    url: Optional[str] = f"https://{domain}/admin/api/{version}/products.json"
    params = {"limit": 250, "fields": "id,title,variants"}
    first = True
    while url:
        resp = session.get(url, params=params if first else None, timeout=60)
        first = False
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify products fetch failed {resp.status_code}: {resp.text[:300]}")
        for product in (resp.json().get("products", []) or []):
            product_title = str(product.get("title") or "").strip()
            for variant in (product.get("variants", []) or []):
                variant_id = str(variant.get("id") or "").strip()
                if not variant_id:
                    continue
                barcode = normalize_upc(variant.get("barcode") or None)
                if barcode and barcode not in by_barcode:
                    by_barcode[barcode] = variant_id
                key = _norm_title(product_title)
                if key and key not in by_title:
                    by_title[key] = variant_id
        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")
    return by_barcode, by_title


def _match_variant(line: OfferLine, by_barcode: dict[str, str], by_title: dict[str, str]) -> Optional[str]:
    if line.upc and line.upc in by_barcode:
        return by_barcode[line.upc]
    key = _norm_title(line.title)
    if key and key in by_title:
        return by_title[key]
    return None


def _index_variant(by_barcode: dict[str, str], by_title: dict[str, str], line: OfferLine, variant_id: str) -> None:
    if line.upc:
        by_barcode[line.upc] = variant_id
    key = _norm_title(line.title)
    if key:
        by_title[key] = variant_id


def _create_variant_for_line(
    *,
    session: requests.Session,
    domain: str,
    version: str,
    line: OfferLine,
    dry_run: bool,
    unit_price: Optional[float] = None,
) -> Optional[str]:
    if dry_run:
        return None
    price = (
        unit_price
        if unit_price is not None
        else (line.per_box_unit_price if line.per_box_unit_price is not None else line.unit_price)
    )
    payload = {
        "product": {
            "title": line.title,
            "product_type": "Sports Cards",
            "tags": "dealernet,auto-created",
            "variants": [
                {
                    "title": "Default Title",
                    "barcode": line.upc or "",
                    "sku": f"DNX-{line.upc}" if line.upc else "",
                    "price": str(price) if price is not None else "0.00",
                }
            ],
        }
    }
    resp = session.post(f"https://{domain}/admin/api/{version}/products.json", json=payload, timeout=60)
    if resp.status_code not in {200, 201}:
        raise ShopifyError(f"Shopify product create failed {resp.status_code}: {resp.text[:300]}")
    product = resp.json().get("product") or {}
    variants = product.get("variants", []) or []
    if not variants:
        return None
    return str((variants[0] or {}).get("id") or "").strip() or None


def _create_draft_order(
    session: requests.Session,
    domain: str,
    version: str,
    offer_id: str,
    line_items: list[dict],
    note: str,
    tags: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    payload = {
        "draft_order": {
            "line_items": line_items,
            "note": note,
            "tags": tags or f"dealernet,purchase,offer-{offer_id}",
        }
    }
    resp = session.post(
        f"https://{domain}/admin/api/{version}/draft_orders.json",
        json=payload,
        timeout=60,
    )
    if resp.status_code not in {200, 201, 202}:
        raise ShopifyError(f"Shopify draft order create failed {resp.status_code}: {resp.text[:300]}")


def _create_order(
    session: requests.Session,
    domain: str,
    version: str,
    offer_id: str,
    line_items: list[dict],
    note: str,
    tags: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    payload = {
        "order": {
            "line_items": line_items,
            "note": note,
            "tags": tags or f"dealernet,sale,offer-{offer_id}",
            "financial_status": "paid",
            "inventory_behaviour": "decrement_ignoring_policy",
            "send_receipt": False,
            "send_fulfillment_receipt": False,
        }
    }
    resp = session.post(
        f"https://{domain}/admin/api/{version}/orders.json",
        json=payload,
        timeout=60,
    )
    if resp.status_code not in {200, 201, 202}:
        raise ShopifyError(f"Shopify order create failed {resp.status_code}: {resp.text[:300]}")


def _norm_title(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _dealernet_tags(*, mode_key: str, offer_id: str, status: str, tracking: str) -> str:
    out = [f"dealernet,{mode_key},offer-{offer_id}"]
    s = (status or "").strip().lower().replace(" ", "-")
    if s:
        out.append(f"dealernet-status-{s}")
    if tracking:
        if mode_key == "purchase":
            out.append("dealernet-in-transit")
        out.append("dealernet-has-tracking")
    elif mode_key == "purchase":
        out.append("dealernet-awaiting-receipt")
    return ",".join(out)


def _has_offer_tag(tags: str, offer_id: str) -> bool:
    needle = f"offer-{offer_id}".strip().lower()
    for t in (tags or "").split(","):
        if t.strip().lower() == needle:
            return True
    return False


def _find_existing_draft_order_id(
    session: requests.Session, domain: str, version: str, offer_id: str
) -> Optional[str]:
    url: Optional[str] = f"https://{domain}/admin/api/{version}/draft_orders.json"
    params = {"limit": 250, "fields": "id,tags"}
    first = True
    while url:
        resp = session.get(url, params=params if first else None, timeout=60)
        first = False
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify draft order fetch failed {resp.status_code}: {resp.text[:300]}")
        for draft in (resp.json().get("draft_orders", []) or []):
            did = str(draft.get("id") or "").strip()
            if did and _has_offer_tag(str(draft.get("tags") or ""), offer_id):
                return did
        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")
    return None


def _find_existing_order_id(
    session: requests.Session, domain: str, version: str, offer_id: str
) -> Optional[str]:
    url: Optional[str] = f"https://{domain}/admin/api/{version}/orders.json"
    params = {"status": "any", "limit": 250, "fields": "id,tags"}
    first = True
    while url:
        resp = session.get(url, params=params if first else None, timeout=60)
        first = False
        if resp.status_code != 200:
            raise ShopifyError(f"Shopify order fetch failed {resp.status_code}: {resp.text[:300]}")
        for order in (resp.json().get("orders", []) or []):
            oid = str(order.get("id") or "").strip()
            if oid and _has_offer_tag(str(order.get("tags") or ""), offer_id):
                return oid
        links = _parse_link_header(resp.headers.get("Link"))
        url = links.get("next")
    return None


def _update_draft_order_metadata(
    *,
    session: requests.Session,
    domain: str,
    version: str,
    draft_order_id: str,
    note: str,
    tags: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    payload = {"draft_order": {"id": int(draft_order_id), "note": note, "tags": tags}}
    resp = session.put(
        f"https://{domain}/admin/api/{version}/draft_orders/{draft_order_id}.json",
        json=payload,
        timeout=60,
    )
    if resp.status_code not in {200, 201, 202}:
        raise ShopifyError(f"Shopify draft order update failed {resp.status_code}: {resp.text[:300]}")


def _update_order_metadata(
    *,
    session: requests.Session,
    domain: str,
    version: str,
    order_id: str,
    note: str,
    tags: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    payload = {"order": {"id": int(order_id), "note": note, "tags": tags}}
    resp = session.put(
        f"https://{domain}/admin/api/{version}/orders/{order_id}.json",
        json=payload,
        timeout=60,
    )
    if resp.status_code not in {200, 201, 202}:
        raise ShopifyError(f"Shopify order update failed {resp.status_code}: {resp.text[:300]}")

