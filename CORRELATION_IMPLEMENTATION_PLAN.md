# News-Trade Correlation System: Implementation Plan

## Overview

Integrate the news scraper with the Polymarket whale scanner to detect potential insider trading by identifying whale trades that precede related news articles. When a news article is scraped, check if any whale trades on related markets occurred in the prior 48 hours. Flag matches to a dedicated Discord channel and store them for pattern analysis.

## Architecture

```
┌─────────────────────────┐     ┌─────────────────────────┐
│ Polymarket Scanner      │     │ News Scraper            │
│ polymarket_whales.db    │     │ articles.db             │
│ - wallets               │     │ - articles              │
│ - whale_trades          │     │                         │
│ - correlation_matches   │     │                         │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            └───────────┬───────────────────┘
                        │
            ┌───────────▼───────────────────┐
            │ Correlation Checker           │
            │ (runs after each scrape)      │
            │                               │
            │ 1. Get articles from last 15m │
            │ 2. For each article:          │
            │    - Extract keywords         │
            │    - Find matching trades     │
            │      from prior 48h           │
            │ 3. Store matches              │
            │ 4. Alert to Discord           │
            └───────────────────────────────┘
```

## File Structure

Add to the polymarket-scanner project:

```
polymarket-scanner/
├── src/
│   ├── correlation/
│   │   ├── __init__.py
│   │   ├── keywords.py       # Keyword extraction logic
│   │   ├── matcher.py        # Match trades to articles
│   │   ├── checker.py        # Main entry point, orchestrates flow
│   │   └── discord.py        # Correlation-specific Discord alerts
│   └── ...existing files...
├── .env                      # Add: CORRELATION_WEBHOOK_URL
└── check_correlations.py     # CLI entry point for cron
```

## Database Schema

Add to `polymarket_whales.db` (extend existing `database.py`):

```sql
CREATE TABLE IF NOT EXISTS correlation_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Trade reference
    trade_id INTEGER NOT NULL,
    trade_timestamp TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    market_title TEXT NOT NULL,
    trade_value REAL NOT NULL,
    
    -- Article reference (denormalized - cross-DB)
    article_url TEXT NOT NULL,
    article_title TEXT NOT NULL,
    article_source TEXT NOT NULL,
    article_scraped_at TEXT NOT NULL,
    
    -- Match metadata
    matched_keywords TEXT NOT NULL,        -- JSON array of matched terms
    time_delta_seconds INTEGER NOT NULL,   -- Negative = trade before article
    confidence TEXT NOT NULL,              -- 'high', 'medium', 'low'
    market_type TEXT,                      -- 'sports', 'politics', 'crypto', 'other'
    
    -- Tracking
    created_at TEXT NOT NULL,
    discord_alerted BOOLEAN DEFAULT FALSE,
    notes TEXT,                            -- For manual annotation
    
    -- Prevent duplicate matches
    UNIQUE(trade_id, article_url),
    FOREIGN KEY (trade_id) REFERENCES whale_trades(id),
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);

CREATE INDEX IF NOT EXISTS idx_correlation_wallet 
    ON correlation_matches(wallet_address);
CREATE INDEX IF NOT EXISTS idx_correlation_time_delta 
    ON correlation_matches(time_delta_seconds);
CREATE INDEX IF NOT EXISTS idx_correlation_created 
    ON correlation_matches(created_at);
```

## Component Specifications

### 1. keywords.py - Keyword Extraction

