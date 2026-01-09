# Polymarket Whale Scanner - Implementation Plan

## Overview

Build a real-time scanner that monitors Polymarket trades via WebSocket and alerts on Discord when large trades (>$10k) occur, with additional context about the trader's history and reputation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  RTDS WebSocket (wss://ws-live-data.polymarket.com)             │
│  Topic: activity/trades - firehose of ALL trades                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Filter: size * price >= $10,000
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Wallet Enrichment (async)                                      │
│  1. GET data-api.polymarket.com/trades?user={wallet}            │
│  2. GET data-api.polymarket.com/v1/leaderboard?user={wallet}    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  SQLite Cache (wallet stats, avoid repeated API calls)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Discord Webhook/Bot - Send formatted alert                     │
└─────────────────────────────────────────────────────────────────┘
```

## Data Sources

### 1. RTDS WebSocket - Real-time Trade Feed

**Endpoint:** `wss://ws-live-data.polymarket.com`

**Subscription message:**
```json
{
  "action": "subscribe",
  "subscriptions": [
    {
      "topic": "activity",
      "type": "trades"
    }
  ]
}
```

**Trade payload (from `activity/trades` topic):**
```json
{
  "asset": "12345...",           // ERC1155 token ID
  "conditionId": "0xabc...",     // Market ID
  "eventSlug": "will-x-happen",
  "slug": "market-slug",
  "title": "Will X happen?",
  "outcome": "Yes",
  "outcomeIndex": 0,
  "side": "BUY",                 // BUY or SELL
  "size": 1000,                  // Number of shares (integer)
  "price": 0.65,                 // Price per share (0-1)
  "proxyWallet": "0x123...",     // Trader's wallet address
  "name": "trader_name",         // Display name (may be empty)
  "pseudonym": "anon123",        // Pseudonym (may be empty)
  "timestamp": 1704067200000,    // Unix ms
  "transactionHash": "0xdef..."
}
```

**Trade value calculation:** `size * price` = USD value of the trade

**Important:** The RTDS connection may stop sending data after ~20 minutes even if ping/pong works. Implement a data timeout that forces reconnection if no trades received for 5 minutes.

### 2. Data API - Wallet History

**Base URL:** `https://data-api.polymarket.com`

**Get user's recent trades:**
```
GET /trades?user={wallet_address}&limit=100
```

Response: Array of trade objects with same schema as WebSocket trades.

**Get leaderboard stats for user:**
```
GET /v1/leaderboard?user={wallet_address}
```

Response:
```json
[
  {
    "rank": "42",
    "proxyWallet": "0x...",
    "userName": "trader_name",
    "vol": 150000,        // Total volume traded
    "pnl": 25000,         // Profit/loss
    "profileImage": "...",
    "verifiedBadge": false
  }
]
```

**Rate limits:**
- General Data API: 200 requests / 10 seconds
- `/trades` endpoint: 75 requests / 10 seconds

### 3. Gamma API - Market Metadata (Optional)

**Base URL:** `https://gamma-api.polymarket.com`

If you need more market context:
```
GET /events?slug={event_slug}
GET /markets?condition_id={condition_id}
```

## Implementation Steps

### Step 1: Project Setup

Create the following file structure:
```
polymarket-scanner/
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point for scanner
│   ├── websocket_client.py  # RTDS connection
│   ├── enrichment.py        # Wallet lookup logic
│   ├── discord_bot.py       # Discord alerts
│   ├── database.py          # SQLite database
│   └── resolution.py        # Background resolution tracker
├── requirements.txt
├── .env.example
└── README.md
```

**requirements.txt:**
```
websockets>=12.0
aiohttp>=3.9.0
discord.py>=2.3.0
python-dotenv>=1.0.0
aiosqlite>=0.19.0
```

**.env.example:**
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
# OR for bot:
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...

# Thresholds
WHALE_THRESHOLD_USD=10000
```

### Step 2: WebSocket Client (`websocket_client.py`)

Implement a WebSocket client that:

1. Connects to `wss://ws-live-data.polymarket.com`
2. Sends subscription message for `activity/trades`
3. Sends PING every 5 seconds to maintain connection
4. Implements data timeout: if no trade messages for 5 minutes, force reconnect
5. Handles reconnection with exponential backoff on disconnect
6. Parses incoming trade messages and filters for whale trades

