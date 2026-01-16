#!/usr/bin/env python3
"""
Quick script to inspect raw trade data from RTDS WebSocket.
Prints the first few trades to see all available fields.
"""
import asyncio
import json
import websockets

RTDS_URL = "wss://ws-live-data.polymarket.com"
MAX_TRADES = 5  # Number of trades to capture before exiting


async def main():
    print(f"Connecting to {RTDS_URL}...")

    async with websockets.connect(RTDS_URL) as ws:
        # Subscribe to trades
        msg = {
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}],
        }
        await ws.send(json.dumps(msg))
        print("Subscribed to activity/trades topic\n")

        trade_count = 0
        async for message in ws:
            try:
                data = json.loads(message)

                if data.get("topic") == "activity" and data.get("type") == "trades":
                    payload = data.get("payload", [])
                    trades = payload if isinstance(payload, list) else [payload]

                    for trade in trades:
                        trade_count += 1
                        print(f"=== Trade #{trade_count} ===")
                        print(json.dumps(trade, indent=2))
                        print()

                        if trade_count >= MAX_TRADES:
                            print(f"\nCaptured {MAX_TRADES} trades. Exiting.")
                            return

            except json.JSONDecodeError:
                # Subscription confirmations etc.
                print(f"Non-JSON: {message[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
