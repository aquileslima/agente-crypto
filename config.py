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
# TECHNICAL INDICATORS
# ============================================================================
EMA_FAST = 21
EMA_MID = 55
EMA_SLOW = 200
RSI_PERIOD = 14
VOLUME_PERIOD = 20

# ============================================================================
# ENTRY CONDITIONS
# ============================================================================
# LONG
LONG_RSI_MIN = 45
LONG_RSI_MAX = 70

# SHORT
SHORT_RSI_MIN = 30
SHORT_RSI_MAX = 55

# ============================================================================
# RISK MANAGEMENT
# ============================================================================
RISK_PER_TRADE = 0.02  # 2% of capital per trade
STOP_LOSS_BUFFER = 0.005  # 0.5% buffer after EMA 55
TP1_RATIO = 1.5  # Risk-to-reward for TP1
TP1_SIZE = 0.60  # Close 60% at TP1
MAX_DAILY_DRAWDOWN = 0.05  # 5% max daily drawdown

# ============================================================================
# BACKTEST PARAMETERS
# ============================================================================
BACKTEST_YEARS = 2
STARTING_CAPITAL = 10000  # $10,000 for simulation
MODE = "paper"  # paper or live

# ============================================================================
# LOGGING & OUTPUT
# ============================================================================
LOG_LEVEL = "INFO"
BACKTEST_OUTPUT_DIR = "backtest_results"
CHART_OUTPUT_DIR = "charts"