**Key implementation details:**

```python
import asyncio
import json
import websockets
from datetime import datetime, timedelta

RTDS_URL = "wss://ws-live-data.polymarket.com"
PING_INTERVAL = 5  # seconds
DATA_TIMEOUT = 300  # 5 minutes - force reconnect if no data

class RTDSClient:
    def __init__(self, on_whale_trade, whale_threshold=10000):
        self.on_whale_trade = on_whale_trade
        self.whale_threshold = whale_threshold
        self.last_data_time = datetime.now()
        self.ws = None
    
    async def connect(self):
        while True:
            try:
                async with websockets.connect(RTDS_URL) as ws:
                    self.ws = ws
                    await self._subscribe()
                    await asyncio.gather(
                        self._ping_loop(),
                        self._receive_loop(),
                        self._data_timeout_checker()
                    )
            except Exception as e:
                print(f"Connection error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)
    
    async def _subscribe(self):
        msg = {
            "action": "subscribe",
            "subscriptions": [
                {"topic": "activity", "type": "trades"}
            ]
        }
        await self.ws.send(json.dumps(msg))
    
    async def _ping_loop(self):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await self.ws.ping()
            except:
                break
    
    async def _data_timeout_checker(self):
        """Force reconnect if no data for DATA_TIMEOUT seconds"""
        while True:
            await asyncio.sleep(60)
            if (datetime.now() - self.last_data_time).seconds > DATA_TIMEOUT:
                print("Data timeout - forcing reconnect")
                await self.ws.close()
                break
    
    async def _receive_loop(self):
        async for message in self.ws:
            self.last_data_time = datetime.now()
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                continue
    
    async def _handle_message(self, data):
        # RTDS wraps messages - extract payload
        if data.get("topic") == "activity" and data.get("type") == "trades":
            trade = data.get("payload", {})
            trade_value = trade.get("size", 0) * trade.get("price", 0)
            if trade_value >= self.whale_threshold:
                await self.on_whale_trade(trade)
```

**Note on message format:** The RTDS wraps messages with topic/type metadata. The actual trade data is in the `payload` field. Test this and adjust parsing as needed.

### Step 3: Database (`database.py`)

SQLite database for tracking wallets and their whale trades over time. This schema supports:
- Tracking all whale trades per wallet
- Resolution tracking (did their bets win?)
- Win rate and realized P&L calculation
- Manual watchlist flagging

**Schema:**

```sql
-- Wallets we've seen making whale trades
CREATE TABLE wallets (
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
CREATE TABLE whale_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    wallet_address TEXT,
    condition_id TEXT,
    event_slug TEXT,
    market_title TEXT,
    outcome TEXT,                 -- YES/NO (what they bet on)
    side TEXT,                    -- BUY/SELL
    size REAL,
    price REAL,
    trade_value REAL,
    tx_hash TEXT,
    -- Resolution (filled in by background job)
    resolved_outcome TEXT,        -- what market actually resolved to
    trade_won BOOLEAN,
    pnl REAL,
    
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);

CREATE INDEX idx_whale_trades_wallet ON whale_trades(wallet_address);
CREATE INDEX idx_whale_trades_unresolved ON whale_trades(trade_won) WHERE trade_won IS NULL;
CREATE INDEX idx_whale_trades_condition ON whale_trades(condition_id);
```

**Implementation:**