```python
"""
Extract searchable keywords from market titles and article headlines.
"""

# Stopwords to remove (expand as needed)
STOPWORDS = {
    'will', 'the', 'a', 'an', 'be', 'is', 'are', 'was', 'were',
    'to', 'of', 'in', 'for', 'on', 'by', 'at', 'or', 'and',
    'this', 'that', 'with', 'from', 'as', 'it', 'its',
    'before', 'after', 'during', 'between',
    'yes', 'no', 'win', 'lose', 'happen', 'end',
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
    '2024', '2025', '2026',  # Add relevant years
    'pm', 'am', 'et', 'pt', 'utc',
}

# Patterns indicating low-value markets for correlation
MARKET_FILTERS = {
    'exclude_patterns': [
        r'up or down',           # Crypto price prediction
        r'updown',               # Alternate spelling in slugs
        r'\d+:\d+[ap]m.*[ap]m',  # Time range markets "9:00PM-9:15PM"
    ],
    'sports_indicators': [
        r'\bvs\.?\b',            # "Team A vs Team B"
        r'\bv\.?\s',             # "Team A v Team B"
    ]
}

def extract_keywords(text: str) -> set[str]:
    """
    Extract meaningful keywords from text.
    
    Args:
        text: Market title or article headline
        
    Returns:
        Set of lowercase keywords
    """
    # Implementation:
    # 1. Lowercase the text
    # 2. Remove punctuation except hyphens in compound words
    # 3. Split on whitespace
    # 4. Remove stopwords
    # 5. Remove single-character tokens
    # 6. Remove pure numbers (but keep alphanumeric like "covid19")
    # 7. Return as set
    pass

def should_skip_market(market_title: str) -> tuple[bool, str]:
    """
    Check if market should be excluded from correlation matching.
    
    Args:
        market_title: The market title from whale_trades
        
    Returns:
        (should_skip: bool, reason: str)
    """
    # Implementation:
    # 1. Check against exclude_patterns - if match, return (True, "price_market")
    # 2. Return (False, "") if no exclusion applies
    pass

def detect_market_type(market_title: str) -> str:
    """
    Categorize market type for filtering/display.
    
    Args:
        market_title: The market title
        
    Returns:
        'sports', 'politics', 'crypto', or 'other'
    """
    # Implementation:
    # 1. Check sports_indicators -> 'sports'
    # 2. Check for political keywords (trump, biden, election, congress, etc.) -> 'politics'
    # 3. Check for crypto keywords (bitcoin, btc, ethereum, eth, etc.) -> 'crypto'
    # 4. Default -> 'other'
    pass
```

### 2. matcher.py - Matching Logic

```python
"""
Match articles to trades based on keyword overlap.
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class CorrelationMatch:
    """Represents a potential correlation between a trade and article."""
    trade_id: int
    trade_timestamp: str
    wallet_address: str
    market_title: str
    trade_value: float
    trade_side: str
    trade_outcome: str
    
    article_url: str
    article_title: str
    article_source: str
    article_scraped_at: str
    
    matched_keywords: list[str]
    time_delta_seconds: int  # Negative = trade before article
    confidence: str          # 'high', 'medium', 'low'
    market_type: str

def calculate_match_confidence(
    matched_keywords: list[str],
    market_type: str,
    time_delta_seconds: int
) -> str:
    """
    Determine confidence level based on match quality.
    
    Rules:
    - high: 3+ keyword matches, non-sports market
    - high: 2+ keywords AND trade within 6 hours before article
    - medium: 2+ keywords for any market type
    - medium: sports market with 3+ keywords
    - low: 1-2 keywords (sports) or edge cases
    
    Args:
        matched_keywords: List of keywords that matched
        market_type: 'sports', 'politics', 'crypto', 'other'
        time_delta_seconds: Time between trade and article (negative = trade first)
        
    Returns:
        'high', 'medium', or 'low'
    """
    pass

def find_matches(
    article_keywords: set[str],
    article_title: str,
    article_url: str,
    article_source: str,
    article_scraped_at: str,
    trades: list[dict],
    min_keyword_overlap: int = 2
) -> list[CorrelationMatch]:
    """
    Find trades that match an article based on keyword overlap.
    
    Args:
        article_keywords: Extracted keywords from article title
        article_title: Original article title
        article_url: Article URL
        article_source: Article source (BBC, AP, etc.)
        article_scraped_at: When article was scraped
        trades: List of trade dicts from whale_trades table
        min_keyword_overlap: Minimum keywords required to match (default 2)
        
    Returns:
        List of CorrelationMatch objects for trades that match
        
    Implementation:
    1. For each trade:
       a. Check should_skip_market() - skip if excluded
       b. Extract keywords from market_title
       c. Find intersection with article_keywords
       d. If len(intersection) >= min_keyword_overlap:
          - Calculate time_delta (trade_timestamp - article_scraped_at)
          - Only include if time_delta is NEGATIVE (trade before article)
          - Determine market_type
          - Calculate confidence
          - Create CorrelationMatch
    2. Return all matches
    """
    pass
```

