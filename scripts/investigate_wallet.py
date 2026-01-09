#!/usr/bin/env python3
"""
Utility script to investigate a wallet's data from Polymarket APIs.

Usage:
    python3 scripts/investigate_wallet.py 0xCeC379...7Cb76d
    python3 scripts/investigate_wallet.py --rank 61
"""

import argparse
import asyncio
import sys

import aiohttp

DATA_API_BASE = "https://data-api.polymarket.com"


async def find_wallet_by_rank(session: aiohttp.ClientSession, rank: int) -> str | None:
    """Find wallet address by leaderboard rank."""
    async with session.get(
        f"{DATA_API_BASE}/v1/leaderboard",
        params={"limit": 1, "offset": rank - 1}
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data:
                return data[0].get("proxyWallet")
    return None


async def find_wallet_by_partial(session: aiohttp.ClientSession, partial: str) -> str | None:
    """Search leaderboard for wallet matching partial address."""
    partial_lower = partial.lower().replace("...", "")  # Handle truncated format

    # Search in batches (API returns max ~50 per request)
    for offset in range(0, 5000, 50):
        async with session.get(
            f"{DATA_API_BASE}/v1/leaderboard",
            params={"limit": 50, "offset": offset}
        ) as resp:
            if resp.status != 200:
                break
            data = await resp.json()
            if not data:
                break

            for entry in data:
                wallet = entry.get("proxyWallet", "")
                if wallet.lower().startswith(partial_lower) or partial_lower in wallet.lower():
                    return wallet

        # Progress indicator for long searches
        if offset > 0 and offset % 500 == 0:
            print(f"  Searched {offset} wallets...")

    return None


async def get_leaderboard_data(session: aiohttp.ClientSession, wallet: str) -> dict | None:
    """Fetch leaderboard data for a wallet."""
    async with session.get(
        f"{DATA_API_BASE}/v1/leaderboard",
        params={"user": wallet}
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data:
                return data[0]
    return None


async def get_trades(session: aiohttp.ClientSession, wallet: str, limit: int = 100) -> list:
    """Fetch recent trades for a wallet."""
    async with session.get(
        f"{DATA_API_BASE}/trades",
        params={"user": wallet, "limit": limit}
    ) as resp:
        if resp.status == 200:
            return await resp.json()
    return []


async def investigate(wallet_input: str = None, rank: int = None):
    """Investigate a wallet's data from all API sources."""
    async with aiohttp.ClientSession() as session:
        wallet = None

        # Find wallet address
        if rank:
            print(f"Looking up wallet at rank #{rank}...")
            wallet = await find_wallet_by_rank(session, rank)
        elif wallet_input:
            if len(wallet_input) == 42 and wallet_input.startswith("0x"):
                wallet = wallet_input
            else:
                print(f"Searching for wallet matching '{wallet_input}'...")
                wallet = await find_wallet_by_partial(session, wallet_input)

        if not wallet:
            print("Wallet not found!")
            return

        print(f"\n{'='*60}")
        print(f"Wallet: {wallet}")
        print(f"{'='*60}\n")

        # Get leaderboard data
        print("Leaderboard Data:")
        print("-" * 40)
        leaderboard = await get_leaderboard_data(session, wallet)
        if leaderboard:
            print(f"  Rank:     #{leaderboard.get('rank')}")
            print(f"  Username: {leaderboard.get('userName') or '(none)'}")
            print(f"  Volume:   ${leaderboard.get('vol', 0):,.2f}")
            print(f"  PnL:      ${leaderboard.get('pnl', 0):,.2f}")
            print(f"  Verified: {leaderboard.get('verifiedBadge', False)}")
        else:
            print("  Not on leaderboard")

        # Get trades
        print(f"\nTrade History:")
        print("-" * 40)
        trades = await get_trades(session, wallet)
        print(f"  Total trades returned: {len(trades)}")

        if trades:
            print(f"\n  Recent trades:")
            for i, trade in enumerate(trades[:5]):
                side = trade.get('side', '?')
                size = trade.get('size', 0)
                price = trade.get('price', 0)
                outcome = trade.get('outcome', '?')
                title = trade.get('title', 'Unknown')[:40]
                value = size * price
                print(f"    {i+1}. {side} {size:,.0f} {outcome} @ ${price:.2f} (${value:,.0f}) - {title}...")

        print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Investigate a Polymarket wallet's data"
    )
    parser.add_argument(
        "wallet",
        nargs="?",
        help="Wallet address (full or partial, e.g., '0xCeC379' or '0xCeC379...7Cb76d')"
    )
    parser.add_argument(
        "--rank", "-r",
        type=int,
        help="Look up wallet by leaderboard rank"
    )

    args = parser.parse_args()

    if not args.wallet and not args.rank:
        parser.print_help()
        sys.exit(1)

    asyncio.run(investigate(wallet_input=args.wallet, rank=args.rank))


if __name__ == "__main__":
    main()