```python
import aiosqlite
from datetime import datetime, timedelta

CACHE_TTL_HOURS = 24

class Database:
    def __init__(self, db_path="polymarket_whales.db"):
        self.db_path = db_path
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    first_seen_at TEXT,
                    total_whale_trades INTEGER DEFAULT 0,
                    total_whale_volume REAL DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    leaderboard_rank INTEGER,
                    leaderboard_pnl REAL,
                    leaderboard_volume REAL,
                    api_trade_count INTEGER,
                    last_api_fetch TEXT,
                    notes TEXT,
                    is_watchlist BOOLEAN DEFAULT FALSE
                );
                
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
            """)
            await db.commit()
    
    async def get_wallet(self, address):
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
    
    async def upsert_wallet(self, address, api_data=None):
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
                    (address, datetime.now().isoformat())
                )
            
            if api_data:
                await db.execute("""
                    UPDATE wallets SET
                        leaderboard_rank = ?,
                        leaderboard_pnl = ?,
                        leaderboard_volume = ?,
                        api_trade_count = ?,
                        last_api_fetch = ?
                    WHERE address = ?
                """, (
                    api_data.get("leaderboard_rank"),
                    api_data.get("pnl"),
                    api_data.get("volume"),
                    api_data.get("trade_count"),
                    datetime.now().isoformat(),
                    address
                ))
            
            await db.commit()
    
    async def record_whale_trade(self, trade):
        """Record a whale trade and update wallet stats."""
        async with aiosqlite.connect(self.db_path) as db:
            wallet = trade["wallet_address"]
            trade_value = trade["size"] * trade["price"]
            
            # Ensure wallet exists
            await db.execute("""
                INSERT INTO wallets (address, first_seen_at, total_whale_trades, total_whale_volume)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(address) DO UPDATE SET
                    total_whale_trades = total_whale_trades + 1,
                    total_whale_volume = total_whale_volume + ?
            """, (wallet, datetime.now().isoformat(), trade_value, trade_value))
            
            # Record the trade
            await db.execute("""
                INSERT INTO whale_trades 
                (timestamp, wallet_address, condition_id, event_slug, market_title,
                 outcome, side, size, price, trade_value, tx_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
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
                trade.get("tx_hash")
            ))
            
            await db.commit()
    
    async def get_unresolved_trades(self):
        """Get all trades pending resolution, grouped by market."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT DISTINCT condition_id, event_slug, market_title
                FROM whale_trades 
                WHERE trade_won IS NULL
            """)
            return [dict(row) for row in await cursor.fetchall()]
    
    async def resolve_trades(self, condition_id, resolved_outcome):
        """Mark all trades for a market as resolved and calculate P&L."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Get all unresolved trades for this market
            cursor = await db.execute("""
                SELECT id, wallet_address, outcome, side, size, price
                FROM whale_trades
                WHERE condition_id = ? AND trade_won IS NULL
            """, (condition_id,))
            trades = await cursor.fetchall()
            
            for trade in trades:
                won, pnl = calculate_trade_pnl(
                    trade["outcome"], 
                    trade["side"], 
                    trade["size"], 
                    trade["price"],
                    resolved_outcome
                )
                
                # Update trade
                await db.execute("""
                    UPDATE whale_trades
                    SET resolved_outcome = ?, trade_won = ?, pnl = ?
                    WHERE id = ?
                """, (resolved_outcome, won, pnl, trade["id"]))
                
                # Update wallet stats
                await db.execute("""
                    UPDATE wallets SET
                        wins = wins + ?,
                        losses = losses + ?,
                        realized_pnl = realized_pnl + ?
                    WHERE address = ?
                """, (
                    1 if won else 0,
                    0 if won else 1,
                    pnl,
                    trade["wallet_address"]
                ))
            
            await db.commit()
            return len(trades)
    
    async def get_wallet_trades(self, address, limit=50):
        """Get recent whale trades for a specific wallet."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM whale_trades
                WHERE wallet_address = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (address, limit))
            return [dict(row) for row in await cursor.fetchall()]
    
    async def get_top_wallets(self, order_by="realized_pnl", limit=20):
        """Get top wallets by various metrics."""
        valid_columns = ["realized_pnl", "wins", "total_whale_volume", "total_whale_trades"]
        if order_by not in valid_columns:
            order_by = "realized_pnl"
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(f"""
                SELECT address, total_whale_trades, total_whale_volume,
                       wins, losses, realized_pnl, is_watchlist,
                       CASE WHEN (wins + losses) > 0 
                            THEN ROUND(wins * 100.0 / (wins + losses), 1)
                            ELSE NULL END as win_rate
                FROM wallets
                WHERE total_whale_trades > 0
                ORDER BY {order_by} DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in await cursor.fetchall()]


def calculate_trade_pnl(bet_outcome, side, size, price, resolved_outcome):
    """
    Calculate if trade won and P&L.
    
    bet_outcome: YES/NO - what they bet on
    side: BUY/SELL
    size: number of shares
    price: price per share
    resolved_outcome: YES/NO - what market resolved to
    
    Returns: (won: bool, pnl: float)
    """
    # Normalize
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
```

