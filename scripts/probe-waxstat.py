"""Quick probe: can we fetch Waxstat release data without Playwright?"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def fetch(url: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)


def main() -> None:
    page_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.waxstat.com/release-dates/june-21-2026-june-27-2026"
    )
    print(f"GET {page_url}")
    try:
        status, body, headers = fetch(page_url)
    except urllib.error.HTTPError as e:
        print(f"FAIL {e.code} {e.reason}")
        sys.exit(1)
    print(f"status={status} cf-ray={headers.get('cf-ray')} server={headers.get('server')}")
    print(f"html bytes={len(body)} angular={body.count('ng-')} upc mentions={body.lower().count('upc')}")

    scripts = re.findall(r'<script[^>]+src="([^"]+)"', body)
    print(f"script tags: {len(scripts)}")
    for s in scripts[:8]:
        print(f"  {s}")

    # Try embedded JSON / gon / window vars
    for label, pat in [
        ("gon", r"gon\s*=\s*(\{.*?\});"),
        ("window.__", r"window\.__[A-Z_]+__\s*=\s*(\{.*?\});"),
    ]:
        m = re.search(pat, body, re.S)
        if m:
            print(f"found {label} json snippet len={len(m.group(1))}")

    # Probe likely Rails/Angular API paths from same host
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', body)
    csrf_token = csrf.group(1) if csrf else ""
    api_paths = [
        "/api/release_dates?start_date=2026-06-21&end_date=2026-06-27",
        "/api/release-dates?start_date=2026-06-21&end_date=2026-06-27",
        "/release_dates.json?start_date=2026-06-21&end_date=2026-06-27",
        "/waxtracker/release_calendar.json",
        "/waxtracker/release-calendar.json",
        "/api/waxtracker/release_calendar",
        "/api/v1/release_dates",
        "/api/v1/products/search?q=series+2+mega",
        "/api/products/search?query=series+2+mega",
    ]
    print("\nAPI probes:")
    for path in api_paths:
        url = "https://www.waxstat.com" + path
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "X-CSRF-Token": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                text = r.read(500).decode("utf-8", "replace")
                print(f"  OK {path} -> {text[:160].replace(chr(10),' ')}")
        except urllib.error.HTTPError as e:
            print(f"  {e.code} {path}")
        except Exception as e:
            print(f"  ERR {path}: {e}")

    # Grep webpack packs for API route strings
    print("\nJS pack route hints:")
    route_hits: set[str] = set()
    for script in scripts:
        if not script.startswith("/packs/js/"):
            continue
        if "runtime" in script or "vendors" in script:
            continue
        js_url = "https://www.waxstat.com" + script
        try:
            _, js, _ = fetch(js_url)
        except Exception as e:
            print(f"  skip {script}: {e}")
            continue
        for m in re.findall(r'["\'](/api/[^"\']+)["\']', js):
            route_hits.add(m)
        for m in re.findall(r'["\'](/waxtracker/[^"\']+)["\']', js):
            route_hits.add(m)
        for m in re.findall(r'release[_-]?dates?[^"\']{0,40}', js, re.I):
            if len(m) < 60:
                route_hits.add(m)
    for h in sorted(route_hits)[:40]:
        print(f"  {h}")


if __name__ == "__main__":
    main()
