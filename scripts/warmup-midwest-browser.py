"""One-time Midwest Cards browser warmup — pass Cloudflare and save cookies to profile."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.midwest_browser import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    MWC_HOME,
    is_cloudflare_page,
    launch_midwest_context,
    wait_past_cloudflare,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Midwest Cards in a persistent browser profile and wait for Cloudflare clearance",
    )
    parser.add_argument("--headed", action="store_true", required=True)
    parser.add_argument("--browser-profile", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--channel", default="chrome", help='Default "chrome"; try "msedge" if Chrome fails')
    parser.add_argument("--timeout-ms", type=int, default=300_000, help="Wait up to 5 minutes for manual CF")
    args = parser.parse_args()

    profile_dir = Path(args.browser_profile)
    channel = args.channel.strip() or None
    print(f"Profile: {profile_dir}", file=sys.stderr)
    print(f"Opening {MWC_HOME} — complete Cloudflare if prompted, then leave the tab on Midwest Cards.", file=sys.stderr)

    with sync_playwright() as p:
        context = launch_midwest_context(
            p,
            headed=args.headed,
            profile_dir=profile_dir,
            channel=channel,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(MWC_HOME, wait_until="domcontentloaded", timeout=args.timeout_ms)
            ok = wait_past_cloudflare(
                page,
                args.timeout_ms,
                manual=True,
                label="homepage",
            )
            if ok:
                print("Cloudflare cleared. Profile saved — scraper runs should reuse this session.", file=sys.stderr)
            else:
                print("Still on Cloudflare after timeout. Retry or check the browser window.", file=sys.stderr)
                sys.exit(1)
            if is_cloudflare_page(page):
                sys.exit(1)
            input("Press Enter to close the browser...")
        finally:
            context.close()


if __name__ == "__main__":
    main()
