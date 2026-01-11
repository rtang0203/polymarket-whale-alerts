# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the scanner
python3 -m src.main

# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Quick API connectivity check (without pytest)
python3 tests/test_api_connectivity.py
```

## Architecture

Real-time Polymarket whale trade scanner with Discord alerts.

**Data Flow:**
1. `websocket_client.py` connects to RTDS WebSocket (`wss://ws-live-data.polymarket.com`), filters trades >= threshold
2. `enrichment.py` fetches wallet context from Data API (trade history, leaderboard stats), caches for 24h
3. `database.py` records trade to SQLite, updates wallet stats
4. `discord_bot.py` sends webhook alert with trade details and wallet flags
5. `resolution.py` runs hourly background task checking Gamma API for market outcomes, calculates P&L

**Key Classes:**
- `WhaleScanner` (main.py) - orchestrates all components, handles graceful shutdown
- `RTDSClient` - WebSocket with auto-reconnect, 5-min data timeout detection
- `Database` - SQLite with `wallets` and `whale_trades` tables
- `WalletEnricher` - Data API client with caching
- `DiscordAlerter` - webhook sender with rich embeds
- `ResolutionTracker` - Gamma API poller for market outcomes

**External APIs:**
- RTDS WebSocket: `wss://ws-live-data.polymarket.com` (real-time trades)
- Data API: `https://data-api.polymarket.com` (wallet history, leaderboard)
- Gamma API: `https://gamma-api.polymarket.com` (market metadata, resolution)

## Configuration

Set in `.env` file (copy from `.env.example`):
- `DISCORD_WEBHOOK_URL` - required for alerts
- `WHALE_THRESHOLD_USD` - default 10000
- `RESOLUTION_CHECK_INTERVAL_HOURS` - default 1
- `DATABASE_PATH` - default polymarket_whales.db
- `DATA_RETENTION_DAYS` - default 30 (cleanup deletes resolved trades older than this)


```