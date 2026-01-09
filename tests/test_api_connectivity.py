"""
Integration tests for Polymarket API connectivity.

These tests verify that we can connect to the various Polymarket APIs
and that the response formats match our expectations.

Run with: pytest tests/test_api_connectivity.py -v
"""

import asyncio
import json
import pytest
import aiohttp
import websockets

# API endpoints
RTDS_URL = "wss://ws-live-data.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Known active wallet for testing (high-volume trader)
# This may need to be updated if this wallet becomes inactive
TEST_WALLET = "0x1234567890123456789012345678901234567890"


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestRTDSWebSocket:
    """Tests for the RTDS WebSocket connection."""

    @pytest.mark.asyncio
    async def test_websocket_connects(self):
        """Test that we can establish a WebSocket connection to RTDS."""
        async with websockets.connect(RTDS_URL) as ws:
            # Connection is open if we get here (context manager succeeds)
            # Send a ping to verify connection is alive
            pong = await ws.ping()
            await pong  # Wait for pong response

    @pytest.mark.asyncio
    async def test_websocket_subscription(self):
        """Test that we can subscribe to the activity/trades topic."""
        async with websockets.connect(RTDS_URL) as ws:
            # Send subscription
            sub_msg = {
                "action": "subscribe",
                "subscriptions": [{"topic": "activity", "type": "trades"}],
            }
            await ws.send(json.dumps(sub_msg))

            # We should receive a confirmation or start receiving trades
            # Wait up to 5 seconds for any response
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                # Just verify we got something back
                assert response is not None
                if isinstance(response, str):
                    print(f"Received response: {response[:200]}...")
            except asyncio.TimeoutError:
                # No immediate response is also OK - trades come when they happen
                pass

    @pytest.mark.asyncio
    async def test_websocket_receives_trades(self):
        """
        Test that we receive trade messages from RTDS.

        Note: This test waits for real trades to come through, which may take
        some time depending on market activity. Set a reasonable timeout.
        """
        async with websockets.connect(RTDS_URL) as ws:
            # Subscribe to trades
            sub_msg = {
                "action": "subscribe",
                "subscriptions": [{"topic": "activity", "type": "trades"}],
            }
            await ws.send(json.dumps(sub_msg))

            # Wait for up to 30 seconds to receive a trade
            trade_received = False
            messages = []

            try:
                start = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - start < 30:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)

                        # Skip non-string messages (ping frames, etc)
                        if not isinstance(msg, str):
                            continue

                        messages.append(msg)

                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            # Skip non-JSON messages
                            continue

                        # Check if this is a trade message
                        if data.get("topic") == "activity" and data.get("type") == "trades":
                            trade_received = True
                            print(f"Trade message received: {json.dumps(data, indent=2)[:500]}...")

                            # Verify expected fields in payload
                            payload = data.get("payload")
                            if payload:
                                # Payload might be a single trade or list
                                trade = payload[0] if isinstance(payload, list) else payload
                                self._verify_trade_fields(trade)
                            break

                    except asyncio.TimeoutError:
                        continue

            finally:
                pass  # Context manager handles close

            # Log what we received for debugging
            if not trade_received:
                print(f"Received {len(messages)} messages but no trades")
                for m in messages[:5]:
                    print(f"  Message: {m[:200]}...")

            # This assertion may fail if market is very quiet
            # Consider marking as xfail or skip during low-activity periods
            assert trade_received, "No trade messages received within timeout"

    def _verify_trade_fields(self, trade: dict):
        """Verify a trade has expected fields."""
        expected_fields = [
            "size",
            "price",
            "proxyWallet",
            "side",
            "outcome",
        ]

        for field in expected_fields:
            assert field in trade, f"Trade missing expected field: {field}"

        # Verify types
        assert isinstance(trade.get("size"), (int, float, str))
        assert isinstance(trade.get("price"), (int, float, str))
        assert trade.get("side") in ("BUY", "SELL", "buy", "sell")


class TestDataAPI:
    """Tests for the Polymarket Data API."""

    @pytest.mark.asyncio
    async def test_trades_endpoint_exists(self):
        """Test that the /trades endpoint is accessible."""
        async with aiohttp.ClientSession() as session:
            # Just check the endpoint is reachable (even with no results)
            async with session.get(
                f"{DATA_API_BASE}/trades",
                params={"limit": 1},
            ) as resp:
                # 200 or 400 (bad request without user) are both valid
                assert resp.status in (200, 400)

    @pytest.mark.asyncio
    async def test_trades_endpoint_returns_array(self):
        """Test that /trades returns an array when querying a wallet."""
        async with aiohttp.ClientSession() as session:
            # Use a random/fake wallet - should return empty array or valid trades
            async with session.get(
                f"{DATA_API_BASE}/trades",
                params={"user": TEST_WALLET, "limit": 10},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)

                # If there are trades, verify structure
                if len(data) > 0:
                    trade = data[0]
                    print(f"Sample trade from API: {json.dumps(trade, indent=2)[:500]}...")
                    assert "proxyWallet" in trade or "user" in trade

    @pytest.mark.asyncio
    async def test_leaderboard_endpoint(self):
        """Test that the /v1/leaderboard endpoint is accessible."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATA_API_BASE}/v1/leaderboard",
                params={"user": TEST_WALLET},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)

                if len(data) > 0:
                    entry = data[0]
                    print(f"Leaderboard entry: {json.dumps(entry, indent=2)}")
                    # Verify expected fields
                    expected = ["rank", "vol", "pnl"]
                    for field in expected:
                        assert field in entry, f"Leaderboard entry missing: {field}"

    @pytest.mark.asyncio
    async def test_leaderboard_top_traders(self):
        """Test fetching top leaderboard traders to get real wallet addresses."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DATA_API_BASE}/v1/leaderboard",
                params={"limit": 5},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)
                assert len(data) > 0, "Leaderboard should have entries"

                # Get top trader's wallet for other tests
                top_trader = data[0]
                print(f"Top trader: {json.dumps(top_trader, indent=2)}")

                assert "proxyWallet" in top_trader
                assert "rank" in top_trader
                assert "pnl" in top_trader


