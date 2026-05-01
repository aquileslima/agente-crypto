"""
Real Trader — executes real orders on Binance (testnet or live).
Mirrors PaperTrader interface but places actual orders.
Uses WebSocket for real-time SL/TP monitoring.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from config import STARTING_CAPITAL, LEVERAGE, RISK_PER_TRADE, STOP_LOSS_BUFFER, \
    TP1_RATIO, TP1_SIZE, MIN_STOP_DISTANCE_PCT, USE_TRAILING_STOP, SYMBOL
from exchange import _build_exchange
from websocket_direct import BinanceWebSocketClient

logger = logging.getLogger(__name__)

STATE_FILE = "trades/real_state.json"


class RealTrader:
    """Execute real orders on Binance Futures (testnet or live)."""

    def __init__(self):
        self.exchange = _build_exchange()
        self.params = {
            "leverage": LEVERAGE,
            "risk_per_trade": RISK_PER_TRADE,
            "stop_loss_buffer": STOP_LOSS_BUFFER,
            "tp1_ratio": TP1_RATIO,
            "tp1_size": TP1_SIZE,
            "min_stop_distance_pct": MIN_STOP_DISTANCE_PCT,
            "use_trailing_stop": USE_TRAILING_STOP,
        }
        self.state = self._load_state()
        self._set_leverage()

    def _set_leverage(self) -> None:
        """Set leverage to configured value."""
        try:
            self.exchange.set_leverage(self.params["leverage"], SYMBOL)
            logger.info(
                f"Leverage set to {self.params['leverage']}x for {SYMBOL}"
            )
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load real state: {e}")
        return {
            "capital": float(STARTING_CAPITAL),
            "initial_capital": float(STARTING_CAPITAL),
            "position": None,
            "total_trades": 0,
            "winning_trades": 0,
            "total_pnl": 0.0,
            "active_orders": {},  # Maps order_id -> order data
        }

    def _save_state(self) -> None:
        os.makedirs("trades", exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    # ── Position queries ──────────────────────────────────────────────────────

    def has_position(self) -> bool:
        return self.state["position"] is not None

    def get_position(self) -> dict | None:
        return self.state["position"]

    @property
    def capital(self) -> float:
        return self.state["capital"]

    # ── Open position ─────────────────────────────────────────────────────────

    def open_position(
        self, direction: str, entry_price: float, ema_mid: float
    ) -> dict | None:
        """
        Open a real position via market order.
        Same logic as PaperTrader but places actual order.
        """
        if self.has_position():
            logger.warning("Already in position — ignoring open signal.")
            return None

        p = self.params
        buffer = p["stop_loss_buffer"]

        if direction == "LONG":
            stop_price = ema_mid * (1 - buffer)
            if stop_price >= entry_price:
                logger.warning("Stop >= entry for LONG — skipping.")
                return None
        else:
            stop_price = ema_mid * (1 + buffer)
            if stop_price <= entry_price:
                logger.warning("Stop <= entry for SHORT — skipping.")
                return None

        price_risk = abs(entry_price - stop_price)
        if price_risk < entry_price * p["min_stop_distance_pct"]:
            logger.warning("Stop too close to entry — skipping.")
            return None

        risk_amount = self.capital * p["risk_per_trade"]
        size = risk_amount / price_risk
        max_notional = self.capital * p["leverage"]
        size = min(size, max_notional / entry_price)

        tp1_price = (
            entry_price + price_risk * p["tp1_ratio"]
            if direction == "LONG"
            else entry_price - price_risk * p["tp1_ratio"]
        )

        # Place market order
        try:
            side = "buy" if direction == "LONG" else "sell"
            order = self.exchange.create_market_order(SYMBOL, side, size)
            order_id = order["id"]
            logger.info(
                f"[REAL] Opened {direction} order {order_id} @ ${entry_price:,.2f} | size={size:.4f}"
            )
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

        position = {
            "direction": direction,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "entry_price": entry_price,
            "stop_price": stop_price,
            "tp1_price": tp1_price,
            "tp1_hit": False,
            "tp1_profit": 0.0,
            "original_size": size,
            "current_size": size,
            "entry_order_id": order_id,
            "sl_order_id": None,
            "tp1_order_id": None,
        }

        self.state["position"] = position
        self.state["active_orders"][order_id] = {
            "side": side,
            "size": size,
            "type": "entry",
        }
        self._save_state()

        return position

    # ── Monitor exits (with WebSocket) ────────────────────────────────────────

    async def monitor_exits_async(self, ema_fast: float) -> dict | None:
        """
        Monitor position exits in real-time via WebSocket (pure implementation).
        Connects directly to Binance bookTicker stream and monitors for SL/TP/trailing stop.
        Returns closed trade dict if position was closed, else None.
        """
        if not self.has_position():
            return None

        pos = self.state["position"]
        symbol = SYMBOL.replace("/", "").lower()  # ETHUSDT

        # WebSocket client for real-time price updates
        ws_client = BinanceWebSocketClient(symbol, stream_type="bookTicker")

        exit_detected = {"trade": None}

        async def on_price_update(data: dict) -> None:
            """Process real-time price updates and check for exit conditions."""
            if exit_detected["trade"] is not None:
                # Already exited, stop monitoring
                ws_client.stop()
                return

            if data.get("type") == "price_update":
                current_price = data.get("mid", 0)

                # Check exit conditions
                exit_info = self._check_exit_condition(current_price, ema_fast)
                if exit_info:
                    logger.warning(f"Exit condition detected: {exit_info['reason']} @ ${current_price:.2f}")

                    # Execute exit order
                    trade = await self._execute_exit(exit_info)
                    if trade:
                        exit_detected["trade"] = trade
                        ws_client.stop()

        ws_client.set_callback(on_price_update)

        try:
            await asyncio.wait_for(ws_client.connect(), timeout=None)
        except asyncio.CancelledError:
            logger.debug("WebSocket monitor cancelled")
        except Exception as e:
            logger.error(f"WebSocket monitor error: {e}")
        finally:
            ws_client.stop()

        return exit_detected["trade"]

    def _check_exit_condition(self, current_price: float, ema_fast: float) -> dict | None:
        """Check if current price triggers any exit condition."""
        pos = self.state["position"]
        if not pos:
            return None

        direction = pos["direction"]
        entry_price = pos["entry_price"]

        # Stop Loss check
        stop_price = pos.get("stop_price")
        if stop_price:
            if (direction == "LONG" and current_price <= stop_price) or \
               (direction == "SHORT" and current_price >= stop_price):
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                return {
                    "reason": "STOP LOSS",
                    "price": current_price,
                    "pnl_pct": pnl_pct,
                }

        # TP1 partial close check
        if not pos.get("tp1_hit"):
            tp1_price = pos.get("tp1_price")
            if tp1_price:
                if (direction == "LONG" and current_price >= tp1_price) or \
                   (direction == "SHORT" and current_price <= tp1_price):
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    return {
                        "reason": "TP1",
                        "price": current_price,
                        "pnl_pct": pnl_pct,
                    }

        # Trailing stop check (on EMA fast)
        if ema_fast > 0:
            if (direction == "LONG" and current_price <= ema_fast) or \
               (direction == "SHORT" and current_price >= ema_fast):
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                return {
                    "reason": "TRAILING STOP",
                    "price": current_price,
                    "pnl_pct": pnl_pct,
                }

        return None

    async def _execute_exit(self, exit_info: dict) -> dict | None:
        """Execute exit order when SL/TP is detected."""
        pos = self.state["position"]
        if not pos:
            return None

        reason = exit_info["reason"]
        close_price = exit_info["price"]

        try:
            direction = pos["direction"]
            side = "sell" if direction == "LONG" else "buy"

            if reason == "TP1" and not pos["tp1_hit"]:
                # Close 50% of position at TP1
                close_size = pos["current_size"] * self.params["tp1_size"]
                order = self.exchange.create_market_order(
                    SYMBOL, side, close_size, params={"reduceOnly": True}
                )
                logger.info(
                    f"[REAL] TP1 close order {order['id']} @ ${close_price:,.2f}"
                )
                pos["tp1_hit"] = True
                pos["tp1_order_id"] = order["id"]
                pos["current_size"] -= close_size
                if direction == "LONG":
                    profit = (close_price - pos["entry_price"]) * close_size
                else:
                    profit = (pos["entry_price"] - close_price) * close_size
                pos["tp1_profit"] = profit
                self.state["capital"] += profit
            else:
                # Close remaining position
                close_size = pos["current_size"]
                order = self.exchange.create_market_order(
                    SYMBOL, side, close_size, params={"reduceOnly": True}
                )
                logger.info(
                    f"[REAL] Close order {order['id']} ({reason}) @ ${close_price:,.2f}"
                )

                if direction == "LONG":
                    pnl_remaining = (close_price - pos["entry_price"]) * close_size
                else:
                    pnl_remaining = (pos["entry_price"] - close_price) * close_size

                self.state["capital"] += pnl_remaining
                total_pnl = pnl_remaining + pos["tp1_profit"]

                entry_dt = datetime.fromisoformat(pos["entry_time"])
                duration_h = (
                    datetime.now(timezone.utc) - entry_dt
                ).total_seconds() / 3600

                trade = {
                    "direction": direction,
                    "entry_time": pos["entry_time"],
                    "exit_time": datetime.now(timezone.utc).isoformat(),
                    "entry_price": pos["entry_price"],
                    "exit_price": close_price,
                    "original_size": pos["original_size"],
                    "pnl": total_pnl,
                    "reason": reason,
                    "duration_h": duration_h,
                    "tp1_hit": pos["tp1_hit"],
                    "capital_after": self.state["capital"],
                }

                self.state["total_trades"] += 1
                if total_pnl > 0:
                    self.state["winning_trades"] += 1
                self.state["total_pnl"] += total_pnl
                self.state["position"] = None

                logger.info(
                    f"[REAL] Closed {direction} @ ${close_price:,.2f} | "
                    f"PnL=${total_pnl:+,.2f} | Capital=${self.state['capital']:,.2f}"
                )
                self._save_state()
                return trade

            self._save_state()
            return None

        except Exception as e:
            logger.error(f"Error executing exit: {e}")
            return None

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        s = self.state
        n = s["total_trades"]
        wins = s["winning_trades"]
        return {
            "capital": s["capital"],
            "initial_capital": s["initial_capital"],
            "total_pnl": s["total_pnl"],
            "return_pct": (s["capital"] - s["initial_capital"])
            / s["initial_capital"]
            * 100,
            "total_trades": n,
            "win_rate": wins / n * 100 if n > 0 else 0,
            "has_position": self.has_position(),
        }
