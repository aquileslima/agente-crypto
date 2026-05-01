"""
WebSocket Monitor — real-time price monitoring for stop loss / take profit detection.
Direct WebSocket connection to Binance with automatic reconnection.
"""
import asyncio
import json
import logging
import websockets
from typing import Callable, Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Monitor price in real-time via WebSocket. Detect SL/TP hits."""

    def __init__(self, ws_url: str, position: dict, ema_fast: float):
        """
        Args:
            ws_url: WebSocket URL (e.g., wss://fstream.binance.com/ws/ethusdt@bookTicker)
            position: Position dict with stop_price, tp1_price, direction, entry_price
            ema_fast: Current EMA21 value for trailing stop
        """
        self.ws_url = ws_url
        self.position = position
        self.ema_fast = ema_fast
        self.exit_callback: Optional[Callable[[dict], None]] = None
        self.running = False
        self.ws = None
        self.last_price = None
        self.last_message_time = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1

    def set_exit_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback to execute when exit condition is met."""
        self.exit_callback = callback

    async def monitor(self) -> Optional[dict]:
        """
        Monitor WebSocket stream until SL or TP is hit.
        Auto-reconnects on failure.
        Returns exit info dict if exit detected, else None.
        """
        self.running = True
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self._connect_and_monitor()
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 30)
                logger.warning(
                    f"WebSocket connection failed (attempt {self.reconnect_attempts}/"
                    f"{self.max_reconnect_attempts}): {e}. Reconnecting in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts reached. Stopping monitor.")
            self.running = False

        return None

    async def _connect_and_monitor(self) -> None:
        """Connect to WebSocket and monitor for exits."""
        async with websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=10,
            compression=None,
        ) as ws:
            self.ws = ws
            self.reconnect_attempts = 0
            logger.info(f"WebSocket connected to {self.ws_url}")

            while self.running:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(ws.recv(), timeout=60)
                    self.last_message_time = datetime.now(timezone.utc)
                    data = json.loads(message)

                    # bookTicker format: {s: symbol, b: bidPrice, B: bidQty, a: askPrice, A: askQty}
                    if "a" in data and "b" in data:
                        bid_price = float(data["b"])
                        ask_price = float(data["a"])
                        mid_price = (bid_price + ask_price) / 2

                        self.last_price = mid_price
                        logger.debug(
                            f"Price update: {mid_price:.2f} | bid={bid_price:.2f} "
                            f"ask={ask_price:.2f}"
                        )

                        # Check exit conditions
                        exit_info = self._check_exit(mid_price)
                        if exit_info:
                            logger.warning(f"Exit detected: {exit_info['reason']} @ {exit_info['price']:.2f}")
                            if self.exit_callback:
                                self.exit_callback(exit_info)
                            self.running = False
                            return

                except asyncio.TimeoutError:
                    logger.warning("WebSocket receive timeout")
                    raise ConnectionError("WebSocket timeout")
                except json.JSONDecodeError as e:
                    logger.debug(f"Invalid JSON from WebSocket: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    raise

    def _check_exit(self, current_price: float) -> Optional[dict]:
        """Check if SL or TP is hit at current price."""
        pos = self.position
        direction = pos["direction"]
        entry_price = pos.get("entry_price", 0)

        # Stop loss
        stop_price = pos.get("stop_price")
        if stop_price:
            if (direction == "LONG" and current_price <= stop_price) or (
                direction == "SHORT" and current_price >= stop_price
            ):
                loss_pct = ((current_price - entry_price) / entry_price) * 100
                return {
                    "reason": "STOP LOSS",
                    "price": current_price,
                    "pnl_pct": loss_pct,
                }

        # TP1 partial close
        if not pos.get("tp1_hit"):
            tp1_price = pos.get("tp1_price")
            if tp1_price:
                if (direction == "LONG" and current_price >= tp1_price) or (
                    direction == "SHORT" and current_price <= tp1_price
                ):
                    profit_pct = ((current_price - entry_price) / entry_price) * 100
                    return {
                        "reason": "TP1",
                        "price": current_price,
                        "pnl_pct": profit_pct,
                    }

        # Trailing stop on EMA fast
        if self.ema_fast > 0:
            if (direction == "LONG" and current_price <= self.ema_fast) or (
                direction == "SHORT" and current_price >= self.ema_fast
            ):
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                return {
                    "reason": "TRAILING STOP",
                    "price": current_price,
                    "pnl_pct": pnl_pct,
                }

        return None

    def stop(self) -> None:
        """Stop monitoring gracefully."""
        self.running = False
        logger.info("WebSocket monitor stopped")

    def get_last_price(self) -> Optional[float]:
        """Get last received price."""
        return self.last_price

    def get_connection_status(self) -> dict:
        """Get connection status info."""
        return {
            "running": self.running,
            "connected": self.ws is not None,
            "last_price": self.last_price,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "reconnect_attempts": self.reconnect_attempts,
        }