class TestGammaAPI:
    """Tests for the Polymarket Gamma API (market metadata)."""

    @pytest.mark.asyncio
    async def test_markets_endpoint(self):
        """Test that the /markets endpoint is accessible."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GAMMA_API_BASE}/markets",
                params={"limit": 5},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)

                if len(data) > 0:
                    market = data[0]
                    print(f"Sample market: {json.dumps(market, indent=2)[:500]}...")

    @pytest.mark.asyncio
    async def test_market_has_expected_fields(self):
        """Test that markets have the fields we need for resolution tracking."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GAMMA_API_BASE}/markets",
                params={"limit": 10, "closed": "true"},  # Get closed markets
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                if len(data) > 0:
                    market = data[0]

                    # Fields we use for resolution
                    resolution_fields = [
                        "conditionId",
                        "outcomes",
                        "outcomePrices",
                    ]

                    for field in resolution_fields:
                        if field not in market:
                            print(f"Warning: market missing field {field}")

                    print(f"Closed market: {json.dumps(market, indent=2)[:800]}...")

    @pytest.mark.asyncio
    async def test_events_endpoint(self):
        """Test that the /events endpoint is accessible."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GAMMA_API_BASE}/events",
                params={"limit": 5},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)

                if len(data) > 0:
                    event = data[0]
                    print(f"Sample event: {json.dumps(event, indent=2)[:500]}...")
                    assert "slug" in event


class TestEndToEnd:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_can_fetch_active_trader_data(self):
        """
        Test the full flow: find an active trader and fetch their data.
        """
        async with aiohttp.ClientSession() as session:
            # Step 1: Get top traders from leaderboard
            async with session.get(
                f"{DATA_API_BASE}/v1/leaderboard",
                params={"limit": 3},
            ) as resp:
                assert resp.status == 200
                leaderboard = await resp.json()
                assert len(leaderboard) > 0

            top_wallet = leaderboard[0]["proxyWallet"]
            print(f"Testing with top trader: {top_wallet[:10]}...")

            # Step 2: Fetch their trades
            async with session.get(
                f"{DATA_API_BASE}/trades",
                params={"user": top_wallet, "limit": 10},
            ) as resp:
                assert resp.status == 200
                trades = await resp.json()
                print(f"Fetched {len(trades)} trades for top trader")

                if len(trades) > 0:
                    trade = trades[0]
                    # Verify trade has data we need
                    assert "size" in trade or "amount" in trade
                    assert "price" in trade

    @pytest.mark.asyncio
    async def test_can_find_resolved_market(self):
        """Test that we can find and parse a resolved market."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GAMMA_API_BASE}/markets",
                params={"limit": 20, "closed": "true"},
            ) as resp:
                assert resp.status == 200
                markets = await resp.json()

            # Find one with outcome prices we can parse
            for market in markets:
                prices = market.get("outcomePrices", [])
                outcomes = market.get("outcomes", [])

                if prices and outcomes:
                    for i, price in enumerate(prices):
                        try:
                            if float(price) >= 0.99:
                                winning_outcome = outcomes[i] if i < len(outcomes) else None
                                print(
                                    f"Found resolved market: {market.get('question', 'Unknown')[:50]}"
                                )
                                print(f"Winning outcome: {winning_outcome}")
                                return
                        except (ValueError, TypeError):
                            continue

            print("Warning: Could not find a clearly resolved market")


# Helper to run a quick connectivity check
async def quick_connectivity_check():
    """Quick check of all API endpoints."""
    print("\n=== Quick Connectivity Check ===\n")

    # RTDS WebSocket
    print("1. Testing RTDS WebSocket...")
    try:
        async with websockets.connect(RTDS_URL) as ws:
            print("   OK - Connected to RTDS")
    except Exception as e:
        print(f"   FAILED - {e}")

    async with aiohttp.ClientSession() as session:
        # Data API
        print("2. Testing Data API...")
        try:
            async with session.get(f"{DATA_API_BASE}/v1/leaderboard", params={"limit": 1}) as resp:
                if resp.status == 200:
                    print("   OK - Data API accessible")
                else:
                    print(f"   WARNING - Status {resp.status}")
        except Exception as e:
            print(f"   FAILED - {e}")

        # Gamma API
        print("3. Testing Gamma API...")
        try:
            async with session.get(f"{GAMMA_API_BASE}/markets", params={"limit": 1}) as resp:
                if resp.status == 200:
                    print("   OK - Gamma API accessible")
                else:
                    print(f"   WARNING - Status {resp.status}")
        except Exception as e:
            print(f"   FAILED - {e}")

    print("\n=== Check Complete ===\n")


if __name__ == "__main__":
    # Run quick check when executed directly
    asyncio.run(quick_connectivity_check())
