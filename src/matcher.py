from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from .models import MatchResult, ShopifyVariantRow, SupplierRow
from .utils import normalize_upc, parse_money, read_csv_dicts, write_csv


def _shopify_display_title(v: ShopifyVariantRow) -> str:
    if v.variant_title and v.variant_title.lower() not in {"default title", "default"}:
        return f"{v.product_title} - {v.variant_title}"
    return v.product_title


def _recommend_action(
    *,
    shopify_price: Optional[float],
    shopify_cost: Optional[float],
    inventory_qty: Optional[int],
    high_buy: Optional[float],
    low_sell: Optional[float],
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    if shopify_price is None:
        return ("review", None, "Missing Shopify price")
    if high_buy is None and low_sell is None:
        return (None, None, None)

    # Midpoint between bid/ask as simple market anchor.
    market_anchor = None
    if high_buy is not None and low_sell is not None:
        market_anchor = (high_buy + low_sell) / 2.0
    elif low_sell is not None:
        market_anchor = low_sell
    else:
        market_anchor = high_buy

    if market_anchor is None:
        return (None, None, None)

    suggested_price = round(max(market_anchor, 0.0), 2)
    delta = suggested_price - shopify_price

    if delta >= 5:
        action = "raise_price"
        rationale = f"Market supports +${delta:.2f} vs current price."
    elif delta <= -5:
        action = "lower_price"
        rationale = f"Current price is ${abs(delta):.2f} above market anchor."
    else:
        action = "hold"
        rationale = "Current price near market anchor."

    if inventory_qty is not None and inventory_qty <= 2 and high_buy and low_sell:
        spread = low_sell - high_buy
        if spread >= 5:
            action = "restock_opportunity"
            rationale = f"Low stock and ${spread:.2f} bid/ask spread."

    if shopify_cost is not None and shopify_price <= shopify_cost:
        action = "margin_risk"
        rationale = "Shopify price is at/below cost."

    return (action, suggested_price, rationale)


def _compute_priority(
    *,
    action: Optional[str],
    sold_7d: Optional[int],
    sold_30d: Optional[int],
    sold_60d: Optional[int],
    inventory_qty: Optional[int],
    product_created_at: Optional[str],
) -> tuple[int, str]:
    score = 0
    action_weight = {
        "restock_opportunity": 45,
        "margin_risk": 40,
        "lower_price": 30,
        "raise_price": 25,
        "hold": 10,
        "review": 20,
    }
    score += action_weight.get(action or "", 0)

    s7 = int(sold_7d or 0)
    s30 = int(sold_30d or 0)
    s60 = int(sold_60d or 0)
    score += min(s7 * 4, 20)
    score += min(s30 * 2, 25)
    score += min(s60, 10)

    if inventory_qty is not None:
        if inventory_qty <= 2:
            score += 15
        elif inventory_qty <= 5:
            score += 8

    if product_created_at:
        try:
            created = datetime.fromisoformat(product_created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days <= 30:
                score += 12
            elif age_days <= 90:
                score += 8
            elif age_days <= 180:
                score += 4
        except ValueError:
            pass

    if score >= 70:
        bucket = "urgent"
    elif score >= 45:
        bucket = "high"
    elif score >= 25:
        bucket = "medium"
    else:
        bucket = "low"
    return score, bucket


def _compute_margin_sales_metrics(
    *,
    shopify_price: Optional[float],
    supplier_price: Optional[float],
    sold_30d: Optional[int],
) -> tuple[Optional[float], Optional[float]]:
    """
    margin_pct: (shopify_price - supplier_price) / shopify_price * 100
    sales_weighted_margin_score: margin_pct * log1p(sold_30d)
    """
    if shopify_price is None or supplier_price is None or shopify_price <= 0:
        return (None, None)
    margin_pct = ((shopify_price - supplier_price) / shopify_price) * 100.0
    s30 = max(int(sold_30d or 0), 0)
    score = margin_pct * math.log1p(s30)
    return (round(margin_pct, 2), round(score, 2))


def match_supplier_to_shopify(
    supplier_rows: list[SupplierRow],
    shopify_variants: list[ShopifyVariantRow],
    *,
    fuzzy_threshold: float = 90.0,
) -> list[MatchResult]:
    # Build UPC index
    upc_to_variant: dict[str, ShopifyVariantRow] = {}
    for v in shopify_variants:
        if v.barcode and v.barcode not in upc_to_variant:
            upc_to_variant[v.barcode] = v

    # Prepare fuzzy candidates
    candidate_titles: list[str] = []
    title_to_variant: dict[str, ShopifyVariantRow] = {}
    for v in shopify_variants:
        t = _shopify_display_title(v).strip()
        if not t:
            continue
        # If duplicates exist, keep the first (good enough for a first pass).
        if t not in title_to_variant:
            title_to_variant[t] = v
            candidate_titles.append(t)

    results: list[MatchResult] = []

    for s in supplier_rows:
        # 1) Exact UPC
        if s.upc:
            v = upc_to_variant.get(normalize_upc(s.upc) or "")
            if v:
                price_delta = None
                if s.supplier_price is not None and v.price is not None:
                    price_delta = v.price - s.supplier_price
                action, suggested_price, rationale = _recommend_action(
                    shopify_price=v.price,
                    shopify_cost=v.cost,
                    inventory_qty=v.inventory_quantity,
                    high_buy=s.supplier_high_buy,
                    low_sell=s.supplier_low_sell,
                )
                priority_score, priority_bucket = _compute_priority(
                    action=action,
                    sold_7d=v.sold_7d,
                    sold_30d=v.sold_30d,
                    sold_60d=v.sold_60d,
                    inventory_qty=v.inventory_quantity,
                    product_created_at=v.product_created_at,
                )
                margin_pct, sales_margin_score = _compute_margin_sales_metrics(
                    shopify_price=v.price,
                    supplier_price=s.supplier_price,
                    sold_30d=v.sold_30d,
                )
                results.append(
                    MatchResult(
                        match_type="exact_upc",
                        confidence=100.0,
                        supplier_upc=s.upc,
                        supplier_title=s.title,
                        supplier_price=s.supplier_price,
                        supplier_high_buy=s.supplier_high_buy,
                        supplier_low_sell=s.supplier_low_sell,
                        shopify_barcode=v.barcode,
                        shopify_title=_shopify_display_title(v),
                        shopify_product_id=v.product_id,
                        shopify_variant_id=v.variant_id,
                        shopify_product_type=v.product_type,
                        shopify_price=v.price,
                        shopify_cost=v.cost,
                        shopify_inventory_quantity=v.inventory_quantity,
                        shopify_product_created_at=v.product_created_at,
                        sold_7d=v.sold_7d,
                        sold_30d=v.sold_30d,
                        sold_60d=v.sold_60d,
                        price_delta=price_delta,
                        margin_pct=margin_pct,
                        sales_weighted_margin_score=sales_margin_score,
                        action=action,
                        suggested_price=suggested_price,
                        priority_score=priority_score,
                        priority_bucket=priority_bucket,
                        rationale=rationale,
                    )
                )
                continue

        # 2) Fuzzy title fallback
        query = (s.title or "").strip()
        if query and candidate_titles:
            match = process.extractOne(
                query,
                candidate_titles,
                scorer=fuzz.token_set_ratio,
            )
            if match:
                matched_title, score, _idx = match
                if score >= fuzzy_threshold:
                    v = title_to_variant.get(matched_title)
                    price_delta = None
                    if v and s.supplier_price is not None and v.price is not None:
                        price_delta = v.price - s.supplier_price
                    action, suggested_price, rationale = _recommend_action(
                        shopify_price=v.price if v else None,
                        shopify_cost=v.cost if v else None,
                        inventory_qty=v.inventory_quantity if v else None,
                        high_buy=s.supplier_high_buy,
                        low_sell=s.supplier_low_sell,
                    )
                    priority_score, priority_bucket = _compute_priority(
                        action=action,
                        sold_7d=v.sold_7d if v else None,
                        sold_30d=v.sold_30d if v else None,
                        sold_60d=v.sold_60d if v else None,
                        inventory_qty=v.inventory_quantity if v else None,
                        product_created_at=v.product_created_at if v else None,
                    )
                    margin_pct, sales_margin_score = _compute_margin_sales_metrics(
                        shopify_price=v.price if v else None,
                        supplier_price=s.supplier_price,
                        sold_30d=v.sold_30d if v else None,
                    )
                    results.append(
                        MatchResult(
                            match_type="fuzzy_title",
                            confidence=float(score),
                            supplier_upc=s.upc,
                            supplier_title=s.title,
                            supplier_price=s.supplier_price,
                            supplier_high_buy=s.supplier_high_buy,
                            supplier_low_sell=s.supplier_low_sell,
                            shopify_barcode=v.barcode if v else None,
                            shopify_title=_shopify_display_title(v) if v else matched_title,
                            shopify_product_id=v.product_id if v else None,
                            shopify_variant_id=v.variant_id if v else None,
                            shopify_product_type=v.product_type if v else None,
                            shopify_price=v.price if v else None,
                            shopify_cost=v.cost if v else None,
                            shopify_inventory_quantity=v.inventory_quantity if v else None,
                            shopify_product_created_at=v.product_created_at if v else None,
                            sold_7d=v.sold_7d if v else None,
                            sold_30d=v.sold_30d if v else None,
                            sold_60d=v.sold_60d if v else None,
                            price_delta=price_delta,
                            margin_pct=margin_pct,
                            sales_weighted_margin_score=sales_margin_score,
                            action=action,
                            suggested_price=suggested_price,
                            priority_score=priority_score,
                            priority_bucket=priority_bucket,
                            rationale=rationale,
                            notes="UPC missing or not found; matched by title",
                        )
                    )
                    continue

        # 3) Unmatched
        results.append(
            MatchResult(
                match_type="unmatched",
                confidence=0.0,
                supplier_upc=s.upc,
                supplier_title=s.title,
                supplier_price=s.supplier_price,
                supplier_high_buy=s.supplier_high_buy,
                supplier_low_sell=s.supplier_low_sell,
                shopify_barcode=None,
                shopify_title=None,
                shopify_product_id=None,
                shopify_variant_id=None,
                shopify_product_type=None,
                shopify_price=None,
                shopify_cost=None,
                shopify_inventory_quantity=None,
                shopify_product_created_at=None,
                sold_7d=None,
                sold_30d=None,
                sold_60d=None,
                price_delta=None,
                margin_pct=None,
                sales_weighted_margin_score=None,
                priority_score=0,
                priority_bucket="low",
            )
        )

    return results


def load_supplier_csv(path: Path) -> list[SupplierRow]:
    rows = read_csv_dicts(path)
    out: list[SupplierRow] = []
    # Keep scraped_at as string in raw; not needed for matching.
    from datetime import datetime

    for r in rows:
        out.append(
            SupplierRow(
                upc=normalize_upc(r.get("upc") or None),
                title=(r.get("title") or "").strip(),
                supplier_price=parse_money(r.get("supplier_price")),
                supplier_high_buy=parse_money(r.get("supplier_high_buy")),
                supplier_low_sell=parse_money(r.get("supplier_low_sell")),
                raw=r,
                scraped_at=datetime.fromisoformat((r.get("scraped_at") or "1970-01-01T00:00:00+00:00")),
            )
        )
    return out


def load_shopify_variants_csv(path: Path) -> list[ShopifyVariantRow]:
    rows = read_csv_dicts(path)
    out: list[ShopifyVariantRow] = []
    for r in rows:
        out.append(
            ShopifyVariantRow(
                product_id=str(r.get("product_id") or ""),
                variant_id=str(r.get("variant_id") or ""),
                product_title=str(r.get("product_title") or ""),
                product_created_at=(r.get("product_created_at") or "").strip() or None,
                product_status=(r.get("product_status") or "").strip() or None,
                product_type=(r.get("product_type") or "").strip() or None,
                variant_title=str(r.get("variant_title") or ""),
                sku=(r.get("sku") or "").strip() or None,
                barcode=normalize_upc((r.get("barcode") or "").strip() or None),
                price=parse_money(r.get("price")),
                compare_at_price=parse_money(r.get("compare_at_price")),
                cost=parse_money(r.get("cost")),
                inventory_quantity=int(r["inventory_quantity"])
                if str(r.get("inventory_quantity") or "").strip()
                else None,
                sold_7d=int(r["sold_7d"]) if str(r.get("sold_7d") or "").strip() else 0,
                sold_30d=int(r["sold_30d"]) if str(r.get("sold_30d") or "").strip() else 0,
                sold_60d=int(r["sold_60d"]) if str(r.get("sold_60d") or "").strip() else 0,
                inventory_item_id=None,
                raw=r,
            )
        )
    return out


def write_matches_csv(path: Path, matches: list[MatchResult]) -> None:
    out_rows = []
    for m in matches:
        out_rows.append(
            {
                "match_type": m.match_type,
                "confidence": m.confidence,
                "supplier_upc": m.supplier_upc or "",
                "supplier_title": m.supplier_title,
                "supplier_price": "" if m.supplier_price is None else m.supplier_price,
                "supplier_high_buy": "" if m.supplier_high_buy is None else m.supplier_high_buy,
                "supplier_low_sell": "" if m.supplier_low_sell is None else m.supplier_low_sell,
                "shopify_barcode": m.shopify_barcode or "",
                "shopify_title": m.shopify_title or "",
                "shopify_product_id": m.shopify_product_id or "",
                "shopify_variant_id": m.shopify_variant_id or "",
                "shopify_product_type": m.shopify_product_type or "",
                "shopify_price": "" if m.shopify_price is None else m.shopify_price,
                "shopify_cost": "" if m.shopify_cost is None else m.shopify_cost,
                "shopify_inventory_quantity": ""
                if m.shopify_inventory_quantity is None
                else m.shopify_inventory_quantity,
                "shopify_product_created_at": m.shopify_product_created_at or "",
                "sold_7d": "" if m.sold_7d is None else m.sold_7d,
                "sold_30d": "" if m.sold_30d is None else m.sold_30d,
                "sold_60d": "" if m.sold_60d is None else m.sold_60d,
                "price_delta": "" if m.price_delta is None else m.price_delta,
                "margin_pct": "" if m.margin_pct is None else m.margin_pct,
                "sales_weighted_margin_score": ""
                if m.sales_weighted_margin_score is None
                else m.sales_weighted_margin_score,
                "suggested_price": "" if m.suggested_price is None else m.suggested_price,
                "action": m.action or "",
                "priority_score": "" if m.priority_score is None else m.priority_score,
                "priority_bucket": m.priority_bucket or "",
                "rationale": m.rationale or "",
                "notes": m.notes or "",
            }
        )
    write_csv(
        path,
        out_rows,
        fieldnames=[
            "match_type",
            "confidence",
            "supplier_upc",
            "supplier_title",
            "supplier_price",
            "supplier_high_buy",
            "supplier_low_sell",
            "shopify_barcode",
            "shopify_title",
            "shopify_product_id",
            "shopify_variant_id",
            "shopify_product_type",
            "shopify_price",
            "shopify_cost",
            "shopify_inventory_quantity",
            "shopify_product_created_at",
            "sold_7d",
            "sold_30d",
            "sold_60d",
            "price_delta",
            "margin_pct",
            "sales_weighted_margin_score",
            "suggested_price",
            "action",
            "priority_score",
            "priority_bucket",
            "rationale",
            "notes",
        ],
    )

