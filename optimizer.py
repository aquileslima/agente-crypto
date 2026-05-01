import itertools
import time
import os
import logging
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from config import SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND, BACKTEST_YEARS, BACKTEST_OUTPUT_DIR
from data_loader import fetch_ohlcv_data
from backtest import run_backtest, DEFAULT_PARAMS, print_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# PARAMETER GRID
# ============================================================================
# Tuned to focus on highest-impact parameters. ~432 combinations.
PARAM_GRID = {
    'ema_fast':              [13, 21, 25],
    'ema_mid':               [50, 55, 65],
    'long_rsi_min':          [45, 50, 55],
    'long_rsi_max':          [65, 70, 75],
    'short_rsi_min':         [25, 30, 35],
    'short_rsi_max':         [50, 55, 60],
    'tp1_ratio':             [1.5, 2.0, 2.5, 3.0],
    'tp1_size':              [0.5, 0.6, 0.7],
    'min_stop_distance_pct': [0.005, 0.01, 0.015],
    'stop_loss_buffer':      [0.005, 0.01],
    'use_trailing_stop':     [True, False],
}

# Min trades required for a config to be valid (avoid lucky outliers with 5 trades)
MIN_TRADES = 30

# Optimization mode: 'grid' or 'random'
MODE = 'random'
RANDOM_SAMPLES = 1000


# ============================================================================
# WORKER (must be top-level for ProcessPoolExecutor)
# ============================================================================
_DF_1H = None
_DF_4H = None


def _init_worker(df_1h, df_4h):
    global _DF_1H, _DF_4H
    _DF_1H = df_1h
    _DF_4H = df_4h


def _evaluate(params):
    """Run one backtest and return summary metrics. Worker function."""
    try:
        report = run_backtest(_DF_1H, _DF_4H, params, verbose=False)
        return {
            **params,
            'total_trades': report['total_trades'],
            'win_rate': report['win_rate'],
            'total_return_pct': report['total_return_pct'],
            'max_drawdown': report['max_drawdown'],
            'payoff_ratio': report['payoff_ratio'],
            'profit_factor': report['profit_factor'],
            'sharpe': report['sharpe'],
            'final_capital': report['final_capital'],
        }
    except Exception as e:
        return {**params, 'error': str(e), 'total_return_pct': -999}


# ============================================================================
# GRID GENERATION
# ============================================================================
def generate_grid_combinations(grid):
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))


def generate_random_combinations(grid, n):
    import random
    random.seed(42)
    keys = list(grid.keys())
    seen = set()
    while len(seen) < n:
        combo = tuple(random.choice(grid[k]) for k in keys)
        if combo in seen:
            continue
        seen.add(combo)
        yield dict(zip(keys, combo))


def filter_invalid_combos(combos):
    """Remove combos where rsi_min >= rsi_max."""
    for c in combos:
        if c['long_rsi_min'] >= c['long_rsi_max']:
            continue
        if c['short_rsi_min'] >= c['short_rsi_max']:
            continue
        if c['ema_fast'] >= c['ema_mid']:
            continue
        yield c


def build_full_params(partial):
    """Merge partial params with defaults."""
    p = DEFAULT_PARAMS.copy()
    p.update(partial)
    return p


