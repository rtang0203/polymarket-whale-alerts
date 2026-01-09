import asyncio
import logging
from typing import Optional

import aiohttp

from .database import Database

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class ResolutionTracker:
    """
    Background job to check if markets have resolved and update trade outcomes.

    Queries the Gamma API for market resolution status and calculates P&L
    for whale trades once markets resolve.
    """

    def __init__(self, db: Database):
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False

    async def init(self):
        """Initialize the HTTP session."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "PolymarketWhaleScanner/1.0"},
        )

    async def close(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def check_resolutions(self) -> int:
        """
        Check all unresolved trades and update any that have resolved.

        Returns:
            Number of trades updated
        """
        unresolved = await self.db.get_unresolved_trades()
        if not unresolved:
            logger.debug("No unresolved trades to check")
            return 0

        logger.info(f"Checking {len(unresolved)} markets for resolution...")

        resolved_count = 0
        for market in unresolved:
            condition_id = market["condition_id"]
            if not condition_id:
                continue

            resolution = await self._fetch_market_resolution(condition_id)

            if resolution:
                market_title = market.get("market_title", "Unknown")[:50]
                trades_updated = await self.db.resolve_trades(condition_id, resolution)
                logger.info(
                    f"Market '{market_title}...' resolved {resolution}, "
                    f"updated {trades_updated} trades"
                )
                resolved_count += trades_updated

            # Small delay to avoid hammering the API
            await asyncio.sleep(0.5)

        return resolved_count

    async def _fetch_market_resolution(self, condition_id: str) -> Optional[str]:
        """
        Fetch market from Gamma API and return resolution if resolved.

        Args:
            condition_id: The market's condition ID

        Returns:
            "Yes" / "No" / None (if not resolved)
        """
        url = f"{GAMMA_API_BASE}/markets"
        params = {"condition_id": condition_id}

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug(
                        f"Gamma API returned {resp.status} for {condition_id[:10]}..."
                    )
                    return None

                data = await resp.json()
                if not data or len(data) == 0:
                    return None

                market = data[0]
                return self._extract_resolution(market)

        except Exception as e:
            logger.error(f"Error fetching market {condition_id[:10]}...: {e}")
            return None

    def _extract_resolution(self, market: dict) -> Optional[str]:
        """
        Extract the resolution outcome from a market object.

        The Gamma API structure may vary, so we check multiple fields.
        """
        # Check if market is closed/resolved
        if not (market.get("closed") or market.get("resolved")):
            return None

        # Try to get direct outcome field
        outcome = market.get("outcome")
        if outcome:
            return outcome

        # For binary markets, check outcome prices
        # If one outcome is at 1.0 (or very close), that's the winner
        outcomes = market.get("outcomes", [])
        prices = market.get("outcomePrices", [])

        if prices and outcomes:
            for i, price in enumerate(prices):
                try:
                    price_float = float(price)
                    if price_float >= 0.99:  # Resolved to this outcome
                        if i < len(outcomes):
                            return outcomes[i]
                except (ValueError, TypeError):
                    continue

        # Check for resolvedOutcome field (alternate naming)
        resolved_outcome = market.get("resolvedOutcome")
        if resolved_outcome:
            return resolved_outcome

        return None

    async def run_periodic(self, interval_hours: float = 1.0):
        """
        Run resolution checks periodically.

        Args:
            interval_hours: Hours between checks
        """
        self._running = True
        interval_seconds = interval_hours * 3600

        while self._running:
            try:
                resolved = await self.check_resolutions()
                logger.info(f"Resolution check complete. Updated {resolved} trades.")
            except Exception as e:
                logger.error(f"Resolution check error: {e}")

            await asyncio.sleep(interval_seconds)

    def stop(self):
        """Stop the periodic resolution checker."""
        self._running = False

    async def fetch_market_raw(self, condition_id: str) -> Optional[dict]:
        """
        Public method to fetch raw market data.
        Useful for testing API connectivity.
        """
        url = f"{GAMMA_API_BASE}/markets"
        params = {"condition_id": condition_id}

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return data[0]
        except Exception as e:
            logger.error(f"Error fetching market: {e}")

        return None
