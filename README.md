# Polymarket Whale Scanner

Real-time scanner that monitors Polymarket trades via WebSocket and alerts on Discord when large trades (>$10k) occur, with context about the trader's history and reputation.

## Features

- **Real-time monitoring** via Polymarket RTDS WebSocket
- **Whale detection** with configurable threshold (default $10k)
- **Wallet enrichment** with trader history and leaderboard stats
- **Discord alerts** with rich embeds showing trade details and flags
- **Reputation tracking** - tracks win rates for wallets over time
- **Resolution tracking** - background job calculates P&L when markets resolve
- **Correlation detection** - identifies whale trades that precede related news (potential insider signals)

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create Discord webhook

1. Open Discord and go to your server
2. Right-click on the channel where you want alerts → **Edit Channel**
3. Go to **Integrations** → **Webhooks** → **New Webhook**
4. Name it (e.g., "Polymarket Whales") and copy the webhook URL

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your webhook URL:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
WHALE_THRESHOLD_USD=10000
```

### 4. Run the scanner

```bash
python3 -m src.main
```

## Testing

Run the integration tests to verify API connectivity:

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Quick connectivity check (without pytest)
python3 tests/test_api_connectivity.py
```

## Correlation Checker

The correlation checker detects whale trades that occur before related news articles break - potential insider trading signals.

### Prerequisites

Requires a separate [news-scraper](https://github.com/your-repo/news-scraper) project with its own `articles.db` database.

### Configuration

Add to `.env`:

```bash
# Correlation checker
CORRELATION_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
NEWS_DB_PATH=/path/to/news-scraper/articles.db
SCANNER_DB_PATH=/path/to/polymarket_whales.db
```

### Running Locally

```bash
# Test webhook connectivity
python3 check_correlations.py --test

# Run correlation check (default: last 15 min of articles, 48h of trades)
python3 check_correlations.py

# Check more articles (useful for testing)
python3 check_correlations.py --lookback 60

# Only alert on high confidence matches
python3 check_correlations.py --min-confidence high

# Verbose output (see article/trade counts)
python3 check_correlations.py -v
```

### How It Works

1. Queries recent articles from the news scraper's database
2. Extracts keywords from article headlines
3. Finds whale trades from the last 48 hours with matching keywords
4. Only flags trades that occurred **before** the news
5. Assigns confidence levels based on keyword overlap and market type:
   - **High**: 3+ keywords, or entity match (person/company name)
   - **Medium**: 2+ keywords on non-sports markets
   - **Low**: Sports matches or minimal overlap

### Confidence Levels

| Confidence | Criteria | Example |
|------------|----------|---------|
| High | 3+ keyword match, non-sports | "Trump", "Greenland", "acquire" |
| High | Entity name + 2 keywords | "Elon Musk" matched |
| Medium | 2 keywords, non-sports | "interest", "rates" |
| Low | Sports market matches | "Bills vs Chiefs" |

See [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment instructions.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | - | Discord webhook URL for whale alerts |
| `WHALE_THRESHOLD_USD` | 10000 | Minimum trade value to trigger alert |
| `RESOLUTION_CHECK_INTERVAL_HOURS` | 1 | How often to check market resolutions |
| `DATABASE_PATH` | polymarket_whales.db | SQLite database file path |
| `CORRELATION_WEBHOOK_URL` | - | Discord webhook for correlation alerts |
| `NEWS_DB_PATH` | - | Path to news scraper's articles.db |
| `SCANNER_DB_PATH` | - | Path to polymarket_whales.db (for correlation checker) |

## Architecture

```
RTDS WebSocket (real-time trades)
         │
         ▼ Filter >= $10k
    ┌────────────┐
    │ Enrichment │ ← Data API (wallet history, leaderboard)
    └────────────┘
         │
         ▼
    ┌────────────┐
    │  Database  │ (SQLite - track wallets, trades, resolutions)
    └────────────┘
         │
         ▼
    ┌────────────┐
    │  Discord   │ → Webhook alerts with flags
    └────────────┘

    ┌────────────┐
    │ Resolution │ ← Gamma API (hourly check for market outcomes)
    │  Tracker   │ → Updates win/loss stats
    └────────────┘
```

## Alert Flags

The scanner adds contextual flags to alerts:

- **NEW WALLET** - Trader has few/no previous trades (fresh wallet)
- **HIGH PNL** - Trader has >$100k profit on leaderboard
- **TOP X** - Trader is in top 100 on leaderboard
- **WIN RATE** - Shows tracked win rate if we have enough data
- **REPEAT WHALE** - Wallet has made multiple whale trades we've tracked

## Database Schema

The scanner tracks:

- **wallets** - Every wallet that makes a whale trade, with stats
- **whale_trades** - Every whale trade, with resolution status

Useful queries:

```sql
-- Top wallets by win rate
SELECT address, wins, losses,
       ROUND(wins * 100.0 / (wins + losses), 1) as win_rate,
       realized_pnl
FROM wallets
WHERE (wins + losses) >= 5
ORDER BY win_rate DESC;

-- Fresh wallets making whale trades (suspicious)
SELECT address, api_trade_count, total_whale_volume
FROM wallets
WHERE api_trade_count < 10
ORDER BY total_whale_volume DESC;

-- Unresolved trades
SELECT market_title, outcome, side, trade_value
FROM whale_trades
WHERE trade_won IS NULL
ORDER BY trade_value DESC;
```

## Project Structure

```
polymarket-whale-alerts/
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point for whale scanner
│   ├── websocket_client.py  # RTDS WebSocket connection
│   ├── enrichment.py        # Wallet data fetching
│   ├── discord_bot.py       # Discord webhook alerts
│   ├── database.py          # SQLite database
│   ├── resolution.py        # Market resolution tracking
│   └── correlation/         # News-trade correlation detection
│       ├── __init__.py
│       ├── keywords.py      # Keyword extraction
│       ├── matcher.py       # Match trades to articles
│       ├── discord.py       # Correlation alerts
│       └── checker.py       # Main orchestrator
├── tests/
│   └── test_api_connectivity.py  # Integration tests
├── check_correlations.py    # CLI for correlation checker
├── requirements.txt
├── pytest.ini
├── .env.example
└── README.md
```

## Known Issues

1. **RTDS data timeout** - The WebSocket may stop sending data after ~20 min even with healthy ping/pong. The scanner auto-reconnects after 5 minutes of no data.

2. **Rate limits** - Data API has limits (75 req/10s for /trades). The cache layer prevents repeated calls for the same wallet.

3. **Proxy wallets** - Polymarket uses proxy wallets. The `proxyWallet` field identifies traders, not their EOA.
