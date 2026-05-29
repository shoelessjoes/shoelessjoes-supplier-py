from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class SupplierRow:
    upc: Optional[str]
    title: str
    supplier_price: Optional[float]
    raw: dict
    scraped_at: datetime
    supplier_high_buy: Optional[float] = None
    supplier_low_sell: Optional[float] = None


@dataclass(frozen=True)
class ShopifyVariantRow:
    product_id: str
    variant_id: str
    product_title: str
    product_created_at: Optional[str]
    product_status: Optional[str]
    product_type: Optional[str]
    variant_title: str
    sku: Optional[str]
    barcode: Optional[str]
    price: Optional[float]
    compare_at_price: Optional[float]
    cost: Optional[float]
    inventory_quantity: Optional[int]
    sold_7d: Optional[int]
    sold_30d: Optional[int]
    sold_60d: Optional[int]
    inventory_item_id: Optional[str]
    raw: dict


@dataclass(frozen=True)
class MatchResult:
    match_type: str  # exact_upc | fuzzy_title | unmatched
    confidence: float
    supplier_upc: Optional[str]
    supplier_title: str
    supplier_price: Optional[float]
    supplier_high_buy: Optional[float]
    supplier_low_sell: Optional[float]
    shopify_barcode: Optional[str]
    shopify_title: Optional[str]
    shopify_product_id: Optional[str]
    shopify_variant_id: Optional[str]
    shopify_product_type: Optional[str]
    shopify_price: Optional[float]
    shopify_cost: Optional[float]
    shopify_inventory_quantity: Optional[int]
    shopify_product_created_at: Optional[str]
    sold_7d: Optional[int]
    sold_30d: Optional[int]
    sold_60d: Optional[int]
    price_delta: Optional[float]
    margin_pct: Optional[float] = None
    sales_weighted_margin_score: Optional[float] = None
    suggested_price: Optional[float] = None
    action: Optional[str] = None
    priority_score: Optional[int] = None
    priority_bucket: Optional[str] = None
    rationale: Optional[str] = None
    notes: Optional[str] = None