# ============================================================================
# MAIN OPTIMIZATION
# ============================================================================
def main():
    logger.info("=" * 70)
    logger.info("OPTIMIZATION START")
    logger.info("=" * 70)

    logger.info("Loading data...")
    df_1h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_ENTRY, BACKTEST_YEARS)
    df_4h = fetch_ohlcv_data(SYMBOL, TIMEFRAME_TREND, BACKTEST_YEARS)

    if MODE == 'random':
        combos = list(filter_invalid_combos(generate_random_combinations(PARAM_GRID, RANDOM_SAMPLES)))
    else:
        combos = list(filter_invalid_combos(generate_grid_combinations(PARAM_GRID)))

    full_combos = [build_full_params(c) for c in combos]
    logger.info(f"Evaluating {len(full_combos)} parameter combinations...")

    results = []
    start = time.time()
    n_workers = max(1, (os.cpu_count() or 2) - 1)
    logger.info(f"Using {n_workers} parallel workers")

    with ProcessPoolExecutor(max_workers=n_workers, initializer=_init_worker, initargs=(df_1h, df_4h)) as executor:
        futures = {executor.submit(_evaluate, p): p for p in full_combos}
        for i, future in enumerate(as_completed(futures), 1):
            res = future.result()
            results.append(res)
            if i % 25 == 0 or i == len(full_combos):
                elapsed = time.time() - start
                eta = elapsed / i * (len(full_combos) - i)
                logger.info(f"  {i}/{len(full_combos)} done | elapsed {elapsed:.0f}s | ETA {eta:.0f}s")

    elapsed = time.time() - start
    logger.info(f"All evaluations done in {elapsed:.1f}s")

    # ========================================================================
    # ANALYZE RESULTS
    # ========================================================================
    df = pd.DataFrame(results)
    df = df[df['total_trades'] >= MIN_TRADES].copy()

    if len(df) == 0:
        logger.warning(f"No configs produced >= {MIN_TRADES} trades. Lowering bar.")
        df = pd.DataFrame(results)

    # Sort by return, then by drawdown (less negative = better)
    df = df.sort_values('total_return_pct', ascending=False).reset_index(drop=True)

    # Save full results
    os.makedirs(BACKTEST_OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(BACKTEST_OUTPUT_DIR, f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"Full results saved to {csv_path}")

    # ========================================================================
    # PRINT TOP 10
    # ========================================================================
    print("\n" + "=" * 110)
    print("TOP 10 PARAMETER COMBINATIONS BY TOTAL RETURN")
    print("=" * 110)

    display_cols = [
        'total_return_pct', 'win_rate', 'max_drawdown', 'payoff_ratio',
        'profit_factor', 'sharpe', 'total_trades',
        'ema_fast', 'ema_mid', 'long_rsi_min', 'long_rsi_max',
        'short_rsi_min', 'short_rsi_max', 'tp1_ratio', 'tp1_size',
        'min_stop_distance_pct', 'stop_loss_buffer', 'use_trailing_stop'
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    print(df[display_cols].head(10).to_string())

    # ========================================================================
    # BEST CONFIG DETAIL
    # ========================================================================
    if len(df) > 0:
        best = df.iloc[0].to_dict()
        print("\n" + "=" * 70)
        print("BEST CONFIGURATION")
        print("=" * 70)
        print(f"Total Return:        {best['total_return_pct']:.2f}%")
        print(f"Win Rate:            {best['win_rate']:.2f}%")
        print(f"Max Drawdown:        {best['max_drawdown']:.2f}%")
        print(f"Payoff Ratio:        {best['payoff_ratio']:.2f}")
        print(f"Profit Factor:       {best['profit_factor']:.2f}")
        print(f"Sharpe Ratio:        {best['sharpe']:.2f}")
        print(f"Total Trades:        {int(best['total_trades'])}")
        print(f"Final Capital:       ${best['final_capital']:.2f}")
        print("\nParameters:")
        for k in PARAM_GRID.keys():
            print(f"  {k:25s} = {best[k]}")
        print("=" * 70 + "\n")

        # Run final backtest with best params and save chart
        best_params = build_full_params({k: best[k] for k in PARAM_GRID.keys()})
        # Cast types since CSV may have converted them
        for k in ['ema_fast', 'ema_mid', 'long_rsi_min', 'long_rsi_max',
                  'short_rsi_min', 'short_rsi_max']:
            best_params[k] = int(best_params[k])
        for k in ['tp1_ratio', 'tp1_size', 'min_stop_distance_pct', 'stop_loss_buffer']:
            best_params[k] = float(best_params[k])
        best_params['use_trailing_stop'] = bool(best_params['use_trailing_stop'])

        logger.info("Running final backtest with best params for chart generation...")
        from backtest import plot_backtest_results, add_indicators
        report = run_backtest(df_1h, df_4h, best_params, verbose=False)
        df_1h_ind = add_indicators(df_1h, best_params)
        chart = plot_backtest_results(df_1h_ind, report, suffix="optimized")
        logger.info(f"Chart saved to {chart}")

        # Save best config to file
        best_config_path = os.path.join(BACKTEST_OUTPUT_DIR, "best_params.txt")
        with open(best_config_path, 'w') as f:
            f.write("# Best optimized parameters\n")
            for k, v in best_params.items():
                f.write(f"{k} = {v}\n")
            f.write(f"\n# Performance:\n")
            f.write(f"# Return: {best['total_return_pct']:.2f}%\n")
            f.write(f"# Win Rate: {best['win_rate']:.2f}%\n")
            f.write(f"# Max DD: {best['max_drawdown']:.2f}%\n")
            f.write(f"# Sharpe: {best['sharpe']:.2f}\n")
        logger.info(f"Best params saved to {best_config_path}")


if __name__ == "__main__":
    main()
