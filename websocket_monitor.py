"""
WebSocket Monitor — real-time price monitoring for stop loss / take profit detection.
Connects to Binance WebSocket stream and monitors price updates.
"""
import asyncio
import json
import logging
import websockets
from typing import Callable

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Monitor price in real-time via WebSocket. Detect SL/TP hits."""

    def __init__(self, ws_url: str, position: dict, ema_fast: float):
        """
        Args:
            ws_url: WebSocket URL from exchange.get_websocket_url()
            position: Position dict with stop_price, tp1_price, direction
            ema_fast: Current EMA21 value for trailing stop
        """
        self.ws_url = ws_url
        self.position = position
        self.ema_fast = ema_fast
        self.exit_callback: Callable[[dict], None] | None = None
        self.running = False

    def set_exit_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback to execute when exit condition is met."""
        self.exit_callback = callback

    async def monitor(self) -> dict | None:
        """
        Monitor WebSocket stream until SL or TP is hit.
        Returns exit info dict if exit detected, else None.
        """
        self.running = True
        try:
            async with websockets.connect(self.ws_url) as ws:
                logger.info(f"WebSocket connected to {self.ws_url}")
                while self.running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=60)
                        data = json.loads(message)

                        # bookTicker format: {s: symbol, b: bidPrice, B: bidQty, a: askPrice, A: askQty}
                        if "a" in data:  # Ask price (use for LONG entries, bid for SHORT)
                            mid_price = (
                                float(data["a"]) + float(data["b"])
                            ) / 2  # Average of bid/ask
                            exit_info = self._check_exit(mid_price)
                            if exit_info:
                                logger.warning(f"Exit detected: {exit_info['reason']}")
                                if self.exit_callback:
                                    self.exit_callback(exit_info)
                                return exit_info

                    except asyncio.TimeoutError:
                        logger.warning("WebSocket timeout — reconnecting...")
                        continue
                    except json.JSONDecodeError:
                        logger.debug("Invalid JSON from WebSocket")
                        continue
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self.running = False
        return None

    def _check_exit(self, current_price: float) -> dict | None:
        """Check if SL or TP is hit at current price."""
        pos = self.position
        direction = pos["direction"]

        # Stop loss
        if (direction == "LONG" and current_price <= pos["stop_price"]) or (
            direction == "SHORT" and current_price >= pos["stop_price"]
        ):
            return {"reason": "STOP LOSS", "price": current_price}

        # TP1 partial close
        if not pos.get("tp1_hit"):
            if (direction == "LONG" and current_price >= pos["tp1_price"]) or (
                direction == "SHORT" and current_price <= pos["tp1_price"]
            ):
                return {"reason": "TP1", "price": current_price}

        # Trailing stop on EMA fast
        if (direction == "LONG" and current_price <= self.ema_fast) or (
            direction == "SHORT" and current_price >= self.ema_fast
        ):
            return {"reason": "TRAILING STOP", "price": current_price}

        return None

    def stop(self) -> None:
        """Stop monitoring."""
        self.running = False
