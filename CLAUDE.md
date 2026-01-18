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

# Run correlation checker (after news scraper)
python3 check_correlations.py

# Run correlation checker with options
python3 check_correlations.py --lookback 60 --min-confidence medium

# Test correlation webhook
python3 check_correlations.py --test
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
- `Database` - SQLite with `wallets`, `whale_trades`, and `correlation_matches` tables
- `WalletEnricher` - Data API client with caching
- `DiscordAlerter` - webhook sender with rich embeds
- `ResolutionTracker` - Gamma API poller for market outcomes
- `CorrelationChecker` - detects trades that precede related news articles

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

**Correlation checker (optional):**
- `CORRELATION_WEBHOOK_URL` - Discord webhook for correlation alerts
- `NEWS_DB_PATH` - path to news scraper's articles.db
- `SCANNER_DB_PATH` - path to polymarket_whales.db

## Correlation Checker

The correlation checker (`check_correlations.py`) detects whale trades that occur before related news articles break - potential insider trading signals.

**How it works:**
1. Queries recent articles from news scraper's `articles.db`
2. Extracts keywords from article headlines
3. Finds whale trades from the last 48 hours with matching keywords
4. Only flags trades that occurred BEFORE the news (negative time delta)
5. Assigns confidence levels (high/medium/low) based on keyword overlap and market type
6. Alerts to a dedicated Discord channel

**Database paths:**
- Local: `NEWS_DB_PATH=~/Documents/projects/news-scraper/articles.db`
- Droplet: `NEWS_DB_PATH=/var/lib/news-scraper/articles.db`

**Local testing:**
```bash
# Ensure .env has correlation settings configured
# NEWS_DB_PATH, SCANNER_DB_PATH, CORRELATION_WEBHOOK_URL

# Test webhook connectivity
python3 check_correlations.py --test

# Run with verbose output to see counts
python3 check_correlations.py -v

# Check more articles (if recent data is sparse)
python3 check_correlations.py --lookback 60 -v

# Only alert on high confidence
python3 check_correlations.py --min-confidence high
```

**Production cron** (chained after news scraper):
```bash
*/10 * * * * /opt/news-scraper/venv/bin/python3 /opt/news-scraper/news_scraper/scraper.py >> /var/lib/news-scraper/scraper.log 2>&1 && /opt/polymarket-scanner/venv/bin/python3 /opt/polymarket-scanner/check_correlations.py >> /var/log/correlation.log 2>&1
```

See [CORRELATION_IMPLEMENTATION_PLAN.md](CORRELATION_IMPLEMENTATION_PLAN.md) for detailed design docs.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for DigitalOcean setup instructions.