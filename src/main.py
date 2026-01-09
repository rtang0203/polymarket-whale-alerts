import asyncio
import logging
import os
import signal
import sys
from datetime import datetime

from dotenv import load_dotenv

from .database import Database
from .discord_bot import DiscordAlerter
from .enrichment import WalletEnricher
from .resolution import ResolutionTracker
from .websocket_client import RTDSClient

# Load environment variables
load_dotenv()

# Configuration
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
WHALE_THRESHOLD = int(os.getenv("WHALE_THRESHOLD_USD", 10000))
RESOLUTION_INTERVAL = float(os.getenv("RESOLUTION_CHECK_INTERVAL_HOURS", 1))
DATABASE_PATH = os.getenv("DATABASE_PATH", "polymarket_whales.db")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class WhaleScanner:
    """
    Main application class that orchestrates all components:
    - WebSocket client for real-time trade monitoring
    - Wallet enrichment for trader context
    - Discord alerts for notifications
    - Resolution tracking for P&L calculation
    """

    def __init__(self):
        self.db = Database(DATABASE_PATH)
        self.enricher = WalletEnricher(self.db)
        self.alerter = DiscordAlerter(WEBHOOK_URL) if WEBHOOK_URL else None
        self.resolution_tracker = ResolutionTracker(self.db)
        self.ws_client = RTDSClient(
            on_whale_trade=self.handle_whale_trade,
            whale_threshold=WHALE_THRESHOLD,
        )
        self._shutdown = False
        self._tasks = []  # Track tasks for cancellation

    async def start(self):
        """Initialize all components and start the scanner."""
        logger.info("Initializing Polymarket Whale Scanner...")

        # Initialize database
        await self.db.init()
        logger.info(f"Database initialized: {DATABASE_PATH}")

        # Initialize HTTP clients
        await self.enricher.init()

        if self.alerter:
            await self.alerter.init()
            # Send test message to verify webhook
            if await self.alerter.send_test_message():
                logger.info("Discord webhook verified")
            else:
                logger.warning("Discord webhook test failed - alerts may not work")
        else:
            logger.warning("No DISCORD_WEBHOOK_URL configured - alerts disabled")

        await self.resolution_tracker.init()

        logger.info(
            f"Starting whale scanner (threshold: ${WHALE_THRESHOLD:,}, "
            f"resolution check: every {RESOLUTION_INTERVAL}h)"
        )

        # Run WebSocket client and resolution tracker concurrently
        # Track tasks so we can cancel them on shutdown
        self._tasks = [
            asyncio.create_task(self.ws_client.connect()),
            asyncio.create_task(self.run_resolution_tracker()),
            asyncio.create_task(self.periodic_stats_log()),
        ]

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")
        finally:
            await self.cleanup()

    async def run_resolution_tracker(self):
        """Run the resolution tracker as a background task."""
        interval_seconds = RESOLUTION_INTERVAL * 3600

        # Wait a bit before first check
        await asyncio.sleep(60)

        while not self._shutdown:
            try:
                resolved = await self.resolution_tracker.check_resolutions()
                if resolved > 0:
                    logger.info(f"Resolution check: updated {resolved} trades")
            except Exception as e:
                logger.error(f"Resolution check error: {e}")

            await asyncio.sleep(interval_seconds)

    async def periodic_stats_log(self):
        """Log statistics periodically."""
        while not self._shutdown:
            await asyncio.sleep(300)  # Every 5 minutes
            stats = self.ws_client.get_stats()
            logger.info(
                f"Stats: {stats['messages_received']} messages, "
                f"{stats['whale_trades_detected']} whales, "
                f"connected={stats['connected']}"
            )

    async def handle_whale_trade(self, trade: dict):
        """
        Handle a whale trade detected by the WebSocket client.

        1. Log the trade
        2. Enrich with wallet data from API
        3. Record to database
        4. Send Discord alert
        """
        wallet = trade.get("proxyWallet")
        if not wallet:
            logger.warning("Trade missing proxyWallet field")
            return

        trade_value = trade.get("size", 0) * trade.get("price", 0)
        market_title = trade.get("title", "Unknown")

        logger.info(f"Processing whale trade: ${trade_value:,.0f} on {market_title}")

        try:
            # Enrich with wallet data from Polymarket API
            wallet_stats = await self.enricher.enrich(wallet)

            # Record trade to database
            await self.db.record_whale_trade(
                {
                    "wallet_address": wallet,
                    "condition_id": trade.get("conditionId"),
                    "event_slug": trade.get("eventSlug"),
                    "market_title": market_title,
                    "outcome": trade.get("outcome"),
                    "side": trade.get("side"),
                    "size": trade.get("size"),
                    "price": trade.get("price"),
                    "tx_hash": trade.get("transactionHash"),
                    "timestamp": self._format_timestamp(trade.get("timestamp")),
                }
            )

            # Get updated wallet stats (now includes our tracked data)
            wallet_data = await self.db.get_wallet(wallet)

            # Merge API stats with our tracked stats for the alert
            combined_stats = {
                "trade_count": wallet_stats.get("trade_count", 0),
                "leaderboard_rank": wallet_stats.get("leaderboard_rank"),
                "pnl": wallet_stats.get("pnl"),
                "volume": wallet_stats.get("volume"),
                # Our tracked data
                "total_whale_trades": (
                    wallet_data.get("total_whale_trades", 0) if wallet_data else 0
                ),
                "wins": wallet_data.get("wins", 0) if wallet_data else 0,
                "losses": wallet_data.get("losses", 0) if wallet_data else 0,
                "realized_pnl": wallet_data.get("realized_pnl", 0) if wallet_data else 0,
            }

            # Send Discord alert
            if self.alerter:
                await self.alerter.send_alert(trade, combined_stats)

        except Exception as e:
            logger.error(f"Error processing whale trade: {e}")

    def _format_timestamp(self, ts) -> str:
        """Format timestamp from various formats to ISO string."""
        if ts is None:
            return datetime.now().isoformat()

        # Handle Unix milliseconds
        if isinstance(ts, (int, float)):
            if ts > 1e12:  # Milliseconds
                ts = ts / 1000
            return datetime.fromtimestamp(ts).isoformat()

        # Already a string
        return str(ts)

    async def cleanup(self):
        """Clean up resources."""
        logger.info("Shutting down...")
        self._shutdown = True
        self.ws_client.stop()
        self.resolution_tracker.stop()
        await self.enricher.close()
        if self.alerter:
            await self.alerter.close()
        await self.resolution_tracker.close()
        logger.info("Shutdown complete")

    def handle_signal(self, sig):
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig}, initiating shutdown...")
        self._shutdown = True
        self.ws_client.stop()
        # Cancel all running tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()


async def main():
    """Entry point for the scanner."""
    if not WEBHOOK_URL:
        logger.warning(
            "DISCORD_WEBHOOK_URL not set. Running without Discord alerts.\n"
            "Set it in .env file or environment to enable alerts."
        )

    scanner = WhaleScanner()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: scanner.handle_signal(s))

    await scanner.start()


if __name__ == "__main__":
    asyncio.run(main())
