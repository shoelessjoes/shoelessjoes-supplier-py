"""One-time Midwest Cards browser warmup — prefer launch-chrome-for-midwest.ps1 + --cdp-url instead."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.midwest_browser import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    MWC_HOME,
    cdp_setup_instructions,
    close_midwest_session,
    is_cloudflare_page,
    open_midwest_session,
    wait_past_cloudflare,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Midwest Cards (Playwright launch). If CF loops, use launch-chrome-for-midwest.ps1 + --cdp-url.",
    )
    parser.add_argument("--headed", action="store_true", required=True)
    parser.add_argument("--browser-profile", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--timeout-ms", type=int, default=300_000)
    args = parser.parse_args()

    profile_dir = Path(args.browser_profile)
    channel = args.channel.strip() or None
    print(cdp_setup_instructions(profile_dir), file=sys.stderr)
    print(f"\nAttempting Playwright launch anyway...", file=sys.stderr)

    with sync_playwright() as p:
        session = open_midwest_session(
            p,
            headed=args.headed,
            profile_dir=profile_dir,
            channel=channel,
            cdp_url=None,
        )
        page = session.page
        try:
            page.goto(MWC_HOME, wait_until="domcontentloaded", timeout=args.timeout_ms)
            ok = wait_past_cloudflare(page, args.timeout_ms, manual=True, label="homepage")
            if not ok or is_cloudflare_page(page):
                print("\nCF still blocking. Use CDP mode (see instructions above).", file=sys.stderr)
                sys.exit(1)
            print("Cloudflare cleared.", file=sys.stderr)
            input("Press Enter to close the browser...")
        finally:
            close_midwest_session(session)


if __name__ == "__main__":
    main()
