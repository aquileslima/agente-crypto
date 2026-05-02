"""
Market State — computes current indicator snapshot from live OHLCV data.
Uses the same add_indicators() function as the backtest engine for consistency.
"""
import logging
import numpy as np
from data_loader import fetch_ohlcv_data
from backtest import add_indicators, DEFAULT_PARAMS
from config import SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND

logger = logging.getLogger(__name__)

# Fetch only last 0.5 years — enough for EMA200 warmup without full 2-year pull
_FETCH_YEARS = 0.5


def get_current_market_state(
    symbol: str = SYMBOL,
    timeframe_1h: str = TIMEFRAME_ENTRY,
    timeframe_4h: str = TIMEFRAME_TREND,
    params: dict = None,
    max_cache_hours: float = 0.1,  # Padrão: 6 min — garante dados frescos no bot horário
) -> dict:
    """
    Fetch the latest OHLCV data and compute current indicator values.

    Args:
        max_cache_hours: max age of cached data before re-fetching.
                         Default 0.1 (6 min) to always get fresh data on hourly bot runs.

    Returns a dict compatible with quant_agent.analyze() and orchestrator.
    """
    if params is None:
        params = DEFAULT_PARAMS

    logger.info(f"Fetching current market state for {symbol}...")
    df_1h = fetch_ohlcv_data(symbol, timeframe_1h, years=_FETCH_YEARS, max_cache_hours=max_cache_hours)
    df_4h = fetch_ohlcv_data(symbol, timeframe_4h, years=_FETCH_YEARS, max_cache_hours=max_cache_hours)

    df_1h = add_indicators(df_1h, params)
    df_4h = add_indicators(df_4h, params)

    latest = df_1h.iloc[-1]
    prev = df_1h.iloc[-2]
    latest_4h = df_4h.iloc[-1]

    price = float(latest["close"])
    ema_fast = float(latest["ema_fast"])
    ema_mid = float(latest["ema_mid"])
    ema_slow = float(latest["ema_slow"])
    rsi = float(latest["rsi"])
    volume = float(latest["volume"])
    volume_ma = float(latest["volume_ma"]) if not np.isnan(latest["volume_ma"]) else volume

    return {
        "timestamp": str(df_1h.index[-1]),
        "symbol": symbol,
        # Price & EMAs
        "price": price,
        "ema_fast": ema_fast,
        "ema_mid": ema_mid,
        "ema_slow": ema_slow,
        # RSI
        "rsi": rsi,
        # Volume
        "volume": volume,
        "volume_ma": volume_ma,
        "volume_above_avg": bool(latest["volume_signal"]),
        # Crossover signals on current candle
        "ema_cross_up": bool(latest["ema_cross_up"]),
        "ema_cross_down": bool(latest["ema_cross_down"]),
        "ema_fast_above_mid": bool(latest["ema_fast_above_mid"]),
        # 4H trend
        "trend_4h_bullish": bool(latest_4h["close"] > latest_4h["ema_slow"]),
        "ema_slow_4h": float(latest_4h["ema_slow"]),
        # Recent candles for context (last 10)
        "recent_closes": df_1h["close"].tail(10).tolist(),
        "recent_highs": df_1h["high"].tail(10).tolist(),
        "recent_lows": df_1h["low"].tail(10).tolist(),
    }
