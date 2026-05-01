# Configuration file for ETH/USDT Trading System

# ============================================================================
# TRADING PARAMETERS
# ============================================================================
SYMBOL = "ETH/USDT"
EXCHANGE = "binance"
LEVERAGE = 3
TIMEFRAME_ENTRY = "1h"  # Entry signal timeframe
TIMEFRAME_TREND = "4h"  # Trend confirmation timeframe

# ============================================================================
# TECHNICAL INDICATORS (OPTIMIZED via grid search 2026-04-25)
# Backtest result: +171% return, -13% max DD, Sharpe 2.43, win rate 36%
# ============================================================================
EMA_FAST = 21
EMA_MID = 50    # was 55 — faster trend detection
EMA_SLOW = 200
RSI_PERIOD = 14
VOLUME_PERIOD = 20

# ============================================================================
# ENTRY CONDITIONS
# ============================================================================
# LONG: wider RSI range allows more valid entries
LONG_RSI_MIN = 45
LONG_RSI_MAX = 75   # was 70 — accept entries in moderate overbought

# SHORT: wider RSI range
SHORT_RSI_MIN = 25  # was 30 — accept entries in oversold
SHORT_RSI_MAX = 55

# ============================================================================
# RISK MANAGEMENT (OPTIMIZED)
# ============================================================================
RISK_PER_TRADE = 0.02         # 2% of capital per trade
STOP_LOSS_BUFFER = 0.01       # was 0.005 — more room for EMA noise
TP1_RATIO = 2.5               # was 1.5 — let winners run further
TP1_SIZE = 0.50               # was 0.60 — leave more on the table for TP2
MIN_STOP_DISTANCE_PCT = 0.005 # min stop distance from entry (sanity guard)
USE_TRAILING_STOP = True      # trail stop on EMA fast
MAX_DAILY_DRAWDOWN = 0.05     # 5% max daily drawdown

# ============================================================================
# BACKTEST PARAMETERS
# ============================================================================
BACKTEST_YEARS = 2
STARTING_CAPITAL = 500    # $500 initial capital
MODE = "paper"  # paper or live

# ============================================================================
# LOGGING & OUTPUT
# ============================================================================
LOG_LEVEL = "INFO"
BACKTEST_OUTPUT_DIR = "backtest_results"
CHART_OUTPUT_DIR = "charts"
