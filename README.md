# ETH/USDT Multi-Agent LLM Trading System

Automated trading system for ETH/USDT Binance Futures using Claude LLM agents.

## Project Structure

```
├── config.py              # Central configuration file
├── backtest.py            # Backtest engine (Stage 1)
├── agents/
│   ├── quant_agent.py     # Technical analysis agent (Stage 2)
│   ├── sentiment_agent.py  # Sentiment analysis agent (Stage 2)
│   ├── decisor_agent.py    # Decision consolidation agent (Stage 2)
│   └── reflect_agent.py    # Learning mechanism (Stage 2)
├── bot.py                 # Live trading bot (Stage 3)
├── backtest_results/      # Backtest outputs (CSV reports)
├── charts/                # Backtest charts (PNG images)
└── logs/                  # Application logs

```

## Installation

```bash
# 1. Clone or navigate to project directory
cd "C:\Aquiles\DEV\Agente Crypto"

# 2. Create virtual environment (optional but recommended)
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## Stage 1: Backtest

### Configuration
Edit `config.py` to adjust:
- `BACKTEST_YEARS` — How many years of historical data to test (default: 2)
- `STARTING_CAPITAL` — Initial capital for simulation (default: $10,000)
- Technical indicator periods (EMA 21/55/200, RSI 14, Volume period)
- Entry/exit conditions (RSI ranges, TP1 ratio, etc.)

### Running Backtest
```bash
python backtest.py
```

### Output
- **Console logs** — Real-time trade execution details
- **CSV report** — `backtest_results/backtest_ETHUSDT_[timestamp].csv`
  - Each row = one completed trade with entry/exit prices, P&L, duration
- **Chart** — `charts/backtest_ETHUSDT_[timestamp].png`
  - Price chart with entry/exit points and EMAs
  - Equity curve showing capital growth/drawdown

### Expected Metrics (from output)
- **Total Trades** — Number of completed trades
- **Win Rate** — % of profitable trades
- **Total Return** — % gain/loss on starting capital
- **Max Drawdown** — Largest peak-to-trough decline
- **Payoff Ratio** — Avg win / Avg loss ratio

---

## Stage 2: LLM Agents (Coming Next)

Once backtest is validated, will implement:

1. **Quant Agent** — Analyzes technical indicators + on-chain data
2. **Sentiment Agent** — Processes Reddit/Telegram/Fear & Greed Index
3. **Decisor Agent** — Consolidates signals → LONG/SHORT/NEUTRAL
4. **Reflect Agent** — Learns from past trades, improves prompts

Each agent uses Claude Haiku 4.5 via Anthropic API (with prompt caching).

---

## Stage 3: Live Trading Bot (Coming Later)

- Executes in paper trading mode by default
- Connects to Binance Futures API
- Runs at each 1H candle close
- Sends Telegram alerts for each trade

---

## Stage 4: Validation & Go Live (Final)

- 2-4 weeks of paper trading
- Daily performance reports
- Transition to live trading only after validation

---

## Configuration Notes

### API Keys (when needed for Stage 2+)
```bash
# Create .env file in project root:
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
ANTHROPIC_API_KEY=your_api_key_here
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### Risk Management
- **Max Risk per Trade:** 2% of capital (configurable)
- **Stop Loss:** EMA 55 ± 0.5% buffer
- **Take Profit 1:** 1.5x risk (close 60%)
- **Take Profit 2:** Trailing stop on EMA 21
- **Daily Drawdown Limit:** 5% → pause trading

---

## Trading Rules Summary

### LONG Entry
- ✓ Price > EMA 200 (4H)
- ✓ EMA 21 crosses above EMA 55 (1H)
- ✓ RSI 45-70 (1H)
- ✓ Volume > 20-period MA

### SHORT Entry
- ✓ Price < EMA 200 (4H)
- ✓ EMA 21 crosses below EMA 55 (1H)
- ✓ RSI 30-55 (1H)
- ✓ Volume > 20-period MA

### Exit Conditions
- Stop Loss: Breach EMA 55 ± 0.5%
- TP1: 1.5x risk (close 60%)
- TP2: Trailing stop at EMA 21

---

## Troubleshooting

**"No module named 'ccxt'"**
```bash
pip install ccxt --upgrade
```

**"Failed to fetch data"**
- Check internet connection
- Verify Binance API is accessible
- Try with fewer years of data first

**Chart not saving**
- Ensure `charts/` directory exists
- Check disk space
- Verify write permissions

---

## Next Steps
1. ✅ Run backtest with default parameters
2. ✅ Review backtest report and chart
3. ✅ Adjust strategy parameters if needed
4. → Build LLM agents (Stage 2)
5. → Deploy live bot (Stage 3)

---

## Support
For questions or issues, check the logs in console output.
Detailed trade logs are saved in `backtest_results/` directory.
