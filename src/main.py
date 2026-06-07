from __future__ import annotations

from pathlib import Path

import typer

from .config import load_supplier_config
from .alerts import add_price_alerts_from_csv
from .matcher import (
    load_shopify_variants_csv,
    load_supplier_csv,
    match_supplier_to_shopify,
    write_matches_csv,
)
from .shopify_client import fetch_shopify_variants
from .shopify_sync import sync_dealernet_offers_to_shopify
from .shopify_tiers import export_upc_tier_csvs
from .supplier_scraper import scrape_supplier_table, test_supplier_login
from .review_pack import build_review_pack


app = typer.Typer(no_args_is_help=True)


def _resolve_profile_config(profile: str) -> tuple[str, Path]:
    profile_key = profile.strip().lower()
    profile_to_config = {
        "daily": Path("configs/dealernetx.daily.yaml"),
        "oos": Path("configs/dealernetx.oos.yaml"),
        "weekly": Path("configs/dealernetx.weekly.yaml"),
    }
    supplier_config = profile_to_config.get(profile_key)
    if supplier_config is None:
        raise typer.BadParameter("profile must be one of: daily, oos, weekly")
    if not supplier_config.exists():
        raise typer.BadParameter(f"Config not found for profile '{profile_key}': {supplier_config}")
    return profile_key, supplier_config


def _profile_output_paths(out_dir: Path, profile_key: str) -> tuple[Path, Path, Path]:
    supplier_csv = out_dir / f"supplier_{profile_key}.csv"
    shopify_csv = out_dir / "shopify_variants.csv"
    matches_csv = out_dir / f"matches_{profile_key}.csv"
    return supplier_csv, shopify_csv, matches_csv


def _run_pipeline(
    *,
    supplier_config: Path,
    supplier_csv: Path,
    shopify_csv: Path,
    matches_csv: Path,
    fuzzy_threshold: float,
) -> None:
    cfg = load_supplier_config(supplier_config)
    scrape_supplier_table(cfg, supplier_csv)
    fetch_shopify_variants(shopify_csv)

    supplier_rows = load_supplier_csv(supplier_csv)
    shopify_rows = load_shopify_variants_csv(shopify_csv)
    matches = match_supplier_to_shopify(
        supplier_rows,
        shopify_rows,
        fuzzy_threshold=fuzzy_threshold,
    )
    write_matches_csv(matches_csv, matches)


@app.command("test-login")
def test_login(
    supplier_config: Path = typer.Option(..., exists=True, dir_okay=False),
    headed: bool = typer.Option(
        False,
        "--headed",
        help="Show the browser window (useful if login fails and you want to see what the site does).",
    ),
):
    """
    Verify Dealernet (or any supplier) login using credentials from .env only.
    Put SUPPLIER_USERNAME and SUPPLIER_PASSWORD in .env — not in the YAML config.
    """
    cfg = load_supplier_config(supplier_config)
    url = test_supplier_login(cfg, headed=headed)
    typer.secho(f"Login OK. Final URL: {url}", fg=typer.colors.GREEN)


@app.command("scrape-supplier")
def scrape_supplier(
    supplier_config: Path = typer.Option(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., dir_okay=False),
):
    cfg = load_supplier_config(supplier_config)
    scrape_supplier_table(cfg, out)
    typer.echo(f"Wrote supplier rows to {out}")


@app.command("fetch-shopify")
def fetch_shopify(
    out: Path = typer.Option(..., dir_okay=False),
):
    fetch_shopify_variants(out)
    typer.echo(f"Wrote Shopify variants to {out}")


@app.command("export-upc-tiers")
def export_upc_tiers(
    out_dir: Path = typer.Option(
        Path("data"),
        help="Writes upcs_in_stock.csv, upcs_out_of_stock.csv, upcs_all_barcodes.csv (header: upc)",
    ),
):
    """
    Pull Shopify variants + inventory levels and write three UPC lists for tiered Dealernet schedules:

    - **in_stock** — total available > 0 (typical “daily” list)
    - **out_of_stock** — barcode in catalog but available == 0 (“every other day”)
    - **all_barcodes** — distinct barcodes for a weekly full pass

    Requires Admin API scopes: read_products, read_inventory.
    """
    stats = export_upc_tier_csvs(out_dir)
    typer.echo(f"Wrote {out_dir / 'upcs_in_stock.csv'} ({stats['in_stock_upcs']} UPCs)")
    typer.echo(f"Wrote {out_dir / 'upcs_out_of_stock.csv'} ({stats['out_of_stock_upcs']} UPCs)")
    typer.echo(f"Wrote {out_dir / 'upcs_all_barcodes.csv'} ({stats['all_distinct_upcs']} UPCs)")


