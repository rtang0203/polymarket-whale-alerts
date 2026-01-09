"""
Tests for Discord alert flag and stats logic.

These tests verify the wallet flag detection and stats display
work correctly with various trade count scenarios.
"""

import pytest
from src.discord_bot import DiscordAlerter


class TestDiscordFlags:
    """Tests for wallet flag logic."""

    @pytest.fixture
    def alerter(self):
        """Create alerter without webhook (just for testing flag logic)."""
        return DiscordAlerter(webhook_url="https://example.com/webhook")

    def test_new_wallet_flag_zero_trades(self, alerter):
        """Wallet with 0 trades should be flagged as NEW WALLET."""
        stats = {"trade_count": 0}
        flags = alerter._build_flags(stats)
        assert any("NEW WALLET" in f and "0 previous trades" in f for f in flags)

    def test_new_wallet_flag_few_trades(self, alerter):
        """Wallet with <10 trades should be flagged as NEW WALLET."""
        stats = {"trade_count": 5}
        flags = alerter._build_flags(stats)
        assert any("NEW WALLET" in f and "5 previous trades" in f for f in flags)

    def test_no_new_wallet_flag_many_trades(self, alerter):
        """Wallet with 10+ trades should NOT be flagged as NEW WALLET."""
        stats = {"trade_count": 50}
        flags = alerter._build_flags(stats)
        assert not any("NEW WALLET" in f for f in flags)

    def test_no_new_wallet_flag_when_api_failed(self, alerter):
        """When trade_count is None (API failed), should NOT flag as NEW WALLET."""
        stats = {"trade_count": None, "leaderboard_rank": 100}
        flags = alerter._build_flags(stats)
        assert not any("NEW WALLET" in f for f in flags)

    def test_no_new_wallet_flag_at_100_trades(self, alerter):
        """Wallet hitting 100 trade limit should NOT be flagged as NEW WALLET."""
        stats = {"trade_count": 100}
        flags = alerter._build_flags(stats)
        assert not any("NEW WALLET" in f for f in flags)


class TestDiscordStats:
    """Tests for wallet stats summary logic."""

    @pytest.fixture
    def alerter(self):
        """Create alerter without webhook (just for testing stats logic)."""
        return DiscordAlerter(webhook_url="https://example.com/webhook")

    def test_stats_show_100_plus(self, alerter):
        """When trade_count is 100 (API limit), should show '100+'."""
        stats = {"trade_count": 100}
        summary = alerter._build_stats_summary(stats)
        assert any("API Trades: 100+" in s for s in summary)

    def test_stats_show_exact_count_under_100(self, alerter):
        """When trade_count < 100, should show exact number."""
        stats = {"trade_count": 42}
        summary = alerter._build_stats_summary(stats)
        assert any("API Trades: 42" in s for s in summary)

    def test_stats_no_trades_when_none(self, alerter):
        """When trade_count is None (API failed), should not show API Trades."""
        stats = {"trade_count": None, "leaderboard_rank": 100}
        summary = alerter._build_stats_summary(stats)
        assert not any("API Trades" in s for s in summary)

    def test_stats_no_trades_when_zero(self, alerter):
        """When trade_count is 0, should not show API Trades (nothing to show)."""
        stats = {"trade_count": 0}
        summary = alerter._build_stats_summary(stats)
        assert not any("API Trades" in s for s in summary)
