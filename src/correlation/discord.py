"""
Discord alerts for correlation matches.

Sends alerts to a dedicated channel when trades are found
that precede related news articles.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from .matcher import CorrelationMatch

logger = logging.getLogger(__name__)

# Rate limiting config
RATE_LIMIT_DELAY = 0.5  # Base delay between requests (seconds)
MAX_RETRY_DELAY = 5.0   # Maximum delay on rate limit


class CorrelationDiscordAlerter:
    """
    Sends correlation alerts to a dedicated Discord channel.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def init(self):
        """Initialize the HTTP session."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def close(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def send_correlation_alert(self, match: CorrelationMatch) -> bool:
        """
        Send an alert for a trade-news correlation.

        Args:
            match: The correlation match to alert on

        Returns:
            True if alert was sent successfully
        """
        if not self.session:
            await self.init()

        # Calculate timing string
        time_delta_abs = abs(match.time_delta_seconds)
        hours = time_delta_abs // 3600
        minutes = (time_delta_abs % 3600) // 60

        if hours > 0:
            timing_str = f"{hours}h {minutes}m before news"
        else:
            timing_str = f"{minutes}m before news"

        # Color based on confidence
        color_map = {
            "high": 0xFF0000,    # Red
            "medium": 0xFFA500,  # Orange
            "low": 0xFFFF00,     # Yellow
        }
        color = color_map.get(match.confidence, 0xFFFF00)

        # Truncate wallet address
        wallet = match.wallet_address
        if len(wallet) > 14:
            wallet_display = f"`{wallet[:8]}...{wallet[-6:]}`"
        else:
            wallet_display = f"`{wallet}`"

        # Format trade description
        trade_desc = (
            f"**{match.market_title}**\n"
            f"{match.trade_side} {match.trade_outcome} · ${match.trade_value:,.0f}"
        )

        # Format article link (truncate title if too long)
        article_title = match.article_title
        if len(article_title) > 100:
            article_title = article_title[:97] + "..."

        embed = {
            "title": f"Potential Insider Signal: {match.confidence.upper()}",
            "color": color,
            "fields": [
                {
                    "name": "Trade",
                    "value": trade_desc,
                    "inline": False,
                },
                {
                    "name": "Wallet",
                    "value": wallet_display,
                    "inline": True,
                },
                {
                    "name": "Timing",
                    "value": timing_str,
                    "inline": True,
                },
                {
                    "name": "Market Type",
                    "value": match.market_type.capitalize(),
                    "inline": True,
                },
                {
                    "name": "News Article",
                    "value": f"[{article_title}]({match.article_url})\n*{match.article_source}*",
                    "inline": False,
                },
                {
                    "name": "Matched Keywords",
                    "value": ", ".join(match.matched_keywords),
                    "inline": False,
                },
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        payload = {"embeds": [embed]}

        # Retry with exponential backoff on rate limit
        max_retries = 3
        delay = RATE_LIMIT_DELAY

        for attempt in range(max_retries):
            try:
                async with self.session.post(self.webhook_url, json=payload) as resp:
                    if resp.status == 204:
                        logger.debug(
                            f"Correlation alert sent: {match.confidence} confidence, "
                            f"{len(match.matched_keywords)} keywords"
                        )
                        # Add delay between requests to avoid rate limits
                        await asyncio.sleep(RATE_LIMIT_DELAY)
                        return True
                    elif resp.status == 429:
                        # Rate limited - extract retry_after and wait
                        try:
                            data = await resp.json()
                            retry_after = data.get("retry_after", delay)
                        except Exception:
                            retry_after = delay

                        wait_time = min(retry_after + 0.1, MAX_RETRY_DELAY)
                        logger.warning(f"Rate limited, waiting {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        delay = min(delay * 2, MAX_RETRY_DELAY)
                    else:
                        body = await resp.text()
                        logger.error(f"Discord webhook error: {resp.status} - {body}")
                        return False
            except Exception as e:
                logger.error(f"Error sending correlation alert: {e}")
                return False

        logger.error(f"Failed to send alert after {max_retries} attempts (rate limited)")
        return False

    async def send_test_message(self) -> bool:
        """Send a test message to verify webhook is working."""
        if not self.session:
            await self.init()

        payload = {
            "content": "Correlation Checker connected successfully!",
            "embeds": [
                {
                    "title": "Test Alert",
                    "description": "If you see this, the correlation webhook is working.",
                    "color": 0x00FF00,
                }
            ],
        }

        try:
            async with self.session.post(self.webhook_url, json=payload) as resp:
                return resp.status == 204
        except Exception as e:
            logger.error(f"Error sending test message: {e}")
            return False
