"""
Exchange — Binance Futures connector.
In paper mode (default): only price fetching is used; no real orders are placed.
In live mode (testnet or real): places market orders, sets leverage, manages positions.
"""
import os
import logging
import ccxt
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_MODE = os.getenv("TRADING_MODE", "paper").lower()
_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
_LEVERAGE = int(os.getenv("LEVERAGE", "3"))


def _build_exchange(public_only: bool = False) -> ccxt.binance:
    kwargs = {
        "options": {"defaultType": "future"},
        "enableRateLimit": True,
    }

    if not public_only:
        kwargs["apiKey"] = os.getenv("BINANCE_API_KEY", "")
        kwargs["secret"] = os.getenv("BINANCE_API_SECRET", "")

    exchange = ccxt.binance(kwargs)

    # Override URLs AFTER instantiation — passing via kwargs doesn't
    # reliably override all internal URL keys in CCXT.
    # The base must be just the host (CCXT appends /fapi/v1/... itself).
    if _TESTNET:
        base = "https://testnet.binancefuture.com"
        exchange.urls["api"]["fapiPublic"]   = base
        exchange.urls["api"]["fapiPublicV2"] = base
        exchange.urls["api"]["fapiPublicV3"] = base
        exchange.urls["api"]["fapiPublicV4"] = base
        exchange.urls["api"]["fapiPrivate"]  = base
        exchange.urls["api"]["fapiPrivateV2"] = base
        logger.info("Using Binance Futures Testnet: %s", base)

    return exchange


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


def get_websocket_url(symbol: str = "ETH/USDT") -> str:
    """Get WebSocket stream URL for real-time price updates."""
    ws_symbol = symbol.replace("/", "").lower()
    if _TESTNET:
        return f"wss://stream.testnet.binancefuture.com/ws/{ws_symbol}@bookTicker"
    else:
        return f"wss://fstream.binance.com/ws/{ws_symbol}@bookTicker"


def is_live_mode() -> bool:
    """Check if running in live mode (testnet or real)."""
    return _MODE in ("live", "testnet") or _TESTNET


def is_testnet() -> bool:
    """Check if running in testnet mode."""
    return _TESTNET