@app.command("match")
def match_cmd(
    supplier: Path = typer.Option(..., exists=True, dir_okay=False),
    shopify: Path = typer.Option(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., dir_okay=False),
    fuzzy_threshold: float = typer.Option(90.0),
):
    supplier_rows = load_supplier_csv(supplier)
    shopify_rows = load_shopify_variants_csv(shopify)
    matches = match_supplier_to_shopify(
        supplier_rows,
        shopify_rows,
        fuzzy_threshold=fuzzy_threshold,
    )
    write_matches_csv(out, matches)
    typer.echo(f"Wrote matches to {out}")


@app.command("run")
def run_all(
    supplier_config: Path = typer.Option(..., exists=True, dir_okay=False),
    out_dir: Path = typer.Option(Path("out")),
    fuzzy_threshold: float = typer.Option(90.0),
):
    out_dir.mkdir(parents=True, exist_ok=True)
    supplier_csv = out_dir / "supplier.csv"
    shopify_csv = out_dir / "shopify_variants.csv"
    matches_csv = out_dir / "matches.csv"

    _run_pipeline(
        supplier_config=supplier_config,
        supplier_csv=supplier_csv,
        shopify_csv=shopify_csv,
        matches_csv=matches_csv,
        fuzzy_threshold=fuzzy_threshold,
    )

    typer.echo(f"Supplier: {supplier_csv}")
    typer.echo(f"Shopify:  {shopify_csv}")
    typer.echo(f"Matches:  {matches_csv}")


@app.command("run-profile")
def run_profile(
    profile: str = typer.Option("daily", help="daily|oos|weekly"),
    out_dir: Path = typer.Option(Path("out")),
    fuzzy_threshold: float = typer.Option(90.0),
    refresh_upcs: bool = typer.Option(
        True,
        help="Refresh tiered UPC CSVs from Shopify before running scrape/match.",
    ),
):
    """
    Single command for schedule-ready profiles.
    """
    profile_key, supplier_config = _resolve_profile_config(profile)

    out_dir.mkdir(parents=True, exist_ok=True)
    if refresh_upcs:
        export_upc_tier_csvs(Path("data"))

    supplier_csv, shopify_csv, matches_csv = _profile_output_paths(out_dir, profile_key)

    _run_pipeline(
        supplier_config=supplier_config,
        supplier_csv=supplier_csv,
        shopify_csv=shopify_csv,
        matches_csv=matches_csv,
        fuzzy_threshold=fuzzy_threshold,
    )

    typer.echo(f"Profile:  {profile_key}")
    typer.echo(f"Config:   {supplier_config}")
    typer.echo(f"Supplier: {supplier_csv}")
    typer.echo(f"Shopify:  {shopify_csv}")
    typer.echo(f"Matches:  {matches_csv}")


@app.command("run-profile-review")
def run_profile_review(
    profile: str = typer.Option("daily", help="daily|oos|weekly"),
    out_dir: Path = typer.Option(Path("out")),
    review_out_dir: Path = typer.Option(Path("out/review")),
    fuzzy_threshold: float = typer.Option(90.0),
    refresh_upcs: bool = typer.Option(True),
    min_bucket: str = typer.Option("high", help="urgent|high|medium|low"),
    top_n: int = typer.Option(250),
):
    """
    One command: run profile pipeline, then build review/email pack.
    """
    profile_key, supplier_config = _resolve_profile_config(profile)
    out_dir.mkdir(parents=True, exist_ok=True)
    if refresh_upcs:
        export_upc_tier_csvs(Path("data"))

    supplier_csv, shopify_csv, matches_csv = _profile_output_paths(out_dir, profile_key)
    _run_pipeline(
        supplier_config=supplier_config,
        supplier_csv=supplier_csv,
        shopify_csv=shopify_csv,
        matches_csv=matches_csv,
        fuzzy_threshold=fuzzy_threshold,
    )

    outputs = build_review_pack(
        matches_csv=matches_csv,
        out_dir=review_out_dir,
        min_bucket=min_bucket,
        top_n=top_n,
    )

    typer.echo(f"Profile:       {profile_key}")
    typer.echo(f"Matches:       {matches_csv}")
    typer.echo(f"Review CSV:    {outputs['review_csv']}")
    typer.echo(f"Price CSV:     {outputs['price_update_csv']}")
    typer.echo(f"Email HTML:    {outputs['email_html']}")


