"""Playwright browser helpers for Midwest Cards (Cloudflare-aware)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, Playwright

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[1] / "out" / "mwc-browser-profile"
MWC_HOME = "https://www.midwestcards.com/"


def is_cloudflare_page(page: Page) -> bool:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    if any(
        phrase in title
        for phrase in (
            "just a moment",
            "attention required",
            "please wait",
            "checking your browser",
        )
    ):
        return True
    try:
        if page.locator(
            "#challenge-running, #cf-challenge-running, .cf-turnstile"
        ).count() > 0:
            return True
        if page.locator('iframe[src*="challenges.cloudflare"], iframe[title*="Cloudflare"]').count() > 0:
            return True
    except Exception:
        pass
    return False


def wait_past_cloudflare(
    page: Page,
    timeout_ms: int,
    *,
    manual: bool = False,
    label: str = "",
) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    prompted = False
    while time.monotonic() < deadline:
        try:
            if not is_cloudflare_page(page):
                return True
        except Exception:
            return False
        if manual and not prompted:
            prompted = True
            where = f" ({label})" if label else ""
            print(
                f"Cloudflare challenge{where}. Complete verification in the browser window; waiting up to {timeout_ms // 1000}s...",
                file=sys.stderr,
            )
        try:
            page.wait_for_timeout(2000)
        except Exception:
            return False
    try:
        return not is_cloudflare_page(page)
    except Exception:
        return False


def launch_midwest_context(
    p: Playwright,
    *,
    headed: bool,
    profile_dir: Path,
    channel: Optional[str] = None,
) -> BrowserContext:
    profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {
        "user_data_dir": str(profile_dir),
        "headless": not headed,
        "viewport": {"width": 1366, "height": 900},
        "locale": "en-US",
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if channel:
        kwargs["channel"] = channel
    return p.chromium.launch_persistent_context(**kwargs)