### Step 4: Wallet Enrichment (`enrichment.py`)

Fetch wallet history and leaderboard stats from Polymarket APIs:

```python
import aiohttp
from database import Database

DATA_API_BASE = "https://data-api.polymarket.com"

class WalletEnricher:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
    
    async def init(self):
        self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def enrich(self, wallet_address):
        """
        Get wallet data, fetching from API if cache is stale.
        Returns dict with trade_count, leaderboard_rank, pnl, volume, etc.
        """
        # Check if we have fresh cached data
        wallet = await self.db.get_wallet(wallet_address)
        if wallet and wallet.get("api_data_fresh"):
            return wallet
        
        # Fetch fresh data from API
        api_data = {}
        
        # Get trade history count
        trades = await self._fetch_trades(wallet_address)
        api_data["trade_count"] = len(trades)
        
        # Get leaderboard stats
        leaderboard = await self._fetch_leaderboard(wallet_address)
        if leaderboard:
            api_data["leaderboard_rank"] = int(leaderboard.get("rank", 0)) or None
            api_data["pnl"] = leaderboard.get("pnl")
            api_data["volume"] = leaderboard.get("vol")
        
        # Update database
        await self.db.upsert_wallet(wallet_address, api_data)
        
        # Return combined data
        if wallet:
            wallet.update(api_data)
            return wallet
        return api_data
    
    async def _fetch_trades(self, wallet):
        url = f"{DATA_API_BASE}/trades"
        params = {"user": wallet, "limit": 100}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Error fetching trades for {wallet}: {e}")
        return []
    
    async def _fetch_leaderboard(self, wallet):
        url = f"{DATA_API_BASE}/v1/leaderboard"
        params = {"user": wallet}
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        return data[0]
        except Exception as e:
            print(f"Error fetching leaderboard for {wallet}: {e}")
        return None
```

### Step 5: Discord Alerts (`discord_bot.py`)

Use webhooks for simplicity (no bot token needed):

```python
import aiohttp
from datetime import datetime

class DiscordAlerter:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.session = None
    
    async def init(self):
        self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def send_alert(self, trade, wallet_stats):
        trade_value = trade["size"] * trade["price"]
        wallet = trade["proxyWallet"]
        
        # Determine wallet flags
        flags = []
        trade_count = wallet_stats.get("trade_count", 0)
        if trade_count == 0:
            flags.append("🆕 **FRESH WALLET** (0 previous trades)")
        elif trade_count < 10:
            flags.append(f"⚠️ **NEW WALLET** ({trade_count} previous trades)")
        
        pnl = wallet_stats.get("pnl")
        if pnl and pnl > 100000:
            flags.append(f"💰 **HIGH PNL** (${pnl:,.0f})")
        elif pnl and pnl > 25000:
            flags.append(f"📈 Profitable (${pnl:,.0f} PnL)")
        
        rank = wallet_stats.get("leaderboard_rank")
        if rank and rank <= 100:
            flags.append(f"🏆 **TOP {rank}** on leaderboard")
        
        # Check our tracked win rate
        wins = wallet_stats.get("wins", 0)
        losses = wallet_stats.get("losses", 0)
        if wins + losses >= 3:  # Only show if we have enough data
            win_rate = wins / (wins + losses) * 100
            if win_rate >= 70:
                flags.append(f"🎯 **{win_rate:.0f}% WIN RATE** ({wins}W/{losses}L tracked)")
            elif win_rate >= 50:
                flags.append(f"📊 {win_rate:.0f}% win rate ({wins}W/{losses}L)")
        
        # Check if this is a repeat whale
        total_whale_trades = wallet_stats.get("total_whale_trades", 0)
        if total_whale_trades > 5:
            flags.append(f"🔄 **REPEAT WHALE** ({total_whale_trades} whale trades tracked)")
        
        # Build embed
        embed = {
            "title": f"🐋 Whale Trade: ${trade_value:,.0f}",
            "color": 0x00ff00 if trade["side"] == "BUY" else 0xff0000,
            "fields": [
                {
                    "name": "Market",
                    "value": f"[{trade['title']}](https://polymarket.com/event/{trade['eventSlug']})",
                    "inline": False
                },
                {
                    "name": "Trade",
                    "value": f"{trade['side']} {trade['size']:,.0f} {trade['outcome']} @ ${trade['price']:.2f}",
                    "inline": True
                },
                {
                    "name": "Value",
                    "value": f"${trade_value:,.0f}",
                    "inline": True
                },
                {
                    "name": "Wallet",
                    "value": f"`{wallet[:8]}...{wallet[-6:]}`",
                    "inline": True
                }
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add flags if any
        if flags:
            embed["fields"].append({
                "name": "Flags",
                "value": "\n".join(flags),
                "inline": False
            })
        
        # Add wallet stats if available
        stats_parts = []
        if wallet_stats.get("volume"):
            stats_parts.append(f"Volume: ${wallet_stats['volume']:,.0f}")
        if rank:
            stats_parts.append(f"Rank: #{rank}")
        if trade_count:
            stats_parts.append(f"API Trades: {trade_count}")
        
        realized_pnl = wallet_stats.get("realized_pnl", 0)
        if realized_pnl != 0:
            stats_parts.append(f"Tracked P&L: ${realized_pnl:+,.0f}")
        
        if stats_parts:
            embed["fields"].append({
                "name": "Wallet Stats",
                "value": " | ".join(stats_parts),
                "inline": False
            })
        
        # Send webhook
        payload = {"embeds": [embed]}
        try:
            async with self.session.post(self.webhook_url, json=payload) as resp:
                if resp.status != 204:
                    print(f"Discord webhook error: {resp.status}")
        except Exception as e:
            print(f"Error sending Discord alert: {e}")
```

