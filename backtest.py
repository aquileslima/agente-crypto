import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
import logging
from config import (
    SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND, BACKTEST_YEARS, STARTING_CAPITAL,
    LEVERAGE, EMA_FAST, EMA_MID, EMA_SLOW, RSI_PERIOD, VOLUME_PERIOD,
    LONG_RSI_MIN, LONG_RSI_MAX, SHORT_RSI_MIN, SHORT_RSI_MAX,
    RISK_PER_TRADE, STOP_LOSS_BUFFER, TP1_RATIO, TP1_SIZE,
    MIN_STOP_DISTANCE_PCT, USE_TRAILING_STOP,
    BACKTEST_OUTPUT_DIR, CHART_OUTPUT_DIR
)
from data_loader import fetch_ohlcv_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.makedirs(BACKTEST_OUTPUT_DIR, exist_ok=True)
os.makedirs(CHART_OUTPUT_DIR, exist_ok=True)


# ============================================================================
# DEFAULT PARAMETERS (loaded from config, can be overridden)
# ============================================================================
DEFAULT_PARAMS = {
    'ema_fast': EMA_FAST,
    'ema_mid': EMA_MID,
    'ema_slow': EMA_SLOW,
    'rsi_period': RSI_PERIOD,
    'volume_period': VOLUME_PERIOD,
    'long_rsi_min': LONG_RSI_MIN,
    'long_rsi_max': LONG_RSI_MAX,
    'short_rsi_min': SHORT_RSI_MIN,
    'short_rsi_max': SHORT_RSI_MAX,
    'risk_per_trade': RISK_PER_TRADE,
    'stop_loss_buffer': STOP_LOSS_BUFFER,
    'tp1_ratio': TP1_RATIO,
    'tp1_size': TP1_SIZE,
    'leverage': LEVERAGE,
    'min_stop_distance_pct': MIN_STOP_DISTANCE_PCT,
    'use_trailing_stop': USE_TRAILING_STOP,
}


# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def add_indicators(df, params):
    df = df.copy()
    df['ema_fast'] = calculate_ema(df['close'], params['ema_fast'])
    df['ema_mid'] = calculate_ema(df['close'], params['ema_mid'])
    df['ema_slow'] = calculate_ema(df['close'], params['ema_slow'])
    df['rsi'] = calculate_rsi(df['close'], params['rsi_period'])
    df['volume_ma'] = df['volume'].rolling(window=params['volume_period']).mean()
    df['volume_signal'] = df['volume'] > df['volume_ma']
    df['ema_fast_above_mid'] = df['ema_fast'] > df['ema_mid']
    df['ema_cross_up'] = df['ema_fast_above_mid'] & ~df['ema_fast_above_mid'].shift(1).fillna(False)
    df['ema_cross_down'] = ~df['ema_fast_above_mid'] & df['ema_fast_above_mid'].shift(1).fillna(True)
    return df


