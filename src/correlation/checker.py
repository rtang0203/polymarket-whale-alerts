"""
Main correlation checker - runs after each news scrape.

Orchestrates the process of finding whale trades that precede
related news articles and alerting on potential insider signals.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .discord import CorrelationDiscordAlerter
from .keywords import extract_keywords, get_entity_keywords
from .matcher import CorrelationMatch, find_matches

logger = logging.getLogger(__name__)

# Configuration defaults
LOOKBACK_MINUTES = 15  # How far back to look for new articles
TRADE_WINDOW_HOURS = 24  # How far back to look for trades before article


class CorrelationChecker:
    """
    Checks for correlations between recent articles and whale trades.
    """

    def __init__(
        self,
        news_db_path: Path,
        scanner_db_path: Path,
        discord_webhook_url: Optional[str] = None,
    ):
        """
        Initialize the correlation checker.

        Args:
            news_db_path: Path to news scraper's articles.db
            scanner_db_path: Path to scanner's polymarket_whales.db
            discord_webhook_url: Optional webhook for alerts
        """
        self.news_db_path = Path(news_db_path).expanduser()
        self.scanner_db_path = Path(scanner_db_path).expanduser()

        self.discord: Optional[CorrelationDiscordAlerter] = None
        if discord_webhook_url:
            self.discord = CorrelationDiscordAlerter(discord_webhook_url)

    async def init(self):
        """Initialize resources."""
        if self.discord:
            await self.discord.init()

        # Ensure correlation_matches table exists
        self._init_correlation_table()

    async def close(self):
        """Clean up resources."""
        if self.discord:
            await self.discord.close()

    def _init_correlation_table(self):
        """Create the correlation_matches table if it doesn't exist."""
        conn = sqlite3.connect(self.scanner_db_path)
        cursor = conn.cursor()

        cursor.executescript("""
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
                matched_keywords TEXT NOT NULL,
                time_delta_seconds INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                market_type TEXT,

                -- Tracking
                created_at TEXT NOT NULL,
                discord_alerted BOOLEAN DEFAULT FALSE,
                notes TEXT,

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
            CREATE INDEX IF NOT EXISTS idx_correlation_confidence
                ON correlation_matches(confidence);
        """)

        conn.commit()
        conn.close()

    async def run(
        self,
        lookback_minutes: int = LOOKBACK_MINUTES,
        trade_window_hours: int = TRADE_WINDOW_HOURS,
        min_confidence: Optional[str] = None,
    ) -> dict:
        """
        Main entry point. Check recent articles for trade correlations.

        Args:
            lookback_minutes: How far back to look for new articles
            trade_window_hours: How far back to look for trades
            min_confidence: Minimum confidence to alert ('low', 'medium', 'high')

        Returns:
            Summary dict with counts
        """
        await self.init()

        try:
            # Get recent articles
            articles = self.get_recent_articles(lookback_minutes)
            logger.info(f"Found {len(articles)} articles from last {lookback_minutes} minutes")

            if not articles:
                return {
                    "articles_checked": 0,
                    "trades_checked": 0,
                    "new_matches": 0,
                    "alerts_sent": 0,
                }

            # Get trades from window
            trades = self.get_trades_in_window(trade_window_hours)
            logger.info(f"Found {len(trades)} trades from last {trade_window_hours} hours")

            if not trades:
                return {
                    "articles_checked": len(articles),
                    "trades_checked": 0,
                    "new_matches": 0,
                    "alerts_sent": 0,
                }

            # Process each article
            total_new_matches = 0
            total_alerts = 0

            for article in articles:
                new_matches, alerts_sent = await self.process_article(
                    article, trades, min_confidence
                )
                total_new_matches += new_matches
                total_alerts += alerts_sent

            return {
                "articles_checked": len(articles),
                "trades_checked": len(trades),
                "new_matches": total_new_matches,
                "alerts_sent": total_alerts,
            }

        finally:
            await self.close()

    def get_recent_articles(self, minutes: int) -> list[dict]:
        """
        Get articles scraped within the last N minutes.

        Queries news scraper's articles.db
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()

        conn = sqlite3.connect(self.news_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, source, url, title, published_at, scraped_at
            FROM articles
            WHERE scraped_at > ?
            ORDER BY scraped_at DESC
        """,
            (cutoff,),
        )

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

        cursor.execute(
            """
            SELECT id, timestamp, wallet_address, market_title,
                   outcome, side, size, price, trade_value, event_slug
            FROM whale_trades
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """,
            (cutoff,),
        )

        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def match_already_exists(self, trade_id: int, article_url: str) -> bool:
        """Check if this trade-article pair was already recorded."""
        conn = sqlite3.connect(self.scanner_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT 1 FROM correlation_matches
            WHERE trade_id = ? AND article_url = ?
        """,
            (trade_id, article_url),
        )

        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def record_match(self, match: CorrelationMatch) -> int:
        """
        Store a correlation match in the database.

        Returns the inserted row id.
        """
        conn = sqlite3.connect(self.scanner_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO correlation_matches (
                trade_id, trade_timestamp, wallet_address, market_title, trade_value,
                article_url, article_title, article_source, article_scraped_at,
                matched_keywords, time_delta_seconds, confidence, market_type,
                created_at, discord_alerted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                match.trade_id,
                match.trade_timestamp,
                match.wallet_address,
                match.market_title,
                match.trade_value,
                match.article_url,
                match.article_title,
                match.article_source,
                match.article_scraped_at,
                json.dumps(match.matched_keywords),
                match.time_delta_seconds,
                match.confidence,
                match.market_type,
                datetime.now().isoformat(),
                False,
            ),
        )

        row_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return row_id

    def mark_alerted(self, match_id: int):
        """Mark a correlation match as alerted."""
        conn = sqlite3.connect(self.scanner_db_path)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE correlation_matches SET discord_alerted = TRUE WHERE id = ?",
            (match_id,),
        )

        conn.commit()
        conn.close()

    async def process_article(
        self,
        article: dict,
        trades: list[dict],
        min_confidence: Optional[str] = None,
    ) -> tuple[int, int]:
        """
        Process a single article against all trades.

        Args:
            article: Article dict from news DB
            trades: List of trade dicts from scanner DB
            min_confidence: Minimum confidence to alert

        Returns:
            (new_matches_count, alerts_sent_count)
        """
        # Extract keywords from article
        article_title = article.get("title", "")
        article_keywords = extract_keywords(article_title)
        article_entities = get_entity_keywords(article_title)

        if not article_keywords:
            return 0, 0

        # Find matches
        matches = find_matches(
            article_keywords=article_keywords,
            article_entities=article_entities,
            article_title=article_title,
            article_url=article.get("url", ""),
            article_source=article.get("source", ""),
            article_scraped_at=article.get("scraped_at", ""),
            trades=trades,
            min_keyword_overlap=2,
        )

        new_matches = 0
        alerts_sent = 0

        confidence_levels = ["low", "medium", "high"]
        min_conf_idx = 0
        if min_confidence and min_confidence in confidence_levels:
            min_conf_idx = confidence_levels.index(min_confidence)

        for match in matches:
            # Skip if already recorded
            if self.match_already_exists(match.trade_id, match.article_url):
                continue

            # Record the match
            match_id = self.record_match(match)
            new_matches += 1

            logger.info(
                f"New correlation: {match.confidence} confidence, "
                f"{len(match.matched_keywords)} keywords ({', '.join(match.matched_keywords)})"
            )

            # Check if we should alert
            match_conf_idx = confidence_levels.index(match.confidence)
            should_alert = match_conf_idx >= min_conf_idx

            if should_alert and self.discord:
                success = await self.discord.send_correlation_alert(match)
                if success:
                    self.mark_alerted(match_id)
                    alerts_sent += 1

        return new_matches, alerts_sent
