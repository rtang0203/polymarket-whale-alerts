# Changelog

## [0.1.0] - 2025-01-09

### Added

Initial implementation of the Polymarket Whale Scanner.

#### Core Components
- **websocket_client.py** - RTDS WebSocket client with:
  - Auto-reconnection with exponential backoff
  - Ping/pong keep-alive (every 5 seconds)
  - Data timeout detection (reconnects if no data for 5 minutes)
  - Whale trade filtering by configurable threshold

- **database.py** - SQLite database with:
  - `wallets` table - tracks wallet stats, API data cache, win/loss records
  - `whale_trades` table - every whale trade with resolution status
  - P&L calculation logic for resolved trades

- **enrichment.py** - Wallet data fetching from Polymarket Data API:
  - `/trades` endpoint for trade history count
  - `/v1/leaderboard` endpoint for rank, PnL, volume
  - 24-hour cache TTL to avoid repeated API calls

- **discord_bot.py** - Discord webhook alerts with:
  - Rich embeds showing trade details
  - Wallet flags (NEW WALLET, HIGH PNL, TOP X, WIN RATE, REPEAT WHALE)
  - Wallet stats summary

- **resolution.py** - Market resolution tracker:
  - Queries Gamma API for market outcomes
  - Updates trade win/loss status and calculates P&L
  - Runs as background task (configurable interval, default 1 hour)

- **main.py** - Entry point that orchestrates all components:
  - Initializes database, HTTP clients, WebSocket
  - Handles whale trades: enrich -> record -> alert
  - Runs resolution tracker as background task
  - Graceful shutdown on SIGTERM/SIGINT

#### Testing
- **test_api_connectivity.py** - 12 integration tests covering:
  - RTDS WebSocket connection and trade reception
  - Data API endpoints (trades, leaderboard)
  - Gamma API endpoints (markets, events)
  - End-to-end flows (fetch trader data, find resolved markets)

#### Configuration
- `.env.example` with all configuration options
- `requirements.txt` with pinned dependencies
- `pytest.ini` for test configuration
- `README.md` with setup and usage instructions

---

## Next Steps

### Immediate (Required to Run)

1. **Create Discord Webhook**
   - Go to Discord server → channel settings → Integrations → Webhooks
   - Create new webhook and copy the URL

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env and set DISCORD_WEBHOOK_URL
   ```

3. **Run the Scanner**
   ```bash
   source venv/bin/activate
   python3 -m src.main
   ```

### Short-term (Recommended)

- [ ] Run scanner for 24+ hours to verify stability
- [ ] Monitor logs for any API rate limiting issues
- [ ] Verify Discord alerts are formatted correctly
- [ ] Check database is recording trades properly

### Future Enhancements (Out of Scope for MVP)

- [ ] Wallet clustering - identify wallets that trade together
- [ ] Position sizing analysis - flag unusually large bets relative to history
- [ ] Time-to-resolution correlation - detect suspiciously timed bets
- [ ] Discord bot commands - query wallet stats directly in Discord
- [ ] Web dashboard - visual interface for exploring data
- [ ] Alerting tiers - separate channels for different signal strengths
- [ ] CSV export - export wallet/trade data for external analysis