# ============================================================================
# BACKTEST ENGINE
# ============================================================================
class BacktestEngine:
    def __init__(self, df_1h, df_4h, params, initial_capital=STARTING_CAPITAL, verbose=True):
        self.df_1h = df_1h
        self.df_4h = df_4h
        self.params = params
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.trades = []
        self.equity_timestamps = []
        self.equity_values = []
        self.position = None
        self.verbose = verbose

    def _log(self, msg):
        if self.verbose:
            logger.info(msg)

    def run(self):
        """Vectorized run using NumPy arrays for speed."""
        df_1h = self.df_1h
        df_4h = self.df_4h
        p = self.params

        # Pre-compute 4h trend (price vs ema_slow) broadcast to each 1h candle
        idx_in_4h = df_4h.index.searchsorted(df_1h.index, side='right') - 1
        valid_4h = idx_in_4h >= 0
        # Use clipped index for indexing; we'll mask invalid entries below
        idx_in_4h_safe = np.clip(idx_in_4h, 0, len(df_4h) - 1)
        ema_slow_4h_arr = df_4h['ema_slow'].values
        close_4h_arr = df_4h['close'].values
        trend_long_4h = (close_4h_arr[idx_in_4h_safe] > ema_slow_4h_arr[idx_in_4h_safe]) & valid_4h
        trend_short_4h = (close_4h_arr[idx_in_4h_safe] < ema_slow_4h_arr[idx_in_4h_safe]) & valid_4h

        # Convert 1h columns to NumPy arrays (indexed access is much faster)
        timestamps = df_1h.index.values
        close_arr = df_1h['close'].values
        ema_fast_arr = df_1h['ema_fast'].values
        ema_mid_arr = df_1h['ema_mid'].values
        ema_slow_arr = df_1h['ema_slow'].values
        rsi_arr = df_1h['rsi'].values
        cross_up_arr = df_1h['ema_cross_up'].values
        cross_down_arr = df_1h['ema_cross_down'].values
        vol_signal_arr = df_1h['volume_signal'].values

        # Pre-compute entry signal masks (bool arrays)
        rsi_long_ok = (rsi_arr >= p['long_rsi_min']) & (rsi_arr <= p['long_rsi_max'])
        rsi_short_ok = (rsi_arr >= p['short_rsi_min']) & (rsi_arr <= p['short_rsi_max'])
        valid_indicators = ~np.isnan(ema_slow_arr)

        long_signals = trend_long_4h & cross_up_arr & rsi_long_ok & vol_signal_arr & valid_indicators
        short_signals = trend_short_4h & cross_down_arr & rsi_short_ok & vol_signal_arr & valid_indicators

        n = len(df_1h)
        for idx in range(1, n):
            if self.position is None:
                if long_signals[idx]:
                    self._open_position_fast(timestamps[idx], close_arr[idx], ema_mid_arr[idx], 'LONG')
                elif short_signals[idx]:
                    self._open_position_fast(timestamps[idx], close_arr[idx], ema_mid_arr[idx], 'SHORT')
            else:
                self._check_exit_fast(timestamps[idx], close_arr[idx], ema_fast_arr[idx])

        self.equity_timestamps = timestamps
        return self._generate_report()

    def _open_position_fast(self, timestamp, entry_price, ema_mid, direction):
        p = self.params
        buffer = p['stop_loss_buffer']

        if direction == 'LONG':
            stop_price = ema_mid * (1 - buffer)
            if stop_price >= entry_price:
                return
        else:
            stop_price = ema_mid * (1 + buffer)
            if stop_price <= entry_price:
                return

        price_risk = abs(entry_price - stop_price)
        if price_risk < entry_price * p['min_stop_distance_pct']:
            return

        risk_amount = self.capital * p['risk_per_trade']
        position_size = risk_amount / price_risk

        max_notional = self.capital * p['leverage']
        position_size = min(position_size, max_notional / entry_price)

        if position_size * entry_price / p['leverage'] > self.capital:
            position_size = (self.capital * p['leverage']) / entry_price

        tp1_price = (entry_price + price_risk * p['tp1_ratio']) if direction == 'LONG' \
                    else (entry_price - price_risk * p['tp1_ratio'])

        self.position = {
            'direction': direction,
            'entry_time': timestamp,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'size': position_size,
            'original_size': position_size,
            'tp1_price': tp1_price,
            'tp1_hit': False,
            'tp1_profit': 0.0,
        }

    def _check_exit_fast(self, timestamp, current_price, ema_fast):
        pos = self.position
        direction = pos['direction']

        # Stop loss
        if (direction == 'LONG' and current_price <= pos['stop_price']) or \
           (direction == 'SHORT' and current_price >= pos['stop_price']):
            self._close_position(timestamp, current_price, 'STOP LOSS')
            return

        # TP1 partial close
        if not pos['tp1_hit']:
            if (direction == 'LONG' and current_price >= pos['tp1_price']) or \
               (direction == 'SHORT' and current_price <= pos['tp1_price']):
                closed = pos['size'] * self.params['tp1_size']
                if direction == 'LONG':
                    profit = (pos['tp1_price'] - pos['entry_price']) * closed
                else:
                    profit = (pos['entry_price'] - pos['tp1_price']) * closed
                self.capital += profit
                pos['size'] -= closed
                pos['tp1_hit'] = True
                pos['tp1_profit'] = profit

        # Trailing stop on EMA fast
        if self.params['use_trailing_stop']:
            if direction == 'LONG' and current_price <= ema_fast:
                self._close_position(timestamp, current_price, 'TRAILING STOP')
            elif direction == 'SHORT' and current_price >= ema_fast:
                self._close_position(timestamp, current_price, 'TRAILING STOP')

    def _close_position(self, timestamp, close_price, reason):
        pos = self.position
        direction = pos['direction']
        entry_price = pos['entry_price']

        if direction == 'LONG':
            pnl = (close_price - entry_price) * pos['size']
        else:
            pnl = (entry_price - close_price) * pos['size']

        self.capital += pnl
        total_pnl = pnl + pos['tp1_profit']

        self.trades.append({
            'entry_time': pos['entry_time'],
            'exit_time': timestamp,
            'entry_price': entry_price,
            'exit_price': close_price,
            'direction': direction,
            'size': pos['original_size'],
            'pnl': total_pnl,
            'reason': reason,
            'duration_h': (timestamp - pos['entry_time']) / np.timedelta64(1, 'h')
        })
        self.position = None

    def _generate_report(self):
        trades_df = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()

        if len(trades_df) == 0:
            return {'total_trades': 0, 'total_return_pct': 0, 'win_rate': 0,
                    'max_drawdown': 0, 'final_capital': self.capital,
                    'trades_df': trades_df, 'equity_df': pd.DataFrame(),
                    'avg_win': 0, 'avg_loss': 0, 'payoff_ratio': 0,
                    'profit_factor': 0, 'sharpe': 0, 'total_pnl': 0,
                    'largest_win': 0, 'largest_loss': 0,
                    'winning_trades': 0, 'losing_trades': 0}

        # Build equity curve from cumulative trade PnL (one point per trade exit)
        equity_df = pd.DataFrame({
            'timestamp': trades_df['exit_time'].values,
            'capital': self.initial_capital + trades_df['pnl'].cumsum().values
        })

        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]
        total_wins = wins['pnl'].sum()
        total_losses = abs(losses['pnl'].sum())

        running_max = equity_df['capital'].cummax()
        drawdown = (equity_df['capital'] - running_max) / running_max * 100
        max_dd = drawdown.min()

        # Sharpe ratio (simple): mean return / std return
        returns = trades_df['pnl'] / self.initial_capital
        sharpe = (returns.mean() / returns.std() * np.sqrt(len(returns))) if returns.std() > 0 else 0

        return {
            'total_trades': len(trades_df),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(trades_df) * 100,
            'total_pnl': self.capital - self.initial_capital,
            'total_return_pct': (self.capital - self.initial_capital) / self.initial_capital * 100,
            'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
            'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
            'largest_win': trades_df['pnl'].max(),
            'largest_loss': trades_df['pnl'].min(),
            'payoff_ratio': (wins['pnl'].mean() / abs(losses['pnl'].mean())) if len(losses) > 0 and len(wins) > 0 else 0,
            'profit_factor': total_wins / total_losses if total_losses > 0 else 0,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'final_capital': self.capital,
            'trades_df': trades_df,
            'equity_df': equity_df
        }


