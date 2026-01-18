#!/usr/bin/env python3
"""
CLI entry point for correlation checking.

Run via cron after news scraper completes to detect
whale trades that precede related news articles.

Usage:
    python3 check_correlations.py [--lookback MINUTES] [--min-confidence LEVEL] [--test]

Examples:
    # Standard run (last 15 minutes of articles)
    python3 check_correlations.py

    # Check last hour of articles
    python3 check_correlations.py --lookback 60

    # Only alert on high confidence matches
    python3 check_correlations.py --min-confidence high

    # Test webhook connectivity
    python3 check_correlations.py --test
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from correlation.checker import CorrelationChecker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Check for correlations between whale trades and news articles"
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=15,
        help="How far back to look for articles (minutes, default: 15)",
    )
    parser.add_argument(
        "--trade-window",
        type=int,
        default=48,
        help="How far back to look for trades (hours, default: 48)",
    )
    parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default="low",
        help="Minimum confidence level to alert on (default: low)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send a test message to verify webhook connectivity",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


async def test_webhook(webhook_url: str) -> bool:
    """Test webhook connectivity."""
    from correlation.discord import CorrelationDiscordAlerter

    alerter = CorrelationDiscordAlerter(webhook_url)
    await alerter.init()

    try:
        success = await alerter.send_test_message()
        if success:
            print("Webhook test successful!")
        else:
            print("Webhook test failed - check logs for details")
        return success
    finally:
        await alerter.close()


async def main():
    load_dotenv()

    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get webhook URL
    webhook_url = os.getenv("CORRELATION_WEBHOOK_URL")
    if not webhook_url:
        logger.error("CORRELATION_WEBHOOK_URL not set in .env")
        sys.exit(1)

    # Test mode
    if args.test:
        success = await test_webhook(webhook_url)
        sys.exit(0 if success else 1)

    # Get database paths
    news_db = Path(os.getenv(
        "NEWS_DB_PATH",
        "/var/lib/news-scraper/articles.db"
    )).expanduser()

    scanner_db = Path(os.getenv(
        "SCANNER_DB_PATH",
        "/var/lib/polymarket-scanner/polymarket_whales.db"
    )).expanduser()

    # Validate paths
    if not news_db.exists():
        logger.error(f"News database not found at {news_db}")
        sys.exit(1)

    if not scanner_db.exists():
        logger.error(f"Scanner database not found at {scanner_db}")
        sys.exit(1)

    logger.info(f"News DB: {news_db}")
    logger.info(f"Scanner DB: {scanner_db}")

    # Run correlation checker
    checker = CorrelationChecker(
        news_db_path=news_db,
        scanner_db_path=scanner_db,
        discord_webhook_url=webhook_url,
    )

    result = await checker.run(
        lookback_minutes=args.lookback,
        trade_window_hours=args.trade_window,
        min_confidence=args.min_confidence,
    )

    # Output summary
    print(f"\nCorrelation check complete:")
    print(f"  Articles checked: {result.get('articles_checked', 0)}")
    print(f"  Trades checked: {result.get('trades_checked', 0)}")
    print(f"  New matches found: {result.get('new_matches', 0)}")
    print(f"  Alerts sent: {result.get('alerts_sent', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