### Step 6: Main Entry Point (`main.py`)

Tie everything together:

```python
import asyncio
import os
from dotenv import load_dotenv

from websocket_client import RTDSClient
from enrichment import WalletEnricher
from discord_bot import DiscordAlerter
from database import Database

load_dotenv()

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
WHALE_THRESHOLD = int(os.getenv("WHALE_THRESHOLD_USD", 10000))

async def main():
    # Initialize components
    db = Database()
    await db.init()
    
    enricher = WalletEnricher(db)
    await enricher.init()
    
    alerter = DiscordAlerter(WEBHOOK_URL)
    await alerter.init()
    
    async def handle_whale_trade(trade):
        wallet = trade.get("proxyWallet")
        if not wallet:
            return
        
        trade_value = trade['size'] * trade['price']
        print(f"Whale trade detected: ${trade_value:,.0f} on {trade['title']}")
        
        # Enrich with wallet data from API
        wallet_stats = await enricher.enrich(wallet)
        
        # Record trade to database
        await db.record_whale_trade({
            "wallet_address": wallet,
            "condition_id": trade.get("conditionId"),
            "event_slug": trade.get("eventSlug"),
            "market_title": trade.get("title"),
            "outcome": trade.get("outcome"),
            "side": trade.get("side"),
            "size": trade.get("size"),
            "price": trade.get("price"),
            "tx_hash": trade.get("transactionHash"),
            "timestamp": trade.get("timestamp")
        })
        
        # Get updated wallet stats (now includes our tracked data)
        wallet_data = await db.get_wallet(wallet)
        
        # Merge API stats with our tracked stats for the alert
        combined_stats = {
            "trade_count": wallet_stats.get("trade_count", 0),
            "leaderboard_rank": wallet_stats.get("leaderboard_rank"),
            "pnl": wallet_stats.get("pnl"),
            "volume": wallet_stats.get("volume"),
            # Our tracked data
            "total_whale_trades": wallet_data.get("total_whale_trades", 0) if wallet_data else 0,
            "wins": wallet_data.get("wins", 0) if wallet_data else 0,
            "losses": wallet_data.get("losses", 0) if wallet_data else 0,
            "realized_pnl": wallet_data.get("realized_pnl", 0) if wallet_data else 0,
        }
        
        # Send Discord alert
        await alerter.send_alert(trade, combined_stats)
    
    # Start WebSocket client
    client = RTDSClient(
        on_whale_trade=handle_whale_trade,
        whale_threshold=WHALE_THRESHOLD
    )
    
    print(f"Starting Polymarket whale scanner (threshold: ${WHALE_THRESHOLD:,})")
    
    try:
        await client.connect()
    finally:
        await enricher.close()
        await alerter.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 7: Resolution Tracker (`resolution.py`)

Background job to check if markets have resolved and update trade outcomes:

```python
import asyncio
import aiohttp
from database import Database

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

