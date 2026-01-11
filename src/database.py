import aiosqlite
from datetime import datetime, timedelta
from typing import Optional

CACHE_TTL_HOURS = 24


def calculate_trade_pnl(
    bet_outcome: str, side: str, size: float, price: float, resolved_outcome: str
) -> tuple[bool, float]:
    """
    Calculate if trade won and P&L.

    Args:
        bet_outcome: YES/NO - what they bet on
        side: BUY/SELL
        size: number of shares
        price: price per share
        resolved_outcome: YES/NO - what market resolved to

    Returns:
        (won: bool, pnl: float)
    """
    bet_yes = bet_outcome.upper() == "YES"
    resolved_yes = resolved_outcome.upper() == "YES"
    is_buy = side.upper() == "BUY"

    # Determine if position profits from YES resolution
    # BUY YES or SELL NO = profits if YES
    # SELL YES or BUY NO = profits if NO
    profits_from_yes = (is_buy and bet_yes) or (not is_buy and not bet_yes)

    won = profits_from_yes == resolved_yes

    # Calculate P&L
    if won:
        if is_buy:
            pnl = size * (1 - price)  # Paid price, received 1
        else:
            pnl = size * price  # Received price, paid 0
    else:
        if is_buy:
            pnl = -size * price  # Paid price, received 0
        else:
            pnl = -size * (1 - price)  # Received price, paid 1

    return won, round(pnl, 2)


