"""
Match parsed_boxes_of_cards.csv to Dealernet supplier_daily.csv via fuzzy search.

Title format:  {year} {name} {sport} {box_type} Box
Search query:  {year} {name} {sport} {box_type}   (no "box" — Dealernet convention)
"""
import argparse
import re
import urllib.parse as up
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

BOX_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"hobby\s+jumbo", "Hobby Jumbo"),
    (r"breakers\s+delight", "Breakers Delight"),
    (r"super\s+jumbo", "Super Jumbo"),
    (r"hobby\s+box", "Hobby"),
    (r"\bhobby\b", "Hobby"),
    (r"mega\s+box", "Mega"),
    (r"\bmega\b", "Mega"),
    (r"blaster\s+box", "Blaster"),
    (r"\bblaster\b", "Blaster"),
    (r"hanger\s+box", "Hanger"),
    (r"\bhanger\b", "Hanger"),
    (r"retail\s+(?:tall\s+)?box", "Retail"),
    (r"\bretail\b", "Retail"),
    (r"value\s+(?:box|pack)", "Value"),
    (r"\bvalue\b", "Value"),
    (r"jumbo\s+box", "Jumbo"),
    (r"\bjumbo\b", "Jumbo"),
    (r"gravity\s+box", "Gravity"),
    (r"tin\s+case", "Tin Case"),
    (r"\btin\b", "Tin"),
    (r"starter\s+deck", "Starter Deck"),
    (r"factory\s+set", "Factory Set"),
    (r"monster\s+box", "Monster"),
    (r"mini\s+box", "Mini"),
    (r"\bset\b", "Set"),
    (r"\bpacks?\b", "Pack"),
    (r"\bbox\b", ""),  # generic "box" with no qualifier
]

YEAR_RE = re.compile(
    r"(?<!\d)"
    r"((?:19|20)\d{2}(?:\s*[-/]\s*\d{2,4})?)"
    r"|"
    r"(\d{2}/\d)"
    r"(?!\d)",
    re.I,
)


def clean_match(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9/ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_year_and_box_type(year_box_col: str) -> tuple[str, str]:
    raw = (year_box_col or "").strip()
    year = ""
    ym = YEAR_RE.search(raw)
    if ym:
        year = (ym.group(1) or ym.group(2) or "").replace(" ", "")

    remainder = YEAR_RE.sub("", raw).strip()
    remainder = re.sub(r"\s+", " ", remainder)

    box_type = ""
    rem_lower = remainder.lower()
    for pattern, label in BOX_TYPE_PATTERNS:
        if re.search(pattern, rem_lower, re.I):
            if label:
                box_type = label
            break

    return year, box_type


def build_full_title(year: str, name: str, sport: str, box_type: str) -> str:
    parts: list[str] = []
    if year:
        parts.append(year)
    parts.append(name.strip())
    parts.append(sport.strip())
    if box_type:
        parts.append(f"{box_type} Box")
    return " ".join(p for p in parts if p)


def build_search_query(year: str, name: str, sport: str, box_type: str) -> str:
    """Dealernet search string — no trailing 'box'."""
    parts: list[str] = []
    if year:
        parts.append(year)
    parts.append(name.strip())
    parts.append(sport.strip())
    if box_type:
        parts.append(box_type)
    return " ".join(p for p in parts if p)


def supplier_search_line(title: str, year: str) -> str:
    """Normalize supplier title for fuzzy compare (drop 'box', tildes)."""
    t = (title or "").replace("~", " ")
    t = re.sub(r"\bbox\b", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    line = f"{year} {t}".strip() if year else t
    return clean_match(line)


def query_arg(url: object, key: str) -> str:
    if pd.isna(url):
        return ""
    parsed = up.urlparse(str(url))
    return str(up.parse_qs(parsed.query).get(key, [""])[0])


def load_and_format_input(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw = raw.rename(
        columns={raw.columns[0]: "name", raw.columns[1]: "year_box_col", raw.columns[2]: "sport"}
    )
    parsed = raw.apply(
        lambda r: pd.Series(parse_year_and_box_type(str(r["year_box_col"]))),
        axis=1,
    )
    raw["year"] = parsed[0]
    raw["box_type"] = parsed[1]
    raw["full_title"] = raw.apply(
        lambda r: build_full_title(r["year"], r["name"], r["sport"], r["box_type"]),
        axis=1,
    )
    raw["search_query"] = raw.apply(
        lambda r: build_search_query(r["year"], r["name"], r["sport"], r["box_type"]),
        axis=1,
    )
    raw["search_query_clean"] = raw["search_query"].apply(clean_match)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/parsed_boxes_of_cards.csv")
    parser.add_argument("--market", default="out/supplier_daily.csv")
    parser.add_argument("--min-score", type=float, default=80.0)
    parser.add_argument("--formatted-out", default="data/parsed_boxes_formatted.csv")
    args = parser.parse_args()

    root = Path(".")
    want = load_and_format_input(root / args.input)
    want.to_csv(root / args.formatted_out, index=False)

    market = pd.read_csv(root / args.market)
    market["supplier_year"] = market["product_url"].apply(lambda u: query_arg(u, "year"))
    market["search_line"] = market.apply(
        lambda r: supplier_search_line(str(r["title"]), str(r["supplier_year"])),
        axis=1,
    )
    choices = market["search_line"].tolist()

    rows: list[dict] = []
    for _, r in want.iterrows():
        q = r["search_query_clean"]
        if not q:
            continue
        hits = process.extract(q, choices, scorer=fuzz.token_set_ratio, limit=5)
        for rank, (_, score, idx) in enumerate(hits, start=1):
            m = market.iloc[idx]
            rows.append(
                {
                    "full_title": r["full_title"],
                    "search_query": r["search_query"],
                    "name": r["name"],
                    "year": r["year"],
                    "box_type": r["box_type"],
                    "sport": r["sport"],
                    "year_box_col": r["year_box_col"],
                    "match_rank": rank,
                    "match_score": round(float(score), 2),
                    "supplier_search_line": m["search_line"],
                    "supplier_title": m["title"],
                    "supplier_year": m["supplier_year"],
                    "supplier_high_buy": m["supplier_high_buy"],
                    "supplier_low_sell": m["supplier_low_sell"],
                    "supplier_price": m["supplier_price"],
                    "product_url": m["product_url"],
                }
            )

    all_df = pd.DataFrame(rows)
    best = (
        all_df.sort_values(["full_title", "match_score"], ascending=[True, False])
        .groupby("full_title", as_index=False)
        .first()
    )
    accepted = best[best["match_score"] >= args.min_score].copy()
    review = best[best["match_score"] < args.min_score].copy()

    out = root / "out"
    all_df.to_csv(out / "parsed_boxes_market_candidates.csv", index=False)
    best.to_csv(out / "parsed_boxes_market_best.csv", index=False)
    accepted.to_csv(out / "parsed_boxes_market_accepted.csv", index=False)
    review.to_csv(out / "parsed_boxes_market_manual_review.csv", index=False)

    print(f"formatted rows -> {args.formatted_out}")
    print(f"unique full_title: {want['full_title'].nunique()} / {len(want)} rows")
    print(f"accepted (>={args.min_score:.0f}): {len(accepted)}")
    print(f"manual review: {len(review)}")
    print("\nSample formatted titles:")
    for t in want["full_title"].drop_duplicates().head(8):
        sq = want.loc[want["full_title"] == t, "search_query"].iloc[0]
        print(f"  title:   {t}")
        print(f"  search:  {sq}")


if __name__ == "__main__":
    main()
