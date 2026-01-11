#!/usr/bin/env python3
"""
Database cleanup script - deletes old resolved trades to manage storage.

Unresolved trades are always kept (needed for P&L calculation).
Wallet aggregate stats (wins, losses, realized_pnl) are preserved.

Usage:
    python3 scripts/cleanup.py                    # Use default 30 days
    python3 scripts/cleanup.py --days 60          # Keep 60 days
    python3 scripts/cleanup.py --dry-run          # Preview without deleting

Recommended: Run daily via cron or systemd timer.
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "polymarket_whales.db")
DEFAULT_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", 30))


async def run_cleanup(retention_days: int, dry_run: bool = False):
    """Run the cleanup process."""
    db = Database(DATABASE_PATH)

    if dry_run:
        print(f"DRY RUN - No data will be deleted")
        print(f"Would delete resolved trades older than {retention_days} days")
        print()

        # Just show current stats
        await db.init()
        import aiosqlite
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM whale_trades WHERE trade_won IS NOT NULL AND timestamp < ?",
                (cutoff,),
            )
            row = await cursor.fetchone()
            would_delete = row[0] if row else 0

            cursor = await conn.execute("SELECT COUNT(*) FROM whale_trades")
            row = await cursor.fetchone()
            total_trades = row[0] if row else 0

            cursor = await conn.execute(
                "SELECT COUNT(*) FROM whale_trades WHERE trade_won IS NULL"
            )
            row = await cursor.fetchone()
            unresolved = row[0] if row else 0

        print(f"Current state:")
        print(f"  Total trades:      {total_trades}")
        print(f"  Unresolved trades: {unresolved}")
        print(f"  Would delete:      {would_delete}")
        print(f"  Would remain:      {total_trades - would_delete}")
        return

    print(f"Running cleanup (retention: {retention_days} days)...")
    await db.init()

    result = await db.cleanup_old_trades(retention_days)

    print(f"Cleanup complete:")
    print(f"  Deleted trades:    {result['deleted_trades']}")
    print(f"  Remaining trades:  {result['remaining_trades']}")
    print(f"  Unresolved trades: {result['unresolved_trades']}")
    print(f"  Total wallets:     {result['total_wallets']}")
    print(f"  Cutoff date:       {result['cutoff_date'][:10]}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up old resolved trades from the database"
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Keep trades from the last N days (default: {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview what would be deleted without actually deleting",
    )

    args = parser.parse_args()

    asyncio.run(run_cleanup(args.days, args.dry_run))


if __name__ == "__main__":
    main()
