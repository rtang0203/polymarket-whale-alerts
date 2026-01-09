import logging
from typing import Optional

import aiohttp

from .database import Database

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"

# Rate limit: 75 req/10s for /trades, 200 req/10s general
# We add small delays between requests to stay well under limits


class WalletEnricher:
    """
    Fetches wallet history and leaderboard stats from Polymarket APIs.
    Uses database caching to avoid repeated API calls for the same wallet.
    """

    def __init__(self, db: Database):
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None

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

    async def enrich(self, wallet_address: str) -> dict:
        """
        Get wallet data, fetching from API if cache is stale.

        Returns dict with:
            - trade_count: number of trades from API
            - leaderboard_rank: rank on leaderboard (if any)
            - pnl: profit/loss from leaderboard
            - volume: total volume from leaderboard
            - api_data_fresh: whether the data was freshly fetched
        """
        # Check if we have fresh cached data
        wallet = await self.db.get_wallet(wallet_address)
        if wallet and wallet.get("api_data_fresh"):
            logger.debug(f"Using cached data for {wallet_address[:10]}...")
            return wallet

        # Fetch fresh data from API
        logger.info(f"Fetching API data for {wallet_address[:10]}...")
        api_data = {}

        # Get trade history count
        # Note: API returns max 100 trades, so 100 means "100+"
        trades = await self._fetch_trades(wallet_address)
        if trades is None:
            # API call failed - don't set trade_count (leave as unknown)
            api_data["trade_count"] = None
        else:
            api_data["trade_count"] = len(trades)

        # Get leaderboard stats
        leaderboard = await self._fetch_leaderboard(wallet_address)
        if leaderboard:
            rank = leaderboard.get("rank")
            api_data["leaderboard_rank"] = int(rank) if rank else None
            api_data["pnl"] = leaderboard.get("pnl")
            api_data["volume"] = leaderboard.get("vol")

        # Update database
        await self.db.upsert_wallet(wallet_address, api_data)

        # Return combined data
        if wallet:
            wallet.update(api_data)
            wallet["api_data_fresh"] = True
            return wallet

        api_data["api_data_fresh"] = True
        return api_data

    async def _fetch_trades(self, wallet: str) -> Optional[list]:
        """
        Fetch recent trades for a wallet.

        GET /trades?user={wallet}&limit=100

        Rate limit: 75 requests / 10 seconds
        """
        url = f"{DATA_API_BASE}/trades"
        params = {"user": wallet, "limit": 100}

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    logger.warning(f"Rate limited on /trades for {wallet[:10]}...")
                else:
                    logger.warning(
                        f"Error fetching trades for {wallet[:10]}...: {resp.status}"
                    )
        except Exception as e:
            logger.error(f"Exception fetching trades for {wallet[:10]}...: {e}")

        return None

    async def _fetch_leaderboard(self, wallet: str) -> Optional[dict]:
        """
        Fetch leaderboard stats for a wallet.

        GET /v1/leaderboard?user={wallet}

        Returns the first entry if the user is on the leaderboard, None otherwise.
        """
        url = f"{DATA_API_BASE}/v1/leaderboard"
        params = {"user": wallet}

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return data[0]
                elif resp.status == 429:
                    logger.warning(f"Rate limited on /leaderboard for {wallet[:10]}...")
                else:
                    logger.debug(
                        f"No leaderboard data for {wallet[:10]}...: {resp.status}"
                    )
        except Exception as e:
            logger.error(f"Exception fetching leaderboard for {wallet[:10]}...: {e}")

        return None

    async def fetch_trades_raw(self, wallet: str) -> Optional[list]:
        """
        Public method to fetch raw trade data for a wallet.
        Useful for testing API connectivity.
        """
        return await self._fetch_trades(wallet)

    async def fetch_leaderboard_raw(self, wallet: str) -> Optional[dict]:
        """
        Public method to fetch raw leaderboard data for a wallet.
        Useful for testing API connectivity.
        """
        return await self._fetch_leaderboard(wallet)
