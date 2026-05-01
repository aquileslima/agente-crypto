"""
Bot — main live/paper trading loop.
Runs every hour (aligned to candle close), calls all agents, executes signals.
In live mode: uses WebSocket real-time monitoring for SL/TP.

Usage:
  python bot.py          # runs continuously
  python bot.py --once   # single analysis cycle (for testing)
"""
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from config import SYMBOL, STARTING_CAPITAL
from market_state import get_current_market_state
from orchestrator import run_analysis
from paper_trader import PaperTrader
from exchange import get_current_price, is_live_mode, is_testnet
from telegram_notifier import (
    send_signal, send_trade_opened, send_trade_closed,
    send_position_update, send_error, send_startup,
)
from agents.reflect_agent import save_trade

MODE = os.getenv("TRADING_MODE", "paper").lower()

# Import RealTrader only if needed (live mode)
if is_live_mode():
    from real_trader import RealTrader
    logger.info(f"Live mode detected. Using RealTrader (Testnet={is_testnet()})")
else:
    RealTrader = None


# ── Timing ────────────────────────────────────────────────────────────────────

def _next_candle_time() -> datetime:
    """Return the next hourly candle close time + 30s buffer."""
    now = datetime.now(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour + timedelta(seconds=30)


def _wait_until_next_candle() -> None:
    target = _next_candle_time()
    sleep_secs = (target - datetime.now(timezone.utc)).total_seconds()
    if sleep_secs > 0:
        logger.info(f"Sleeping {sleep_secs:.0f}s until next candle at {target.strftime('%H:%M:%S')} UTC")
        time.sleep(sleep_secs)


# ── Single iteration ──────────────────────────────────────────────────────────

def run_once(trader) -> None:  # Can be PaperTrader or RealTrader
    """Execute one full analysis + trade management cycle."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"── Cycle start {now_str} ──")

    # ── Step 1: Check open position ─────────────────────────────────────────
    if trader.has_position():
        try:
            current_price = get_current_price(SYMBOL)
            # Need EMA_fast for trailing stop — get from market state
            ms = get_current_market_state(max_cache_hours=0.5)
            ema_fast = ms["ema_fast"]

            closed = trader.check_exits(current_price, ema_fast)
            if closed:
                logger.info(f"Position closed: {closed['reason']} | PnL=${closed['pnl']:+,.2f}")
                save_trade({
                    **closed,
                    "rsi_at_entry": ms.get("rsi"),
                    "volume_above_avg": ms.get("volume_above_avg"),
                    "trend_4h": "BULLISH" if ms.get("trend_4h_bullish") else "BEARISH",
                })
                send_trade_closed(closed, trader.capital)
            else:
                send_position_update(trader.get_position(), current_price, trader.capital)
                logger.info(
                    f"Position still open @ ${current_price:,.2f} | "
                    f"Capital=${trader.capital:,.2f}"
                )
        except Exception as e:
            logger.error(f"Error checking position: {e}")
            send_error(f"Error checking position: {e}")
        return  # Don't look for new entry while in position

    # ── Step 2: No position — run full agent analysis ────────────────────────
    try:
        report = run_analysis(verbose=True)
        send_signal(report)
    except Exception as e:
        logger.error(f"Error running analysis: {e}")
        send_error(f"Analysis error: {e}")
        return

    # ── Step 3: Execute signal if entry allowed ──────────────────────────────
    if not report["entry_allowed"]:
        logger.info("No entry signal — waiting for next candle.")
        return

    decision = report["decision"]
    if decision not in ("LONG", "SHORT"):
        return

    ms = report["market_state"]
    entry_price = ms["price"]
    ema_mid = ms["ema_mid"]

    position = trader.open_position(decision, entry_price, ema_mid)
    if position:
        send_trade_opened(position, trader.capital)
        logger.info(
            f"Trade opened: {decision} @ ${entry_price:,.2f} | "
            f"SL=${position['stop_price']:,.2f} | TP1=${position['tp1_price']:,.2f}"
        )

    # ── Summary ──────────────────────────────────────────────────────────────
    summary = trader.get_summary()
    logger.info(
        f"Capital=${summary['capital']:,.2f} | "
        f"Return={summary['return_pct']:+.2f}% | "
        f"Trades={summary['total_trades']} | "
        f"Win rate={summary['win_rate']:.1f}%"
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def main(run_once_only: bool = False) -> None:
    logger.info("=" * 60)
    logger.info(f"AGENTE CRYPTO — ETH/USDT | Mode: {MODE.upper()}")
    if is_live_mode():
        logger.info(f"Live Trading: Testnet={is_testnet()}")
    logger.info("=" * 60)

    # Create appropriate trader based on mode
    if is_live_mode() and RealTrader:
        trader = RealTrader()
        mode_display = "LIVE (Testnet)" if is_testnet() else "LIVE (Real)"
    else:
        trader = PaperTrader()
        mode_display = "PAPER"

    summary = trader.get_summary()

    send_startup(mode_display, summary["capital"])
    logger.info(
        f"Starting capital: ${summary['capital']:,.2f} | "
        f"Trades so far: {summary['total_trades']}"
    )

    if run_once_only:
        run_once(trader)
        return

    logger.info("Entering hourly loop. Press Ctrl+C to stop.")
    while True:
        try:
            run_once(trader)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unhandled error in loop: {e}", exc_info=True)
            send_error(f"Unhandled bot error: {e}")

        _wait_until_next_candle()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETH/USDT Trading Bot")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()
    main(run_once_only=args.once)