### 3. checker.py - Main Orchestrator

```python
"""
Main correlation checker - runs after each news scrape.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
LOOKBACK_MINUTES = 15        # How far back to look for new articles
TRADE_WINDOW_HOURS = 48      # How far back to look for trades before article

# Default paths - override via environment variables
# Local: NEWS_DB_PATH=/Users/randytang/Documents/projects/news-scraper/articles.db
# Droplet: NEWS_DB_PATH=/var/lib/news-scraper/articles.db

class CorrelationChecker:
    """
    Checks for correlations between recent articles and whale trades.
    """
    
    def __init__(
        self,
        news_db_path: Path,
        scanner_db_path: Path,
        discord_webhook_url: str
    ):
        self.news_db_path = news_db_path
        self.scanner_db_path = scanner_db_path
        self.discord = CorrelationDiscordAlerter(discord_webhook_url)
    
    async def run(self, lookback_minutes: int = 15) -> dict:
        """
        Main entry point. Check recent articles for trade correlations.
        
        Args:
            lookback_minutes: How far back to look for new articles
            
        Returns:
            Summary dict with counts
        """
        # Implementation:
        # 1. Get articles scraped in last lookback_minutes from news DB
        # 2. Get trades from last TRADE_WINDOW_HOURS from scanner DB
        # 3. For each article:
        #    a. Extract keywords
        #    b. Find matching trades
        #    c. Filter out already-recorded matches
        #    d. Store new matches
        #    e. Send Discord alerts
        # 4. Return summary
        pass
    
    def get_recent_articles(self, minutes: int) -> list[dict]:
        """
        Get articles scraped within the last N minutes.
        
        Queries news scraper's articles.db
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        
        conn = sqlite3.connect(self.news_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, source, url, title, published_at, scraped_at
            FROM articles
            WHERE scraped_at > ?
            ORDER BY scraped_at DESC
        """, (cutoff,))
        
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    
    def get_trades_in_window(self, hours: int) -> list[dict]:
        """
        Get whale trades from the last N hours.
        
        Queries scanner's polymarket_whales.db
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        conn = sqlite3.connect(self.scanner_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, timestamp, wallet_address, market_title, 
                   outcome, side, size, price, trade_value, event_slug
            FROM whale_trades
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,))
        
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    
    def match_already_exists(self, trade_id: int, article_url: str) -> bool:
        """Check if this trade-article pair was already recorded."""
        conn = sqlite3.connect(self.scanner_db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 1 FROM correlation_matches
            WHERE trade_id = ? AND article_url = ?
        """, (trade_id, article_url))
        
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    
    async def record_match(self, match: CorrelationMatch) -> int:
        """
        Store a correlation match in the database.
        
        Returns the inserted row id.
        """
        # Implementation: INSERT into correlation_matches table
        pass
    
    async def process_article(
        self,
        article: dict,
        trades: list[dict]
    ) -> list[CorrelationMatch]:
        """
        Process a single article against all trades.
        
        Returns list of new matches found.
        """
        # Implementation:
        # 1. Extract keywords from article title
        # 2. Call find_matches()
        # 3. Filter out existing matches via match_already_exists()
        # 4. For each new match:
        #    a. record_match()
        #    b. discord.send_correlation_alert()
        # 5. Return new matches
        pass
```

### 4. discord.py - Correlation Alerts