class Database:
    def __init__(self, db_path: str = "polymarket_whales.db"):
        self.db_path = db_path

    async def init(self):
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                -- Wallets we've seen making whale trades
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    first_seen_at TEXT,
                    total_whale_trades INTEGER DEFAULT 0,
                    total_whale_volume REAL DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    -- Latest API data (refreshed periodically)
                    leaderboard_rank INTEGER,
                    leaderboard_pnl REAL,
                    leaderboard_volume REAL,
                    api_trade_count INTEGER,
                    last_api_fetch TEXT,
                    -- Manual annotations
                    notes TEXT,
                    is_watchlist BOOLEAN DEFAULT FALSE
                );

                -- Every whale trade we've observed
                CREATE TABLE IF NOT EXISTS whale_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    wallet_address TEXT,
                    condition_id TEXT,
                    event_slug TEXT,
                    market_title TEXT,
                    outcome TEXT,
                    side TEXT,
                    size REAL,
                    price REAL,
                    trade_value REAL,
                    tx_hash TEXT,
                    -- Resolution (filled in by background job)
                    resolved_outcome TEXT,
                    trade_won BOOLEAN,
                    pnl REAL,
                    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
                );

                CREATE INDEX IF NOT EXISTS idx_whale_trades_wallet
                    ON whale_trades(wallet_address);
                CREATE INDEX IF NOT EXISTS idx_whale_trades_unresolved
                    ON whale_trades(trade_won) WHERE trade_won IS NULL;
                CREATE INDEX IF NOT EXISTS idx_whale_trades_condition
                    ON whale_trades(condition_id);
            """
            )
            await db.commit()

    async def get_wallet(self, address: str) -> Optional[dict]:
        """Get wallet with cache TTL check for API data freshness."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM wallets WHERE address = ?", (address,)
            )
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                # Check if API data is stale
                if result.get("last_api_fetch"):
                    fetched_at = datetime.fromisoformat(result["last_api_fetch"])
                    result["api_data_fresh"] = (
                        datetime.now() - fetched_at < timedelta(hours=CACHE_TTL_HOURS)
                    )
                else:
                    result["api_data_fresh"] = False
                return result
            return None

    async def upsert_wallet(self, address: str, api_data: Optional[dict] = None):
        """Create wallet if not exists, optionally update API data."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if exists
            cursor = await db.execute(
                "SELECT address FROM wallets WHERE address = ?", (address,)
            )
            exists = await cursor.fetchone()

            if not exists:
                await db.execute(
                    "INSERT INTO wallets (address, first_seen_at) VALUES (?, ?)",
                    (address, datetime.now().isoformat()),
                )

            if api_data:
                await db.execute(
                    """
                    UPDATE wallets SET
                        leaderboard_rank = ?,
                        leaderboard_pnl = ?,
                        leaderboard_volume = ?,
                        api_trade_count = ?,
                        last_api_fetch = ?
                    WHERE address = ?
                """,
                    (
                        api_data.get("leaderboard_rank"),
                        api_data.get("pnl"),
                        api_data.get("volume"),
                        api_data.get("trade_count"),
                        datetime.now().isoformat(),
                        address,
                    ),
                )

            await db.commit()

    async def record_whale_trade(self, trade: dict):
        """Record a whale trade and update wallet stats."""
        async with aiosqlite.connect(self.db_path) as db:
            wallet = trade["wallet_address"]
            trade_value = trade["size"] * trade["price"]

            # Ensure wallet exists and update stats
            await db.execute(
                """
                INSERT INTO wallets (address, first_seen_at, total_whale_trades, total_whale_volume)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(address) DO UPDATE SET
                    total_whale_trades = total_whale_trades + 1,
                    total_whale_volume = total_whale_volume + ?
            """,
                (wallet, datetime.now().isoformat(), trade_value, trade_value),
            )

            # Record the trade
            await db.execute(
                """
                INSERT INTO whale_trades
                (timestamp, wallet_address, condition_id, event_slug, market_title,
                 outcome, side, size, price, trade_value, tx_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    trade.get("timestamp", datetime.now().isoformat()),
                    wallet,
                    trade["condition_id"],
                    trade.get("event_slug"),
                    trade.get("market_title"),
                    trade["outcome"],
                    trade["side"],
                    trade["size"],
                    trade["price"],
                    trade_value,
                    trade.get("tx_hash"),
                ),
            )

            await db.commit()

    async def get_unresolved_trades(self) -> list[dict]:
        """Get all trades pending resolution, grouped by market."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT DISTINCT condition_id, event_slug, market_title
                FROM whale_trades
                WHERE trade_won IS NULL
            """
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def resolve_trades(self, condition_id: str, resolved_outcome: str) -> int:
        """Mark all trades for a market as resolved and calculate P&L."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Get all unresolved trades for this market
            cursor = await db.execute(
                """
                SELECT id, wallet_address, outcome, side, size, price
                FROM whale_trades
                WHERE condition_id = ? AND trade_won IS NULL
            """,
                (condition_id,),
            )
            trades = await cursor.fetchall()

            for trade in trades:
                won, pnl = calculate_trade_pnl(
                    trade["outcome"],
                    trade["side"],
                    trade["size"],
                    trade["price"],
                    resolved_outcome,
                )

                # Update trade
                await db.execute(
                    """
                    UPDATE whale_trades
                    SET resolved_outcome = ?, trade_won = ?, pnl = ?
                    WHERE id = ?
                """,
                    (resolved_outcome, won, pnl, trade["id"]),
                )

                # Update wallet stats
                await db.execute(
                    """
                    UPDATE wallets SET
                        wins = wins + ?,
                        losses = losses + ?,
                        realized_pnl = realized_pnl + ?
                    WHERE address = ?
                """,
                    (
                        1 if won else 0,
                        0 if won else 1,
                        pnl,
                        trade["wallet_address"],
                    ),
                )

            await db.commit()
            return len(trades)

    async def get_wallet_trades(self, address: str, limit: int = 50) -> list[dict]:
        """Get recent whale trades for a specific wallet."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM whale_trades
                WHERE wallet_address = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (address, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get_top_wallets(
        self, order_by: str = "realized_pnl", limit: int = 20
    ) -> list[dict]:
        """Get top wallets by various metrics."""
        valid_columns = [
            "realized_pnl",
            "wins",
            "total_whale_volume",
            "total_whale_trades",
        ]
        if order_by not in valid_columns:
            order_by = "realized_pnl"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT address, total_whale_trades, total_whale_volume,
                       wins, losses, realized_pnl, is_watchlist,
                       CASE WHEN (wins + losses) > 0
                            THEN ROUND(wins * 100.0 / (wins + losses), 1)
                            ELSE NULL END as win_rate
                FROM wallets
                WHERE total_whale_trades > 0
                ORDER BY {order_by} DESC
                LIMIT ?
            """,
                (limit,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def cleanup_old_trades(self, retention_days: int = 30) -> dict:
        """
        Delete resolved trades older than retention_days.
        Unresolved trades are kept regardless of age.
        Wallet aggregate stats are preserved.

        Returns dict with cleanup stats.
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            # Count what we're about to delete
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM whale_trades
                WHERE trade_won IS NOT NULL AND timestamp < ?
            """,
                (cutoff,),
            )
            row = await cursor.fetchone()
            trades_to_delete = row[0] if row else 0

            if trades_to_delete > 0:
                # Delete old resolved trades
                await db.execute(
                    """
                    DELETE FROM whale_trades
                    WHERE trade_won IS NOT NULL AND timestamp < ?
                """,
                    (cutoff,),
                )
                await db.commit()

                # Vacuum to reclaim space
                await db.execute("VACUUM")

            # Get current stats
            cursor = await db.execute("SELECT COUNT(*) FROM whale_trades")
            row = await cursor.fetchone()
            remaining_trades = row[0] if row else 0

            cursor = await db.execute(
                "SELECT COUNT(*) FROM whale_trades WHERE trade_won IS NULL"
            )
            row = await cursor.fetchone()
            unresolved_trades = row[0] if row else 0

            cursor = await db.execute("SELECT COUNT(*) FROM wallets")
            row = await cursor.fetchone()
            total_wallets = row[0] if row else 0

        return {
            "deleted_trades": trades_to_delete,
            "remaining_trades": remaining_trades,
            "unresolved_trades": unresolved_trades,
            "total_wallets": total_wallets,
            "retention_days": retention_days,
            "cutoff_date": cutoff,
        }
