"""
Exchange — Binance Futures connector.
In paper mode (default): only price fetching is used; no real orders are placed.
In live mode: places market orders, sets leverage, manages positions.
"""
import os
import logging
import ccxt
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODE = os.getenv("TRADING_MODE", "paper").lower()
_LEVERAGE = int(os.getenv("LEVERAGE", "3"))


def _build_exchange(public_only: bool = False) -> ccxt.binance:
    kwargs = {
        "options": {"defaultType": "future"},
        "enableRateLimit": True,
    }
    if not public_only:
        kwargs["apiKey"] = os.getenv("BINANCE_API_KEY", "")
        kwargs["secret"] = os.getenv("BINANCE_API_SECRET", "")
    return ccxt.binance(kwargs)


def get_current_price(symbol: str = "ETH/USDT") -> float:
    """Fetch live last price from Binance Futures (no API key required)."""
    ex = _build_exchange(public_only=True)
    ticker = ex.fetch_ticker(symbol)
    return float(ticker["last"])


def get_account_balance(asset: str = "USDT") -> float:
    """Fetch available balance from Binance Futures account."""
    if _MODE == "paper":
        raise RuntimeError("Cannot fetch real balance in paper mode.")
    ex = _build_exchange()
    balance = ex.fetch_balance()
    return float(balance["free"].get(asset, 0))


def set_leverage(symbol: str, leverage: int) -> None:
    if _MODE == "paper":
        return
    ex = _build_exchange()
    ex.set_leverage(leverage, symbol)
    logger.info(f"Leverage set to {leverage}x for {symbol}")


def open_market_order(symbol: str, direction: str, size: float) -> dict | None:
    """
    Place a market order on Binance Futures.
    direction: 'LONG' or 'SHORT'
    size: quantity in base asset (ETH)

    Returns order dict or None in paper mode.
    """
    if _MODE == "paper":
        logger.info(f"[PAPER] Would open {direction} {size:.4f} {symbol}")
        return None

    ex = _build_exchange()
    side = "buy" if direction == "LONG" else "sell"
    order = ex.create_market_order(symbol, side, size)
    logger.info(f"Opened {direction} order: {order['id']} | size={size:.4f}")
    return order


def close_market_order(symbol: str, direction: str, size: float) -> dict | None:
    """
    Close (reduce) a position via market order.
    direction: current position direction ('LONG' closes with sell, 'SHORT' closes with buy)

    Returns order dict or None in paper mode.
    """
    if _MODE == "paper":
        logger.info(f"[PAPER] Would close {direction} {size:.4f} {symbol}")
        return None

    ex = _build_exchange()
    side = "sell" if direction == "LONG" else "buy"
    order = ex.create_market_order(symbol, side, size, params={"reduceOnly": True})
    logger.info(f"Closed {direction} order: {order['id']} | size={size:.4f}")
    return order


def get_open_positions(symbol: str = "ETH/USDT") -> list:
    """Fetch open futures positions from Binance."""
    if _MODE == "paper":
        return []
    ex = _build_exchange()
    positions = ex.fetch_positions([symbol])
    return [p for p in positions if float(p.get("contracts", 0)) != 0]
