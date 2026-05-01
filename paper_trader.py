"""
Paper Trader — simulates trade execution without touching real money.
Mirrors the exact exit logic from BacktestEngine for consistency.
State is persisted to JSON between runs.
"""
import json
import logging
import os
from datetime import datetime, timezone

from config import STARTING_CAPITAL, LEVERAGE, RISK_PER_TRADE, STOP_LOSS_BUFFER, \
    TP1_RATIO, TP1_SIZE, MIN_STOP_DISTANCE_PCT, USE_TRAILING_STOP

logger = logging.getLogger(__name__)

STATE_FILE = "trades/paper_state.json"


class PaperTrader:
    def __init__(self, params: dict = None):
        self.params = params or {
            "leverage": LEVERAGE,
            "risk_per_trade": RISK_PER_TRADE,
            "stop_loss_buffer": STOP_LOSS_BUFFER,
            "tp1_ratio": TP1_RATIO,
            "tp1_size": TP1_SIZE,
            "min_stop_distance_pct": MIN_STOP_DISTANCE_PCT,
            "use_trailing_stop": USE_TRAILING_STOP,
        }
        self.state = self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load paper state: {e}")
        return {
            "capital": float(STARTING_CAPITAL),
            "initial_capital": float(STARTING_CAPITAL),
            "position": None,
            "total_trades": 0,
            "winning_trades": 0,
            "total_pnl": 0.0,
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

    def open_position(self, direction: str, entry_price: float, ema_mid: float) -> dict | None:
        """
        Open a new paper position. Returns position dict or None if invalid setup.
        Mirrors BacktestEngine._open_position_fast() exactly.
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
        }
        self.state["position"] = position
        self._save_state()

        logger.info(
            f"[PAPER] Opened {direction} @ ${entry_price:,.2f} | "
            f"SL=${stop_price:,.2f} | TP1=${tp1_price:,.2f} | size={size:.4f}"
        )
        return position

    # ── Check exits ───────────────────────────────────────────────────────────

    def check_exits(self, current_price: float, ema_fast: float) -> dict | None:
        """
        Check stop loss, TP1, and trailing stop against current price.
        Mirrors BacktestEngine._check_exit_fast() exactly.

        Returns closed trade dict if position was closed, else None.
        """
        if not self.has_position():
            return None

        pos = self.state["position"]
        direction = pos["direction"]
        closed_trade = None

        # ── Stop loss ─────────────────────────────────────────────────────────
        if (direction == "LONG" and current_price <= pos["stop_price"]) or \
           (direction == "SHORT" and current_price >= pos["stop_price"]):
            closed_trade = self._close_position(current_price, "STOP LOSS")
            return closed_trade

        # ── TP1 partial close ─────────────────────────────────────────────────
        if not pos["tp1_hit"]:
            if (direction == "LONG" and current_price >= pos["tp1_price"]) or \
               (direction == "SHORT" and current_price <= pos["tp1_price"]):
                closed_size = pos["current_size"] * self.params["tp1_size"]
                if direction == "LONG":
                    profit = (pos["tp1_price"] - pos["entry_price"]) * closed_size
                else:
                    profit = (pos["entry_price"] - pos["tp1_price"]) * closed_size
                self.state["capital"] += profit
                pos["current_size"] -= closed_size
                pos["tp1_hit"] = True
                pos["tp1_profit"] = profit
                self._save_state()
                logger.info(
                    f"[PAPER] TP1 hit @ ${pos['tp1_price']:,.2f} | "
                    f"partial PnL=${profit:+,.2f} | remaining={pos['current_size']:.4f}"
                )

        # ── Trailing stop on EMA fast ─────────────────────────────────────────
        if self.params["use_trailing_stop"]:
            if (direction == "LONG" and current_price <= ema_fast) or \
               (direction == "SHORT" and current_price >= ema_fast):
                closed_trade = self._close_position(current_price, "TRAILING STOP")
                return closed_trade

        self._save_state()
        return None

    # ── Close position ────────────────────────────────────────────────────────

    def _close_position(self, close_price: float, reason: str) -> dict:
        pos = self.state["position"]
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        remaining_size = pos["current_size"]

        if direction == "LONG":
            pnl_remaining = (close_price - entry_price) * remaining_size
        else:
            pnl_remaining = (entry_price - close_price) * remaining_size

        self.state["capital"] += pnl_remaining
        total_pnl = pnl_remaining + pos["tp1_profit"]

        entry_dt = datetime.fromisoformat(pos["entry_time"])
        duration_h = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

        trade = {
            "direction": direction,
            "entry_time": pos["entry_time"],
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "entry_price": entry_price,
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
        self._save_state()

        logger.info(
            f"[PAPER] Closed {direction} @ ${close_price:,.2f} | "
            f"Reason: {reason} | PnL=${total_pnl:+,.2f} | Capital=${self.state['capital']:,.2f}"
        )
        return trade

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        s = self.state
        n = s["total_trades"]
        wins = s["winning_trades"]
        return {
            "capital": s["capital"],
            "initial_capital": s["initial_capital"],
            "total_pnl": s["total_pnl"],
            "return_pct": (s["capital"] - s["initial_capital"]) / s["initial_capital"] * 100,
            "total_trades": n,
            "win_rate": wins / n * 100 if n > 0 else 0,
            "has_position": self.has_position(),
        }
