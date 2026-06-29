"""Playwright browser helpers for Midwest Cards (Cloudflare-aware)."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[1] / "out" / "mwc-browser-profile"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
LAUNCH_CHROME_PS1 = Path(__file__).resolve().parents[1] / "scripts" / "launch-chrome-for-midwest.ps1"
MWC_HOME = "https://www.midwestcards.com/"

# Reduce automation signals Playwright sets (Cloudflare Turnstile loops on these).
STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  if (!window.chrome) window.chrome = { runtime: {} };
  const origQuery = window.navigator.permissions.query;
  if (origQuery) {
    window.navigator.permissions.query = (parameters) =>
      parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters);
  }
})();
"""


@dataclass
class MidwestSession:
    context: BrowserContext
    page: Page
    cdp_connected: bool = False
    browser: Optional[Browser] = None


def apply_stealth(context: BrowserContext) -> None:
    context.add_init_script(STEALTH_INIT_SCRIPT)


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
        if page.locator("#challenge-running, #cf-challenge-running, .cf-turnstile").count() > 0:
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
                f"Cloudflare challenge{where}. If the checkbox spins forever, stop and use CDP mode "
                f"(launch-chrome-for-midwest.ps1 + --cdp-url). Waiting up to {timeout_ms // 1000}s...",
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
        "locale": "en-US",
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
        ],
    }
    if headed:
        kwargs["viewport"] = None
    else:
        kwargs["viewport"] = {"width": 1366, "height": 900}
    if channel:
        kwargs["channel"] = channel
    context = p.chromium.launch_persistent_context(**kwargs)
    apply_stealth(context)
    return context


def connect_midwest_cdp(p: Playwright, cdp_url: str) -> MidwestSession:
    browser = p.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    apply_stealth(context)
    page = context.pages[0] if context.pages else context.new_page()
    return MidwestSession(context=context, page=page, cdp_connected=True, browser=browser)


def open_midwest_session(
    p: Playwright,
    *,
    headed: bool,
    profile_dir: Path,
    channel: Optional[str],
    cdp_url: Optional[str],
) -> MidwestSession:
    if cdp_url:
        print(f"Connecting to Chrome via CDP: {cdp_url}", file=sys.stderr)
        return connect_midwest_cdp(p, cdp_url)
    context = launch_midwest_context(
        p,
        headed=headed,
        profile_dir=profile_dir,
        channel=channel,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return MidwestSession(context=context, page=page)


def close_midwest_session(session: MidwestSession) -> None:
    if session.cdp_connected and session.browser:
        session.browser.close()
        return
    session.context.close()


def cdp_setup_instructions(profile_dir: Path, cdp_url: str = DEFAULT_CDP_URL) -> str:
    return f"""
Cloudflare Turnstile often loops when Playwright launches Chrome (automation fingerprint).

Use real Chrome you control manually, then attach the scraper:

  1) Close any Chrome using the Midwest profile.
  2) Run:
       powershell -NoProfile -ExecutionPolicy Bypass -File {LAUNCH_CHROME_PS1}
  3) In that Chrome window, open {MWC_HOME} and pass Cloudflare once.
     (Use normal browsing — do NOT run warmup-midwest-browser.py for this step.)
  4) Leave Chrome open. In a new terminal:
       ... scrape-midwestcards-presells.py --cdp-url {cdp_url} ...

Profile dir: {profile_dir}
""".strip()