```python
"""
Discord alerts for correlation matches.
"""

import aiohttp
from datetime import datetime, timezone

class CorrelationDiscordAlerter:
    """
    Sends correlation alerts to a dedicated Discord channel.
    """
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session = None
    
    async def init(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def send_correlation_alert(self, match: CorrelationMatch) -> bool:
        """
        Send an alert for a trade-news correlation.
        
        Embed format:
        - Title: "Potential Insider Signal: [confidence]"
        - Color: Orange for medium, Red for high confidence
        - Fields:
          - Trade: market title, side, value, wallet (truncated)
          - Article: title (linked), source
          - Timing: "Trade was X hours Y minutes before news"
          - Matched Keywords: comma-separated list
          - Market Type: sports/politics/crypto/other
        """
        time_delta_abs = abs(match.time_delta_seconds)
        hours = time_delta_abs // 3600
        minutes = (time_delta_abs % 3600) // 60
        
        if hours > 0:
            timing_str = f"{hours}h {minutes}m before news"
        else:
            timing_str = f"{minutes}m before news"
        
        # Color based on confidence
        color_map = {
            'high': 0xFF0000,    # Red
            'medium': 0xFFA500,  # Orange
            'low': 0xFFFF00      # Yellow
        }
        color = color_map.get(match.confidence, 0xFFFF00)
        
        # Truncate wallet address
        wallet = match.wallet_address
        wallet_display = f"`{wallet[:8]}...{wallet[-6:]}`"
        
        embed = {
            "title": f"Potential Insider Signal: {match.confidence.upper()}",
            "color": color,
            "fields": [
                {
                    "name": "Trade",
                    "value": (
                        f"**{match.market_title}**\n"
                        f"{match.trade_side} {match.trade_outcome} · "
                        f"${match.trade_value:,.0f}"
                    ),
                    "inline": False
                },
                {
                    "name": "Wallet",
                    "value": wallet_display,
                    "inline": True
                },
                {
                    "name": "Timing",
                    "value": timing_str,
                    "inline": True
                },
                {
                    "name": "Market Type",
                    "value": match.market_type.capitalize(),
                    "inline": True
                },
                {
                    "name": "News Article",
                    "value": f"[{match.article_title}]({match.article_url})\n*{match.article_source}*",
                    "inline": False
                },
                {
                    "name": "Matched Keywords",
                    "value": ", ".join(match.matched_keywords),
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        payload = {"embeds": [embed]}
        
        try:
            async with self.session.post(self.webhook_url, json=payload) as resp:
                return resp.status == 204
        except Exception as e:
            print(f"Error sending correlation alert: {e}")
            return False
```

### 5. check_correlations.py - CLI Entry Point

```python
#!/usr/bin/env python3
"""
CLI entry point for correlation checking.
Run via cron after news scraper completes.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from correlation.checker import CorrelationChecker

def main():
    load_dotenv()
    
    webhook_url = os.getenv("CORRELATION_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: CORRELATION_WEBHOOK_URL not set in .env")
        sys.exit(1)
    
    # Configure paths - adjust these for your deployment
    news_db = Path(os.getenv("NEWS_DB_PATH", "/home/user/news-scraper/articles.db"))
    scanner_db = Path(os.getenv("SCANNER_DB_PATH", "/home/user/polymarket-scanner/polymarket_whales.db"))
    
    if not news_db.exists():
        print(f"ERROR: News database not found at {news_db}")
        sys.exit(1)
    
    if not scanner_db.exists():
        print(f"ERROR: Scanner database not found at {scanner_db}")
        sys.exit(1)
    
    checker = CorrelationChecker(
        news_db_path=news_db,
        scanner_db_path=scanner_db,
        discord_webhook_url=webhook_url
    )
    
    # Run with 15 minute lookback (matches scraper frequency + buffer)
    result = asyncio.run(checker.run(lookback_minutes=15))
    
    print(f"Correlation check complete:")
    print(f"  Articles checked: {result.get('articles_checked', 0)}")
    print(f"  New matches found: {result.get('new_matches', 0)}")
    print(f"  Alerts sent: {result.get('alerts_sent', 0)}")

if __name__ == "__main__":
    main()
```

