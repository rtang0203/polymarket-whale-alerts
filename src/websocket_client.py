import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

RTDS_URL = "wss://ws-live-data.polymarket.com"
PING_INTERVAL = 5  # seconds
DATA_TIMEOUT = 300  # 5 minutes - force reconnect if no data
RECONNECT_DELAY_BASE = 5  # seconds
RECONNECT_DELAY_MAX = 60  # seconds


class RTDSClient:
    """
    WebSocket client for Polymarket's Real-Time Data Service (RTDS).

    Connects to the activity/trades topic and filters for whale trades.
    Implements automatic reconnection with exponential backoff and
    data timeout detection.
    """

    def __init__(
        self,
        on_whale_trade: Callable[[dict], Awaitable[None]],
        whale_threshold: float = 10000,
    ):
        self.on_whale_trade = on_whale_trade
        self.whale_threshold = whale_threshold
        self.last_data_time = datetime.now()
        self.ws = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY_BASE
        self._message_count = 0
        self._whale_count = 0

    async def connect(self):
        """
        Main connection loop. Connects to RTDS and handles reconnection.
        This method runs indefinitely until stop() is called.
        """
        self._running = True
        while self._running:
            try:
                logger.info(f"Connecting to RTDS at {RTDS_URL}...")
                async with websockets.connect(
                    RTDS_URL,
                    ping_interval=None,  # We handle pings ourselves
                    ping_timeout=None,
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = RECONNECT_DELAY_BASE  # Reset on success
                    logger.info("Connected to RTDS")

                    await self._subscribe()

                    # Run ping, receive, and timeout checker concurrently
                    await asyncio.gather(
                        self._ping_loop(),
                        self._receive_loop(),
                        self._data_timeout_checker(),
                    )
            except ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
            except Exception as e:
                logger.error(f"Connection error: {e}")

            if self._running:
                logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff with cap
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_DELAY_MAX
                )

    def stop(self):
        """Stop the client and close the connection."""
        self._running = False
        if self.ws:
            asyncio.create_task(self.ws.close())

    async def _subscribe(self):
        """Subscribe to the activity/trades topic."""
        msg = {
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}],
        }
        await self.ws.send(json.dumps(msg))
        logger.info("Subscribed to activity/trades topic")

    async def _ping_loop(self):
        """Send pings to keep the connection alive."""
        while self._running and self.ws:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await self.ws.ping()
            except Exception as e:
                logger.warning(f"Ping failed: {e}")
                break

    async def _data_timeout_checker(self):
        """Force reconnect if no data received for DATA_TIMEOUT seconds."""
        while self._running and self.ws:
            await asyncio.sleep(60)  # Check every minute
            elapsed = (datetime.now() - self.last_data_time).total_seconds()
            if elapsed > DATA_TIMEOUT:
                logger.warning(
                    f"Data timeout ({elapsed:.0f}s since last message) - forcing reconnect"
                )
                await self.ws.close()
                break

    async def _receive_loop(self):
        """Receive and process messages from RTDS."""
        async for message in self.ws:
            self.last_data_time = datetime.now()
            self._message_count += 1

            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse message: {message[:100]}...")
            except Exception as e:
                logger.error(f"Error handling message: {e}")

    async def _handle_message(self, data: dict):
        """
        Handle incoming RTDS message.

        RTDS wraps messages with topic/type metadata. The actual trade
        data is in the payload field.
        """
        # Check if this is a trade message
        if data.get("topic") != "activity" or data.get("type") != "trades":
            return

        # Extract the trade payload
        # Note: The exact structure may vary - this handles both direct payload
        # and array-wrapped payloads
        payload = data.get("payload")
        if not payload:
            return

        # Handle case where payload is an array of trades
        trades = payload if isinstance(payload, list) else [payload]

        for trade in trades:
            await self._process_trade(trade)

    async def _process_trade(self, trade: dict):
        """Process a single trade and check if it's a whale trade."""
        size = trade.get("size", 0)
        price = trade.get("price", 0)

        # Handle size as string (some APIs return string numbers)
        if isinstance(size, str):
            size = float(size)
        if isinstance(price, str):
            price = float(price)

        trade_value = size * price

        if trade_value >= self.whale_threshold:
            self._whale_count += 1
            logger.info(
                f"Whale trade #{self._whale_count}: ${trade_value:,.0f} on {trade.get('title', 'Unknown')}"
            )
            await self.on_whale_trade(trade)

    def get_stats(self) -> dict:
        """Get client statistics."""
        # Check connection state (websockets v15+ uses state.name instead of .open)
        connected = False
        if self.ws is not None:
            try:
                connected = self.ws.state.name == "OPEN"
            except AttributeError:
                connected = False

        return {
            "messages_received": self._message_count,
            "whale_trades_detected": self._whale_count,
            "last_data_time": self.last_data_time.isoformat(),
            "connected": connected,
        }