@app.command("add-alerts")
def add_alerts(
    supplier_config: Path = typer.Option(..., exists=True, dir_okay=False),
    matches: Path = typer.Option(..., exists=True, dir_okay=False),
    alert_type: str = typer.Option("Wanted", help="Typically 'Wanted' or 'For Sale'"),
    match_types: str = typer.Option("exact_upc,fuzzy_title", help="Comma-separated match types"),
    price_source: str = typer.Option("suggested", help="supplier|shopify|suggested"),
    min_priority_bucket: str = typer.Option("high", help="urgent|high|medium|low"),
    actions: str = typer.Option(
        "restock_opportunity,margin_risk,lower_price,raise_price",
        help="Comma-separated actions to include; empty means all actions.",
    ),
    require_in_stock: bool = typer.Option(False, help="If true, only include Shopify inventory > 0."),
    min_sold_30d: int = typer.Option(0, help="Minimum sold_30d to include."),
    max_alerts: int = typer.Option(150, help="Maximum alerts per run (0 means unlimited)."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Dry-run by default. Use --execute to actually submit alerts.",
    ),
):
    cfg = load_supplier_config(supplier_config)
    stats = add_price_alerts_from_csv(
        cfg,
        matches_csv=matches,
        match_types={s.strip() for s in match_types.split(",") if s.strip()},
        alert_type=alert_type,
        price_source=price_source,
        min_priority_bucket=min_priority_bucket,
        allowed_actions={s.strip() for s in actions.split(",") if s.strip()},
        require_in_stock=require_in_stock,
        min_sold_30d=min_sold_30d,
        max_alerts=max_alerts,
        dry_run=dry_run,
    )
    typer.echo(f"Rows total:       {stats.get('rows_total', 0)}")
    typer.echo(f"Rows filtered:    {stats.get('rows_filtered_out', 0)}")
    typer.echo(f"Skipped no URL:   {stats.get('skipped_no_product_url', 0)}")
    typer.echo(f"Alerts planned:   {stats.get('planned', 0)}")
    typer.echo(f"Alerts attempted: {stats.get('attempted', 0)}")
    typer.echo(f"Alerts added:     {stats.get('added', 0)}")
    typer.echo(f"Alerts rejected:  {stats.get('rejected', 0)}")


@app.command("build-review-pack")
def build_review_pack_cmd(
    matches: Path = typer.Option(..., exists=True, dir_okay=False),
    out_dir: Path = typer.Option(Path("out/review")),
    min_bucket: str = typer.Option("high", help="urgent|high|medium|low"),
    top_n: int = typer.Option(200, help="Max rows in review outputs"),
):
    outputs = build_review_pack(
        matches_csv=matches,
        out_dir=out_dir,
        min_bucket=min_bucket,
        top_n=top_n,
    )
    typer.echo(f"Review CSV:      {outputs['review_csv']}")
    typer.echo(f"Price CSV:       {outputs['price_update_csv']}")
    typer.echo(f"Email HTML:      {outputs['email_html']}")


@app.command("sync-dealernet-shopify")
def sync_dealernet_shopify_cmd(
    offers_csv: Path = typer.Option(..., exists=True, dir_okay=False),
    mode: str = typer.Option("purchase", help="purchase|sale"),
    dry_run: bool = typer.Option(
        True,
        help="Plan only (default). Use --no-dry-run to execute writes in Shopify.",
    ),
    create_missing_products: bool = typer.Option(
        True,
        help="Create product/variant if no existing Shopify match is found.",
    ),
    accepted_only: bool = typer.Option(
        True,
        help="Only sync rows where status=ACCEPTED.",
    ),
    max_offers: int = typer.Option(
        0,
        help="Optional cap for testing. 0 means no limit.",
    ),
):
    stats = sync_dealernet_offers_to_shopify(
        offers_csv=offers_csv,
        mode=mode,
        dry_run=dry_run,
        create_missing_products=create_missing_products,
        accepted_only=accepted_only,
        max_offers=(max_offers if max_offers > 0 else None),
    )
    typer.echo(f"Mode:                    {mode}")
    typer.echo(f"Dry run:                 {dry_run}")
    typer.echo(f"Offers seen:             {stats.get('offers_seen', 0)}")
    typer.echo(f"Offers created:          {stats.get('offers_created', 0)}")
    typer.echo(f"Offers updated:          {stats.get('offers_updated', 0)}")
    typer.echo(f"Lines seen:              {stats.get('lines_seen', 0)}")
    typer.echo(f"Lines mapped:            {stats.get('lines_mapped', 0)}")
    typer.echo(f"Products created:        {stats.get('products_created', 0)}")
    typer.echo(f"Lines missing product:   {stats.get('lines_skipped_missing_product', 0)}")
    typer.echo(
        f"Lines skipped (case qty): {stats.get('lines_skipped_uncertain_case_qty', 0)}"
    )
    typer.echo(f"Offers skipped/no lines: {stats.get('offers_skipped_no_lines', 0)}")


if __name__ == "__main__":
    app()

