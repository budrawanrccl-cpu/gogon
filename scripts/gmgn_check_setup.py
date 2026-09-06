"""Sanity-check your .env / config for the gmgn.ai smart-money screener,
and optionally do a live connectivity check.

Usage: python scripts/gmgn_check_setup.py [--live]
"""
from __future__ import annotations

import os
import sys

# Allow running this script directly (e.g. `python scripts/gmgn_check_setup.py`)
# by making sure the project root (containing the `gmgn` package) is on
# sys.path, regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gmgn.config import load_settings


def main() -> int:
    try:
        settings = load_settings()
    except Exception as e:
        print(f"[FAIL] Could not load configuration: {e}")
        return 1

    print("Configuration loaded OK.")
    print(f"  Chain:                  {settings.chain}")
    print(f"  API base URL:           {settings.api.base_url}")
    print(f"  Cookie set:             {'yes' if settings.api.cookie else 'no'}")
    print(f"  Poll interval:          {settings.poll_interval_seconds}s")
    print(f"  Min smart wallets:      {settings.screener.min_smart_wallets}")
    print(f"  Min net buy USD:        ${settings.screener.min_net_buy_usd:,.0f}")
    print(f"  Min liquidity USD:      ${settings.screener.min_liquidity_usd:,.0f}")
    print(f"  Required tags:          {settings.screener.required_tags}")
    print(f"  Alert cooldown:         {settings.notify.cooldown_minutes}m")
    print(f"  Telegram configured:    {'yes' if settings.notify.telegram_bot_token else 'no'}")
    print(f"  Discord configured:     {'yes' if settings.notify.discord_webhook_url else 'no'}")

    if "--live" in sys.argv:
        print("\nAttempting a live connectivity check against gmgn.ai...")
        try:
            from gmgn.client import GmgnApiError, GmgnClient

            client = GmgnClient(settings.api)
            pairs = client.get_new_pairs(settings.chain, limit=5)
            print(f"[OK] Fetched {len(pairs)} new pair(s) from gmgn.ai.")
            for p in pairs[:5]:
                print(f"       {p.symbol or p.address} | liquidity=${p.liquidity_usd:,.0f}")
        except GmgnApiError as e:
            print(f"[FAIL] {e}")
            print(
                "\nThis is expected if gmgn.ai's Cloudflare protection blocked the request, "
                "or if the undocumented endpoint/field names have changed. See the comments "
                "in gmgn/client.py and try setting GMGN_COOKIE / GMGN_USER_AGENT in .env."
            )
            return 1
        except Exception as e:
            print(f"[FAIL] Unexpected error: {e}")
            return 1
    else:
        print("\nSkipping live connectivity check (pass --live to try it).")
        print(
            "Note: gmgn.ai has no official public API. If --live fails with a 403, "
            "set GMGN_COOKIE in .env to a cf_clearance/session cookie from a real "
            "browser session, or update GMGN_USER_AGENT."
        )

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
