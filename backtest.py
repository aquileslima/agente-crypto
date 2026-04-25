import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import logging
from config import *

# ============================================================================
# SETUP LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create output directories
os.makedirs(BACKTEST_OUTPUT_DIR, exist_ok=True)
os.makedirs(CHART_OUTPUT_DIR, exist_ok=True)

# ============================================================================
# DATA FETCHING
# ============================================================================
def fetch_ohlcv_data(symbol, timeframe, years=2):
    """Fetch historical OHLCV data from Binance"""
    logger.info(f"Fetching {symbol} {timeframe} data for {years} years...")

    exchange = ccxt.binance()
    all_data = []

    # Calculate start date
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=365 * years)

    since = int(start_date.timestamp() * 1000)

    try:
        while since < int(end_date.timestamp() * 1000):
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not ohlcv:
                break

            all_data.extend(ohlcv)
            since = ohlcv[-1][0] + 1  # Move to next batch
            logger.info(f"  Fetched {len(all_data)} candles...")

    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None

    # Convert to DataFrame
    df = pd.DataFrame(
        all_data,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    logger.info(f"✓ Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    return df

# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================
def calculate_ema(series, period):
    """Calculate Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    """Calculate Relative Strength Index"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_volume_ma(volume, period=20):
    """Calculate Volume Moving Average"""
    return volume.rolling(window=period).mean()

def add_indicators(df):
    """Add all technical indicators to dataframe"""
    logger.info("Calculating technical indicators...")

    # EMAs
    df['ema_21'] = calculate_ema(df['close'], EMA_FAST)
    df['ema_55'] = calculate_ema(df['close'], EMA_MID)
    df['ema_200'] = calculate_ema(df['close'], EMA_SLOW)

    # RSI
    df['rsi'] = calculate_rsi(df['close'], RSI_PERIOD)

    # Volume
    df['volume_ma'] = calculate_volume_ma(df['volume'], VOLUME_PERIOD)
    df['volume_signal'] = df['volume'] > df['volume_ma']

    # EMA Crossovers
    df['ema_21_above_55'] = df['ema_21'] > df['ema_55']
    df['ema_cross_up'] = df['ema_21_above_55'] & ~df['ema_21_above_55'].shift(1)
    df['ema_cross_down'] = ~df['ema_21_above_55'] & df['ema_21_above_55'].shift(1)

    logger.info("✓ Indicators calculated")
    return df

# ============================================================================
# ENTRY SIGNALS
# ============================================================================
def check_long_entry(row_1h, row_4h):
    """Check if LONG entry conditions are met"""
    conditions = {
        'price_above_ema200': row_4h['close'] > row_4h['ema_200'],
        'ema_crossover': row_1h['ema_cross_up'],
        'rsi_valid': LONG_RSI_MIN <= row_1h['rsi'] <= LONG_RSI_MAX,
        'volume_signal': row_1h['volume_signal']
    }
    return all(conditions.values()), conditions

def check_short_entry(row_1h, row_4h):
    """Check if SHORT entry conditions are met"""
    conditions = {
        'price_below_ema200': row_4h['close'] < row_4h['ema_200'],
        'ema_crossover': row_1h['ema_cross_down'],
        'rsi_valid': SHORT_RSI_MIN <= row_1h['rsi'] <= SHORT_RSI_MAX,
        'volume_signal': row_1h['volume_signal']
    }
    return all(conditions.values()), conditions

# ============================================================================
# BACKTEST ENGINE
# ============================================================================
class BacktestEngine:
    def __init__(self, df_1h, df_4h, initial_capital=STARTING_CAPITAL):
        self.df_1h = df_1h.copy()
        self.df_4h = df_4h.copy()
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.trades = []
        self.equity_curve = []
        self.position = None  # None, 'LONG', or 'SHORT'

    def get_4h_row(self, timestamp_1h):
        """Get the 4h row corresponding to 1h timestamp"""
        # Find the closest 4h candle that is <= 1h candle timestamp
        mask = self.df_4h.index <= timestamp_1h
        if mask.any():
            return self.df_4h.loc[mask].iloc[-1]
        return None

    def run(self):
        """Run the backtest"""
        logger.info("Starting backtest simulation...")

        for idx in range(1, len(self.df_1h)):
            timestamp = self.df_1h.index[idx]
            row_1h = self.df_1h.iloc[idx]
            row_4h = self.get_4h_row(timestamp)

            if row_4h is None or pd.isna(row_1h['ema_200']):
                continue

            # Check entry signals (only if no position)
            if self.position is None:
                long_signal, long_conds = check_long_entry(row_1h, row_4h)
                short_signal, short_conds = check_short_entry(row_1h, row_4h)

                if long_signal:
                    self._open_position(timestamp, row_1h, 'LONG')
                elif short_signal:
                    self._open_position(timestamp, row_1h, 'SHORT')

            # Check exit signals (if in position)
            elif self.position:
                self._check_exit(timestamp, row_1h)

            # Record equity
            self.equity_curve.append({
                'timestamp': timestamp,
                'capital': self.capital,
                'position': self.position
            })

        logger.info("✓ Backtest simulation complete")
        return self._generate_report()

    def _open_position(self, timestamp, row, direction):
        """Open a new position"""
        entry_price = row['close']

        # Calculate position sizing
        if direction == 'LONG':
            stop_price = row['ema_55'] - (row['ema_55'] * STOP_LOSS_BUFFER)
        else:  # SHORT
            stop_price = row['ema_55'] + (row['ema_55'] * STOP_LOSS_BUFFER)

        risk = abs(entry_price - stop_price)
        position_size = (self.capital * RISK_PER_TRADE) / risk

        self.position = {
            'direction': direction,
            'entry_time': timestamp,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'size': position_size,
            'tp1_price': entry_price + (risk * TP1_RATIO) if direction == 'LONG'
                        else entry_price - (risk * TP1_RATIO),
            'tp1_hit': False,
            'highest_price': entry_price if direction == 'LONG' else entry_price,
            'lowest_price': entry_price if direction == 'LONG' else entry_price
        }

        logger.info(f"[{timestamp}] {direction} ENTRY @ ${entry_price:.2f} | "
                   f"SL: ${stop_price:.2f} | TP1: ${self.position['tp1_price']:.2f}")

    def _check_exit(self, timestamp, row):
        """Check exit conditions"""
        current_price = row['close']
        direction = self.position['direction']

        # Track highs/lows for trailing stop
        if direction == 'LONG':
            self.position['highest_price'] = max(self.position['highest_price'], current_price)
        else:
            self.position['lowest_price'] = min(self.position['lowest_price'], current_price)

        # Check stop loss
        if direction == 'LONG' and current_price <= self.position['stop_price']:
            self._close_position(timestamp, current_price, 'STOP LOSS')
            return
        elif direction == 'SHORT' and current_price >= self.position['stop_price']:
            self._close_position(timestamp, current_price, 'STOP LOSS')
            return

        # Check TP1 (close 60% of position)
        if direction == 'LONG' and current_price >= self.position['tp1_price'] and not self.position['tp1_hit']:
            partial_profit = (self.position['tp1_price'] - self.position['entry_price']) * self.position['size'] * TP1_SIZE
            self.capital += partial_profit
            self.position['tp1_hit'] = True
            logger.info(f"[{timestamp}] TP1 HIT @ ${current_price:.2f} | "
                       f"Closed 60% | Profit: ${partial_profit:.2f}")
        elif direction == 'SHORT' and current_price <= self.position['tp1_price'] and not self.position['tp1_hit']:
            partial_profit = (self.position['entry_price'] - self.position['tp1_price']) * self.position['size'] * TP1_SIZE
            self.capital += partial_profit
            self.position['tp1_hit'] = True
            logger.info(f"[{timestamp}] TP1 HIT @ ${current_price:.2f} | "
                       f"Closed 60% | Profit: ${partial_profit:.2f}")

        # Check trailing stop (EMA 21)
        ema_21 = row['ema_21']
        if direction == 'LONG' and current_price <= ema_21:
            self._close_position(timestamp, current_price, 'TRAILING STOP')
        elif direction == 'SHORT' and current_price >= ema_21:
            self._close_position(timestamp, current_price, 'TRAILING STOP')

    def _close_position(self, timestamp, close_price, reason):
        """Close current position"""
        direction = self.position['direction']
        entry_price = self.position['entry_price']

        if direction == 'LONG':
            pnl = (close_price - entry_price) * self.position['size']
        else:
            pnl = (entry_price - close_price) * self.position['size']

        self.capital += pnl

        self.trades.append({
            'entry_time': self.position['entry_time'],
            'entry_price': entry_price,
            'exit_time': timestamp,
            'exit_price': close_price,
            'direction': direction,
            'size': self.position['size'],
            'pnl': pnl,
            'pnl_pct': (pnl / (entry_price * self.position['size'])) * 100 if direction == 'LONG'
                      else (pnl / (entry_price * self.position['size'])) * 100,
            'reason': reason,
            'duration_hours': (timestamp - self.position['entry_time']).total_seconds() / 3600
        })

        logger.info(f"[{timestamp}] {direction} EXIT @ ${close_price:.2f} | "
                   f"Reason: {reason} | P&L: ${pnl:.2f} ({self.trades[-1]['pnl_pct']:.2f}%)")

        self.position = None

    def _generate_report(self):
        """Generate backtest report"""
        trades_df = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
        equity_df = pd.DataFrame(self.equity_curve)

        report = {
            'total_trades': len(self.trades),
            'winning_trades': len(trades_df[trades_df['pnl'] > 0]) if len(trades_df) > 0 else 0,
            'losing_trades': len(trades_df[trades_df['pnl'] <= 0]) if len(trades_df) > 0 else 0,
            'win_rate': (len(trades_df[trades_df['pnl'] > 0]) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
            'total_pnl': self.capital - self.initial_capital,
            'total_return_pct': ((self.capital - self.initial_capital) / self.initial_capital) * 100,
            'avg_trade_pnl': trades_df['pnl'].mean() if len(trades_df) > 0 else 0,
            'largest_win': trades_df['pnl'].max() if len(trades_df) > 0 else 0,
            'largest_loss': trades_df['pnl'].min() if len(trades_df) > 0 else 0,
            'final_capital': self.capital,
            'trades_df': trades_df,
            'equity_df': equity_df
        }

        # Calculate max drawdown
        if len(equity_df) > 0:
            cumulative_returns = (equity_df['capital'] / self.initial_capital - 1) * 100
            running_max = equity_df['capital'].cummax()
            drawdown = (equity_df['capital'] - running_max) / running_max * 100
            report['max_drawdown'] = drawdown.min()
        else:
            report['max_drawdown'] = 0

        return report

# ============================================================================
# VISUALIZATION
# ============================================================================
def plot_backtest_results(df_1h, report, symbol=SYMBOL):
    """Plot backtest results with entry/exit points"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))

    # Price chart with indicators
    ax1.plot(df_1h.index, df_1h['close'], label='Close', linewidth=1, color='black', alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_21'], label='EMA 21', linewidth=1, alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_55'], label='EMA 55', linewidth=1, alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_200'], label='EMA 200', linewidth=2, alpha=0.7)

    # Plot trades
    trades_df = report['trades_df']
    if len(trades_df) > 0:
        # Long entries
        long_trades = trades_df[trades_df['direction'] == 'LONG']
        ax1.scatter(long_trades['entry_time'], long_trades['entry_price'],
                   marker='^', color='green', s=100, label='Long Entry', zorder=5)
        ax1.scatter(long_trades['exit_time'], long_trades['exit_price'],
                   marker='v', color='lightgreen', s=100, label='Long Exit', zorder=5)

        # Short entries
        short_trades = trades_df[trades_df['direction'] == 'SHORT']
        ax1.scatter(short_trades['entry_time'], short_trades['entry_price'],
                   marker='v', color='red', s=100, label='Short Entry', zorder=5)
        ax1.scatter(short_trades['exit_time'], short_trades['exit_price'],
                   marker='^', color='lightcoral', s=100, label='Short Exit', zorder=5)

    ax1.set_title(f'{symbol} 1H Backtest - Entry/Exit Points', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Price (USDT)', fontsize=11)
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Equity curve
    equity_df = report['equity_df']
    ax2.plot(equity_df['timestamp'], equity_df['capital'], linewidth=2, color='blue', label='Account Equity')
    ax2.axhline(y=10000, color='gray', linestyle='--', alpha=0.5, label='Starting Capital')
    ax2.fill_between(equity_df['timestamp'], equity_df['capital'], 10000, alpha=0.2)

    ax2.set_title('Account Equity Curve', fontsize=14, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=11)
    ax2.set_ylabel('Capital ($)', fontsize=11)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    output_file = os.path.join(CHART_OUTPUT_DIR, f'backtest_{symbol.replace("/", "")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    plt.savefig(output_file, dpi=100, bbox_inches='tight')
    logger.info(f"✓ Chart saved to {output_file}")
    plt.close()

# ============================================================================
# MAIN
# ============================================================================
def main():
    logger.info("=" * 70)
    logger.info("ETH/USDT BACKTEST ENGINE - START")
    logger.info("=" * 70)

    # Fetch data
    df_1h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_ENTRY, years=BACKTEST_YEARS)
    df_4h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_TREND, years=BACKTEST_YEARS)

    if df_1h is None or df_4h is None:
        logger.error("Failed to fetch data. Exiting.")
        return

    # Add indicators
    df_1h = add_indicators(df_1h)
    df_4h = add_indicators(df_4h)

    # Run backtest
    engine = BacktestEngine(df_1h, df_4h)
    report = engine.run()

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("BACKTEST RESULTS SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total Trades:        {report['total_trades']}")
    logger.info(f"Winning Trades:      {report['winning_trades']}")
    logger.info(f"Losing Trades:       {report['losing_trades']}")
    logger.info(f"Win Rate:            {report['win_rate']:.2f}%")
    logger.info(f"Total Return:        {report['total_return_pct']:.2f}%")
    logger.info(f"Total P&L:           ${report['total_pnl']:.2f}")
    logger.info(f"Avg Trade P&L:       ${report['avg_trade_pnl']:.2f}")
    logger.info(f"Largest Win:         ${report['largest_win']:.2f}")
    logger.info(f"Largest Loss:        ${report['largest_loss']:.2f}")
    logger.info(f"Max Drawdown:        {report['max_drawdown']:.2f}%")
    logger.info(f"Final Capital:       ${report['final_capital']:.2f}")
    logger.info("=" * 70 + "\n")

    # Save detailed report
    if len(report['trades_df']) > 0:
        report_file = os.path.join(BACKTEST_OUTPUT_DIR,
                                   f"backtest_{SYMBOL.replace('/', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        report['trades_df'].to_csv(report_file, index=False)
        logger.info(f"✓ Detailed trades saved to {report_file}")

    # Plot results
    plot_backtest_results(df_1h, report)

    logger.info("=" * 70)
    logger.info("ETH/USDT BACKTEST ENGINE - COMPLETE")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()