# ============================================================================
# PUBLIC API
# ============================================================================
def run_backtest(df_1h_raw, df_4h_raw, params=None, verbose=True):
    """Run a single backtest with given parameters. df_*_raw are uncomputed OHLCV."""
    if params is None:
        params = DEFAULT_PARAMS.copy()
    df_1h = add_indicators(df_1h_raw, params)
    df_4h = add_indicators(df_4h_raw, params)
    engine = BacktestEngine(df_1h, df_4h, params, verbose=verbose)
    return engine.run()


def plot_backtest_results(df_1h, report, symbol=SYMBOL, suffix=""):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))

    ax1.plot(df_1h.index, df_1h['close'], label='Close', linewidth=1, color='black', alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_fast'], label=f"EMA fast", linewidth=1, alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_mid'], label=f"EMA mid", linewidth=1, alpha=0.7)
    ax1.plot(df_1h.index, df_1h['ema_slow'], label=f"EMA slow", linewidth=2, alpha=0.7)

    trades_df = report['trades_df']
    if len(trades_df) > 0:
        longs = trades_df[trades_df['direction'] == 'LONG']
        shorts = trades_df[trades_df['direction'] == 'SHORT']
        ax1.scatter(longs['entry_time'], longs['entry_price'], marker='^', color='green', s=80, label='Long Entry', zorder=5)
        ax1.scatter(longs['exit_time'], longs['exit_price'], marker='v', color='lightgreen', s=80, label='Long Exit', zorder=5)
        ax1.scatter(shorts['entry_time'], shorts['entry_price'], marker='v', color='red', s=80, label='Short Entry', zorder=5)
        ax1.scatter(shorts['exit_time'], shorts['exit_price'], marker='^', color='lightcoral', s=80, label='Short Exit', zorder=5)

    ax1.set_title(f'{symbol} Backtest {suffix}', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Price (USDT)')
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)

    equity_df = report['equity_df']
    ax2.plot(equity_df['timestamp'], equity_df['capital'], linewidth=2, color='blue', label='Equity')
    ax2.axhline(y=STARTING_CAPITAL, color='gray', linestyle='--', alpha=0.5)
    ax2.fill_between(equity_df['timestamp'], equity_df['capital'], STARTING_CAPITAL, alpha=0.2)
    ax2.set_title('Equity Curve')
    ax2.set_ylabel('Capital ($)')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    output = os.path.join(CHART_OUTPUT_DIR, f'backtest_{symbol.replace("/", "")}_{suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    plt.savefig(output, dpi=100, bbox_inches='tight')
    plt.close()
    return output


def print_report(report, params=None):
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    if params:
        print("Parameters:")
        for k, v in params.items():
            print(f"  {k:25s} = {v}")
        print("-" * 70)
    print(f"Total Trades:        {report['total_trades']}")
    print(f"Winning / Losing:    {report['winning_trades']} / {report['losing_trades']}")
    print(f"Win Rate:            {report['win_rate']:.2f}%")
    print(f"Total Return:        {report['total_return_pct']:.2f}%")
    print(f"Total P&L:           ${report['total_pnl']:.2f}")
    print(f"Avg Win / Avg Loss:  ${report['avg_win']:.2f} / ${report['avg_loss']:.2f}")
    print(f"Payoff Ratio:        {report['payoff_ratio']:.2f}")
    print(f"Profit Factor:       {report['profit_factor']:.2f}")
    print(f"Max Drawdown:        {report['max_drawdown']:.2f}%")
    print(f"Sharpe Ratio:        {report['sharpe']:.2f}")
    print(f"Final Capital:       ${report['final_capital']:.2f}")
    print("=" * 70 + "\n")


# ============================================================================
# MAIN
# ============================================================================
def main():
    logger.info("Loading data...")
    df_1h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_ENTRY, BACKTEST_YEARS)
    df_4h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_TREND, BACKTEST_YEARS)

    logger.info("Running backtest with default parameters...")
    report = run_backtest(df_1h, df_4h, verbose=False)
    print_report(report, DEFAULT_PARAMS)

    if len(report['trades_df']) > 0:
        report_file = os.path.join(BACKTEST_OUTPUT_DIR,
                                   f"backtest_{SYMBOL.replace('/', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        report['trades_df'].to_csv(report_file, index=False)
        logger.info(f"Trades saved to {report_file}")

        df_1h_with_ind = add_indicators(df_1h, DEFAULT_PARAMS)
        chart_file = plot_backtest_results(df_1h_with_ind, report, suffix="default")
        logger.info(f"Chart saved to {chart_file}")


if __name__ == "__main__":
    main()
