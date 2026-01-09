import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class DiscordAlerter:
    """
    Sends whale trade alerts to Discord via webhook.

    Formats trades as rich embeds with wallet context and flags.
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

    async def send_alert(self, trade: dict, wallet_stats: dict) -> bool:
        """
        Send a whale trade alert to Discord.

        Args:
            trade: The trade data from RTDS
            wallet_stats: Enriched wallet statistics

        Returns:
            True if alert was sent successfully, False otherwise
        """
        trade_value = trade.get("size", 0) * trade.get("price", 0)
        wallet = trade.get("proxyWallet", "Unknown")

        # Build flags based on wallet characteristics
        flags = self._build_flags(wallet_stats)

        # Build the Discord embed
        embed = self._build_embed(trade, trade_value, wallet, wallet_stats, flags)

        # Send webhook
        payload = {"embeds": [embed]}

        try:
            async with self.session.post(self.webhook_url, json=payload) as resp:
                if resp.status == 204:
                    logger.debug(f"Discord alert sent for ${trade_value:,.0f} trade")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Discord webhook error: {resp.status} - {body}")
                    return False
        except Exception as e:
            logger.error(f"Error sending Discord alert: {e}")
            return False

    def _build_flags(self, wallet_stats: dict) -> list[str]:
        """Build list of flag strings based on wallet characteristics."""
        flags = []

        # Check trade count - fresh/new wallet flags
        # trade_count can be None (API failed), 0 (new wallet), or 1-100 (capped at 100)
        trade_count = wallet_stats.get("trade_count")
        if trade_count is None:
            trade_count = wallet_stats.get("api_trade_count")

        # Only flag as NEW WALLET if we have confirmed data (not None)
        if trade_count is not None:
            if trade_count == 0:
                flags.append("NEW WALLET (0 previous trades)")
            elif trade_count < 10:
                flags.append(f"NEW WALLET ({trade_count} previous trades)")

        # Check PnL from leaderboard
        pnl = wallet_stats.get("pnl") or wallet_stats.get("leaderboard_pnl")
        if pnl:
            if pnl > 100000:
                flags.append(f"HIGH PNL (${pnl:,.0f})")
            elif pnl > 25000:
                flags.append(f"Profitable (${pnl:,.0f} PnL)")

        # Check leaderboard rank
        rank = wallet_stats.get("leaderboard_rank")
        if rank and rank <= 100:
            flags.append(f"TOP {rank} on leaderboard")

        # Check our tracked win rate
        wins = wallet_stats.get("wins", 0)
        losses = wallet_stats.get("losses", 0)
        if wins + losses >= 3:  # Only show if we have enough data
            win_rate = wins / (wins + losses) * 100
            if win_rate >= 70:
                flags.append(f"{win_rate:.0f}% WIN RATE ({wins}W/{losses}L tracked)")
            elif win_rate >= 50:
                flags.append(f"{win_rate:.0f}% win rate ({wins}W/{losses}L)")

        # Check if repeat whale
        total_whale_trades = wallet_stats.get("total_whale_trades", 0)
        if total_whale_trades > 5:
            flags.append(f"REPEAT WHALE ({total_whale_trades} whale trades tracked)")

        return flags

    def _build_embed(
        self,
        trade: dict,
        trade_value: float,
        wallet: str,
        wallet_stats: dict,
        flags: list[str],
    ) -> dict:
        """Build Discord embed object."""
        side = trade.get("side", "UNKNOWN")
        # Green for BUY, Red for SELL
        color = 0x00FF00 if side == "BUY" else 0xFF0000

        # Build market URL
        event_slug = trade.get("eventSlug", "")
        market_url = f"https://polymarket.com/event/{event_slug}" if event_slug else ""
        title = trade.get("title", "Unknown Market")

        # Format market field
        market_field = f"[{title}]({market_url})" if market_url else title

        # Format trade details
        size = trade.get("size", 0)
        price = trade.get("price", 0)
        outcome = trade.get("outcome", "?")
        trade_desc = f"{side} {size:,.0f} {outcome} @ ${price:.2f}"

        # Format wallet (truncated)
        wallet_display = f"`{wallet[:8]}...{wallet[-6:]}`" if len(wallet) > 14 else f"`{wallet}`"

        embed = {
            "title": f"Whale Trade: ${trade_value:,.0f}",
            "color": color,
            "fields": [
                {"name": "Market", "value": market_field, "inline": False},
                {"name": "Trade", "value": trade_desc, "inline": True},
                {"name": "Value", "value": f"${trade_value:,.0f}", "inline": True},
                {"name": "Wallet", "value": wallet_display, "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Add flags if any
        if flags:
            embed["fields"].append(
                {"name": "Flags", "value": "\n".join(flags), "inline": False}
            )

        # Add wallet stats summary
        stats_parts = self._build_stats_summary(wallet_stats)
        if stats_parts:
            embed["fields"].append(
                {"name": "Wallet Stats", "value": " | ".join(stats_parts), "inline": False}
            )

        return embed

    def _build_stats_summary(self, wallet_stats: dict) -> list[str]:
        """Build wallet stats summary strings."""
        stats_parts = []

        volume = wallet_stats.get("volume") or wallet_stats.get("leaderboard_volume")
        if volume:
            stats_parts.append(f"Volume: ${volume:,.0f}")

        rank = wallet_stats.get("leaderboard_rank")
        if rank:
            stats_parts.append(f"Rank: #{rank}")

        trade_count = wallet_stats.get("trade_count")
        if trade_count is None:
            trade_count = wallet_stats.get("api_trade_count")
        if trade_count is not None and trade_count > 0:
            # API caps at 100, so 100 means "at least 100"
            display = "100+" if trade_count >= 100 else str(trade_count)
            stats_parts.append(f"API Trades: {display}")

        realized_pnl = wallet_stats.get("realized_pnl", 0)
        if realized_pnl != 0:
            stats_parts.append(f"Tracked P&L: ${realized_pnl:+,.0f}")

        return stats_parts

    async def send_test_message(self) -> bool:
        """Send a test message to verify webhook is working."""
        payload = {
            "content": "Polymarket Whale Scanner connected successfully!",
            "embeds": [
                {
                    "title": "Test Alert",
                    "description": "If you see this, the webhook is working correctly.",
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
