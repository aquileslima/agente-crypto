import ccxt
import pandas as pd
import os
import pickle
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(symbol, timeframe, years):
    safe_symbol = symbol.replace("/", "")
    return os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}_{years}y.pkl")


def fetch_ohlcv_data(symbol, timeframe, years=2, use_cache=True, max_cache_hours=24):
    """Fetch OHLCV from Binance with local pickle cache."""
    cache_file = _cache_path(symbol, timeframe, years)

    if use_cache and os.path.exists(cache_file):
        cache_age_hours = (datetime.now().timestamp() - os.path.getmtime(cache_file)) / 3600
        if cache_age_hours < max_cache_hours:
            logger.info(f"Loading {symbol} {timeframe} from cache ({cache_age_hours:.1f}h old)")
            return pd.read_pickle(cache_file)

    logger.info(f"Fetching {symbol} {timeframe} for {years} years from Binance...")
    exchange = ccxt.binance()
    all_data = []

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365 * years)
    since = int(start_date.timestamp() * 1000)

    while since < int(end_date.timestamp() * 1000):
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not ohlcv:
            break
        all_data.extend(ohlcv)
        since = ohlcv[-1][0] + 1

    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    df.to_pickle(cache_file)
    logger.info(f"Cached {len(df)} candles to {cache_file}")
    return df