## Configuration

Add to `.env`:

```bash
# Existing settings...

# Correlation checker
CORRELATION_WEBHOOK_URL=https://discord.com/api/webhooks/1462329955059765359/xO-J2f95F9y1soXrf5fg07eFdICfzh6F6GatFx9F2gLy5eYowhsrqJnu6-iinQsO2Gex

# Local development paths
NEWS_DB_PATH=/Users/randytang/Documents/projects/news-scraper/articles.db
SCANNER_DB_PATH=/Users/randytang/Documents/projects/polymarket-whale-alerts/polymarket_whales.db

# DigitalOcean droplet paths (uncomment for production)
# NEWS_DB_PATH=/var/lib/news-scraper/articles.db
# SCANNER_DB_PATH=/var/lib/polymarket-scanner/polymarket_whales.db
```

## Deployment

### Cron Setup

Add to crontab on DigitalOcean droplet:

```bash
# Run news scraper every 10 minutes (already configured)
*/10 * * * * cd /opt/news-scraper && ./venv/bin/python3 news_scraper/scraper.py >> /var/log/news-scraper.log 2>&1

# Run correlation checker 1 minute after scraper (give it time to complete)
1,11,21,31,41,51 * * * * cd /opt/polymarket-scanner && ./venv/bin/python3 check_correlations.py >> /var/log/correlation.log 2>&1
```

Database paths on droplet:
- News DB: `/var/lib/news-scraper/articles.db`
- Scanner DB: `/var/lib/polymarket-scanner/polymarket_whales.db`

### Database Migration

Run once to add the correlation_matches table:

```bash
cd /opt/polymarket-scanner
./venv/bin/python3 -c "
import asyncio
from src.database import Database

async def migrate():
    db = Database()
    await db.init()  # Existing init
    
    # Add correlation table
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.executescript('''
            CREATE TABLE IF NOT EXISTS correlation_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                trade_timestamp TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                market_title TEXT NOT NULL,
                trade_value REAL NOT NULL,
                article_url TEXT NOT NULL,
                article_title TEXT NOT NULL,
                article_source TEXT NOT NULL,
                article_scraped_at TEXT NOT NULL,
                matched_keywords TEXT NOT NULL,
                time_delta_seconds INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                market_type TEXT,
                created_at TEXT NOT NULL,
                discord_alerted BOOLEAN DEFAULT FALSE,
                notes TEXT,
                UNIQUE(trade_id, article_url),
                FOREIGN KEY (trade_id) REFERENCES whale_trades(id),
                FOREIGN KEY (wallet_address) REFERENCES wallets(address)
            );
            
            CREATE INDEX IF NOT EXISTS idx_correlation_wallet 
                ON correlation_matches(wallet_address);
            CREATE INDEX IF NOT EXISTS idx_correlation_time_delta 
                ON correlation_matches(time_delta_seconds);
            CREATE INDEX IF NOT EXISTS idx_correlation_created 
                ON correlation_matches(created_at);
        ''')
        await conn.commit()
    print('Migration complete')

asyncio.run(migrate())
"
```

## Analysis Queries

Useful queries to run against the correlation_matches table:

```sql
-- Wallets with multiple news-correlated trades (potential insiders)
SELECT 
    wallet_address,
    COUNT(*) as correlation_count,
    AVG(time_delta_seconds) / 3600.0 as avg_hours_before_news,
    GROUP_CONCAT(DISTINCT market_type) as market_types
FROM correlation_matches
GROUP BY wallet_address
HAVING COUNT(*) >= 2
ORDER BY correlation_count DESC;

-- High confidence matches from the last 24 hours
SELECT 
    market_title,
    article_title,
    article_source,
    time_delta_seconds / 3600.0 as hours_before,
    matched_keywords,
    wallet_address
FROM correlation_matches
WHERE confidence = 'high'
  AND created_at > datetime('now', '-24 hours')
ORDER BY created_at DESC;

-- Match distribution by market type
SELECT 
    market_type,
    confidence,
    COUNT(*) as count
FROM correlation_matches
GROUP BY market_type, confidence
ORDER BY market_type, confidence;

-- Wallets from correlation matches that also have good win rates
SELECT 
    cm.wallet_address,
    COUNT(DISTINCT cm.id) as correlations,
    w.wins,
    w.losses,
    ROUND(w.wins * 100.0 / (w.wins + w.losses), 1) as win_rate,
    w.realized_pnl
FROM correlation_matches cm
JOIN wallets w ON cm.wallet_address = w.address
WHERE w.wins + w.losses >= 3
GROUP BY cm.wallet_address
HAVING correlations >= 2
ORDER BY win_rate DESC;
```

