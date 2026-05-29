from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


UPC_RE = re.compile(r"\d+")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_upc(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = "".join(UPC_RE.findall(str(value)))
    return digits or None


def upcs_from_cell(text: Optional[str]) -> list[str]:
    """
    One table cell may list multiple UPCs (e.g. <br> between codes). Playwright usually yields newlines.
    Returns distinct normalized codes (typical UPC-A/EAN-13 lengths); empty if none parse cleanly.
    """
    if not text or not str(text).strip():
        return []
    s = str(text).strip()
    parts = re.split(r"[\n\r,;]+", s)
    seen: dict[str, None] = {}
    out: list[str] = []
    for p in parts:
        u = normalize_upc(p.strip())
        if u and 8 <= len(u) <= 14 and u not in seen:
            seen[u] = None
            out.append(u)
    return out


def parse_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in {"", ".", "-", "-."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_parent_dir(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return [dict(row) for row in r]