class ResolutionTracker:
    def __init__(self, db: Database):
        self.db = db
        self.session = None
    
    async def init(self):
        self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def check_resolutions(self):
        """Check all unresolved trades and update any that have resolved."""
        unresolved = await self.db.get_unresolved_trades()
        print(f"Checking {len(unresolved)} markets for resolution...")
        
        resolved_count = 0
        for market in unresolved:
            condition_id = market["condition_id"]
            resolution = await self._fetch_market_resolution(condition_id)
            
            if resolution:
                trades_updated = await self.db.resolve_trades(condition_id, resolution)
                print(f"Market {market['market_title'][:50]}... resolved {resolution}, updated {trades_updated} trades")
                resolved_count += trades_updated
        
        return resolved_count
    
    async def _fetch_market_resolution(self, condition_id):
        """
        Fetch market from Gamma API and return resolution if resolved.
        Returns: "Yes" / "No" / None (if not resolved)
        """
        url = f"{GAMMA_API_BASE}/markets"
        params = {"condition_id": condition_id}
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        market = data[0]
                        # Check if market is resolved
                        # The exact field names may vary - verify against actual API response
                        if market.get("closed") or market.get("resolved"):
                            # Get the winning outcome
                            # This may be in different fields depending on market type
                            outcome = market.get("outcome")
                            if outcome:
                                return outcome
                            # For binary markets, check outcome prices
                            # If one outcome is at 1.0, that's the winner
                            outcomes = market.get("outcomes", [])
                            prices = market.get("outcomePrices", [])
                            if prices:
                                for i, price in enumerate(prices):
                                    if float(price) >= 0.99:  # Resolved to this outcome
                                        return outcomes[i] if i < len(outcomes) else None
        except Exception as e:
            print(f"Error fetching market {condition_id}: {e}")
        
        return None
    
    async def run_periodic(self, interval_hours=1):
        """Run resolution checks periodically."""
        while True:
            try:
                resolved = await self.check_resolutions()
                print(f"Resolution check complete. Updated {resolved} trades.")
            except Exception as e:
                print(f"Resolution check error: {e}")
            
            await asyncio.sleep(interval_hours * 3600)


async def run_resolution_tracker():
    """Standalone entry point for resolution tracking."""
    db = Database()
    await db.init()
    
    tracker = ResolutionTracker(db)
    await tracker.init()
    
    try:
        await tracker.run_periodic(interval_hours=1)
    finally:
        await tracker.close()


if __name__ == "__main__":
    asyncio.run(run_resolution_tracker())
```

## Testing Plan

### Phase 1: WebSocket Connection
1. Connect to RTDS and verify you receive trade messages
2. Log all messages for 5 minutes to understand message format
3. Verify ping/pong keeps connection alive
4. Test reconnection by killing connection manually

### Phase 2: Trade Filtering
1. Lower threshold to $100 temporarily to see more trades
2. Verify trade value calculation is correct: `size * price`
3. Check that message parsing handles all fields correctly

### Phase 3: Wallet Enrichment
1. Test Data API endpoints manually with curl
2. Verify rate limiting is respected (add delays if needed)
3. Test cache hit/miss behavior

### Phase 4: Discord Integration
1. Create a test webhook in a private channel
2. Send test alerts with mock data
3. Verify embed formatting looks correct

### Phase 5: End-to-End
1. Run full system with $10k threshold
2. Monitor for 24+ hours to verify stability
3. Check data timeout reconnection works

## Known Issues / Gotchas

1. **RTDS data timeout:** The WebSocket may stop sending data after ~20 minutes even with healthy ping/pong. The implementation includes a data timeout checker that forces reconnection.

2. **Message format uncertainty:** The exact RTDS message wrapper format should be verified by logging raw messages. Adjust parsing if needed.

3. **Rate limits:** The Data API has rate limits. The cache layer prevents hammering the same wallet, but if you see many unique wallets rapidly, you may need to add request queuing with delays.

4. **Wallet address format:** Polymarket uses proxy wallets. The `proxyWallet` field is what identifies traders, not their EOA.

5. **Fresh vs new wallets:** "Fresh" (0 trades) is more suspicious than "new" (<10 trades). A brand new wallet making a $50k bet is a stronger signal than someone with 5 previous small trades.

## Useful Queries

Once you have data accumulated, these queries help identify potential insiders:

```sql
-- Top wallets by win rate (minimum 5 resolved trades)
SELECT 
    address,
    wins,
    losses,
    ROUND(wins * 100.0 / (wins + losses), 1) as win_rate,
    realized_pnl,
    total_whale_trades