## Testing

### Unit Tests

Create `tests/test_correlation/`:

```python
# test_keywords.py
def test_extract_keywords_removes_stopwords():
    from src.correlation.keywords import extract_keywords
    result = extract_keywords("Will Trump win the 2024 election?")
    assert 'will' not in result
    assert 'the' not in result
    assert 'trump' in result
    assert 'election' in result

def test_should_skip_market_filters_price_markets():
    from src.correlation.keywords import should_skip_market
    skip, reason = should_skip_market("Bitcoin Up or Down - January 15")
    assert skip is True
    assert reason == "price_market"

def test_should_skip_market_allows_political():
    from src.correlation.keywords import should_skip_market
    skip, _ = should_skip_market("Will Trump win the 2024 election?")
    assert skip is False

# test_matcher.py
def test_find_matches_requires_minimum_overlap():
    # Test that single keyword matches are rejected
    pass

def test_find_matches_only_returns_trades_before_article():
    # Test that trades AFTER article are not matched
    pass

def test_confidence_calculation():
    from src.correlation.matcher import calculate_match_confidence
    
    # High confidence: 3+ keywords, non-sports
    assert calculate_match_confidence(['trump', 'tariff', 'china'], 'politics', -3600) == 'high'
    
    # Medium confidence: 2 keywords
    assert calculate_match_confidence(['trump', 'tariff'], 'politics', -3600) == 'medium'
    
    # Lower confidence for sports
    assert calculate_match_confidence(['utah', 'jazz'], 'sports', -3600) == 'low'
```

### Manual Testing

Before deploying, test locally:

```bash
# 1. Populate some test articles
cd /path/to/news-scraper
./venv/bin/python3 news_scraper/scraper.py

# 2. Check what articles exist
./venv/bin/python3 -c "
from news_scraper.db import get_recent_articles
for a in get_recent_articles(10):
    print(f\"{a['source']}: {a['title']}\")
"

# 3. Run correlation checker with verbose output
cd /path/to/polymarket-scanner
./venv/bin/python3 -c "
import asyncio
from src.correlation.checker import CorrelationChecker

async def test():
    checker = CorrelationChecker(
        news_db_path='../news-scraper/articles.db',
        scanner_db_path='polymarket_whales.db',
        discord_webhook_url='YOUR_TEST_WEBHOOK'
    )
    
    # Check last hour of articles for testing
    result = await checker.run(lookback_minutes=60)
    print(result)

asyncio.run(test())
"
```

## Future Enhancements

Not for v1, but consider later:

1. **Embedding-based matching**: Use sentence-transformers for semantic similarity instead of keyword overlap. Would catch "Fed raises interest rates" matching "Will inflation decrease?" even without shared keywords.

2. **Market category from Polymarket**: If their API exposes category data, use it for better filtering.

3. **Resolution tracking**: After markets resolve, check if news-correlated trades won at a higher rate than baseline. That's the real insider signal.

4. **Wallet reputation scoring**: Weight wallets by their historical correlation-to-win rate.

5. **More news sources**: Add Twitter/X monitoring for faster news detection, or financial news APIs.

6. **Reverse correlation**: Also flag when news breaks and *then* a whale trade happens within minutes (fast-money signal, different from insider but still interesting).