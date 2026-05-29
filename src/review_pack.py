from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

from .utils import read_csv_dicts, write_csv


def _bucket_rank(bucket: str) -> int:
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return order.get((bucket or "").strip().lower(), 9)


def _safe_int(v: str | None) -> int:
    try:
        return int(str(v or "0").strip() or "0")
    except ValueError:
        return 0


def _admin_url(shop_domain: str, product_id: str, variant_id: str) -> str:
    domain = shop_domain.replace("https://", "").replace("http://", "").strip("/")
    if not domain or not product_id or not variant_id:
        return ""
    return f"https://{domain}/admin/products/{product_id}/variants/{variant_id}"


def build_review_pack(
    *,
    matches_csv: Path,
    out_dir: Path,
    min_bucket: str = "high",
    top_n: int = 200,
) -> dict[str, str]:
    rows = read_csv_dicts(matches_csv)
    out_dir.mkdir(parents=True, exist_ok=True)
    min_rank = _bucket_rank(min_bucket)

    filtered = [
        r
        for r in rows
        if _bucket_rank(r.get("priority_bucket", "")) <= min_rank
        and (r.get("match_type") or "") in {"exact_upc", "fuzzy_title"}
    ]
    filtered.sort(
        key=lambda r: (
            _bucket_rank(r.get("priority_bucket", "")),
            -_safe_int(r.get("priority_score")),
        )
    )
    filtered = filtered[:top_n]

    load_dotenv()
    shop_domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
    for r in filtered:
        r["shopify_admin_url"] = _admin_url(
            shop_domain=shop_domain,
            product_id=(r.get("shopify_product_id") or "").strip(),
            variant_id=(r.get("shopify_variant_id") or "").strip(),
        )

    # CSV for operations review / bulk action prep.
    review_csv = out_dir / "review_priority.csv"
    write_csv(
        review_csv,
        filtered,
        fieldnames=[
            "priority_bucket",
            "priority_score",
            "action",
            "rationale",
            "supplier_title",
            "supplier_upc",
            "supplier_high_buy",
            "supplier_low_sell",
            "shopify_title",
            "shopify_product_type",
            "shopify_product_id",
            "shopify_variant_id",
            "shopify_price",
            "shopify_cost",
            "shopify_inventory_quantity",
            "sold_7d",
            "sold_30d",
            "sold_60d",
            "suggested_price",
            "shopify_admin_url",
        ],
    )

    # CSV focused on pricing updates only.
    price_update_csv = out_dir / "shopify_price_update_candidates.csv"
    price_rows = [
        {
            "shopify_product_id": r.get("shopify_product_id", ""),
            "shopify_variant_id": r.get("shopify_variant_id", ""),
            "shopify_title": r.get("shopify_title", ""),
            "current_price": r.get("shopify_price", ""),
            "suggested_price": r.get("suggested_price", ""),
            "priority_bucket": r.get("priority_bucket", ""),
            "priority_score": r.get("priority_score", ""),
            "action": r.get("action", ""),
            "rationale": r.get("rationale", ""),
            "shopify_admin_url": r.get("shopify_admin_url", ""),
        }
        for r in filtered
        if (r.get("action") or "") in {"raise_price", "lower_price"}
    ]
    write_csv(
        price_update_csv,
        price_rows,
        fieldnames=[
            "shopify_product_id",
            "shopify_variant_id",
            "shopify_title",
            "current_price",
            "suggested_price",
            "priority_bucket",
            "priority_score",
            "action",
            "rationale",
            "shopify_admin_url",
        ],
    )

    # Email-ready HTML summary grouped by category/product_type.
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in filtered:
        k = (r.get("shopify_product_type") or "Uncategorized").strip() or "Uncategorized"
        by_type[k].append(r)

    bucket_counts = Counter((r.get("priority_bucket") or "").strip().lower() for r in filtered)
    action_counts = Counter((r.get("action") or "").strip().lower() for r in filtered)

    def color_for_bucket(bucket: str) -> str:
        b = (bucket or "").lower()
        if b == "urgent":
            return "#ffdddd"
        if b == "high":
            return "#fff3cd"
        if b == "medium":
            return "#e6f0ff"
        return "#f5f5f5"

    html_parts = [
        "<html><body style='font-family:Arial,sans-serif;'>",
        "<h2>Pricing Review Summary</h2>",
        f"<p>Total prioritized rows: <b>{len(filtered)}</b> (min bucket: {min_bucket})</p>",
        "<h3>Priority Buckets</h3><ul>",
    ]
    for b in ["urgent", "high", "medium", "low"]:
        html_parts.append(f"<li><b>{b.title()}</b>: {bucket_counts.get(b, 0)}</li>")
    html_parts.append("</ul><h3>Actions</h3><ul>")
    for a, c in action_counts.most_common():
        html_parts.append(f"<li><b>{a}</b>: {c}</li>")
    html_parts.append("</ul>")

    for product_type, items in sorted(by_type.items(), key=lambda kv: kv[0].lower()):
        html_parts.append(f"<h3>{product_type} ({len(items)})</h3>")
        html_parts.append(
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%;'>"
        )
        html_parts.append(
            "<tr><th>Priority</th><th>Action</th><th>Title</th><th>UPC</th>"
            "<th>Current</th><th>Suggested</th><th>Inv</th><th>Sold30d</th><th>Link</th></tr>"
        )
        for r in items[:50]:
            bucket = r.get("priority_bucket", "")
            bg = color_for_bucket(bucket)
            html_parts.append(
                "<tr>"
                f"<td style='background:{bg};'><b>{bucket}</b> ({r.get('priority_score','')})</td>"
                f"<td>{r.get('action','')}</td>"
                f"<td>{r.get('shopify_title','')}</td>"
                f"<td>{r.get('supplier_upc','')}</td>"
                f"<td>{r.get('shopify_price','')}</td>"
                f"<td>{r.get('suggested_price','')}</td>"
                f"<td>{r.get('shopify_inventory_quantity','')}</td>"
                f"<td>{r.get('sold_30d','')}</td>"
                f"<td><a href='{r.get('shopify_admin_url','')}'>Open</a></td>"
                "</tr>"
            )
        html_parts.append("</table>")

    html_parts.append("</body></html>")
    html_path = out_dir / "email_summary.html"
    html_path.write_text("".join(html_parts), encoding="utf-8")

    return {
        "review_csv": str(review_csv),
        "price_update_csv": str(price_update_csv),
        "email_html": str(html_path),
    }