FROM wallets
WHERE (wins + losses) >= 5
ORDER BY win_rate DESC, realized_pnl DESC
LIMIT 20;

-- Wallets with suspiciously high win rates on large bets
SELECT 
    address,
    wins,
    losses,
    ROUND(wins * 100.0 / (wins + losses), 1) as win_rate,
    realized_pnl,
    total_whale_volume
FROM wallets
WHERE (wins + losses) >= 3
  AND wins * 100.0 / (wins + losses) >= 80
  AND total_whale_volume >= 50000
ORDER BY realized_pnl DESC;

-- Fresh wallets that made whale trades (highest suspicion)
SELECT 
    w.address,
    w.first_seen_at,
    w.api_trade_count,
    w.total_whale_trades,
    w.total_whale_volume,
    w.wins,
    w.losses
FROM wallets w
WHERE w.api_trade_count < 10
  AND w.total_whale_trades >= 1
ORDER BY w.total_whale_volume DESC;

-- All trades for a specific wallet
SELECT 
    timestamp,
    market_title,
    outcome,
    side,
    size,
    price,
    trade_value,
    resolved_outcome,
    trade_won,
    pnl
FROM whale_trades
WHERE wallet_address = '0x...'
ORDER BY timestamp DESC;

-- Unresolved trades (pending outcomes)
SELECT 
    wt.wallet_address,
    wt.market_title,
    wt.outcome,
    wt.side,
    wt.trade_value,
    wt.timestamp
FROM whale_trades wt
WHERE wt.trade_won IS NULL
ORDER BY wt.trade_value DESC;

-- Markets with most whale activity
SELECT 
    condition_id,
    market_title,
    COUNT(*) as whale_trade_count,
    SUM(trade_value) as total_whale_volume,
    COUNT(DISTINCT wallet_address) as unique_whales
FROM whale_trades
GROUP BY condition_id
ORDER BY total_whale_volume DESC
LIMIT 20;

-- Wallets that consistently bet the same direction on a market
SELECT 
    wallet_address,
    market_title,
    outcome,
    side,
    COUNT(*) as trade_count,
    SUM(trade_value) as total_value
FROM whale_trades
GROUP BY wallet_address, condition_id, outcome, side
HAVING COUNT(*) >= 2
ORDER BY total_value DESC;
```

## Running the System

**Start the main scanner:**
```bash
cd polymarket-scanner
python -m src.main
```

**Start the resolution tracker (separate process or cron):**
```bash
python -m src.resolution
```

Or run resolution checks via cron every hour:
```bash
0 * * * * cd /path/to/polymarket-scanner && python -m src.resolution --once
```

## Future Enhancements (Out of Scope for MVP)

- **Wallet clustering**: Identify wallets that trade together (possible sock puppets)
- **Position sizing analysis**: Flag when someone bets unusually large relative to their history
- **Time-to-resolution correlation**: Do their bets come suspiciously close to resolution?
- **News correlation**: Did price move before public news? (requires news API)
- **Discord commands**: Query wallet stats, top performers, unresolved positions directly in Discord
- **Web dashboard**: Visual interface for exploring wallet histories
- **Alerting tiers**: Separate Discord channels for different signal strengths
- **Export functionality**: CSV export of wallet/trade data for external analysis