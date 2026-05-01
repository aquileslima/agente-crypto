# WebSocket Implementation Guide

## Overview

Two new modules implement real-time price monitoring without CCXT:

- **`websocket_monitor.py`** — High-level position monitoring with exit detection (SL/TP/trailing stop)
- **`websocket_direct.py`** — Low-level Binance REST + WebSocket clients (pure requests + websockets)

## Architecture

```
┌─────────────────────────────────┐
│  WebSocketMonitor               │
│  - Position tracking            │
│  - Exit detection (SL/TP)       │
│  - Auto-reconnection            │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  BinanceWebSocketClient         │
│  - Real-time price streaming    │
│  - Callback-based updates       │
│  - Multiple stream types        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Binance WebSocket (Public)     │
│  wss://fstream.binance.com/ws/  │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│  BinanceRESTClient              │
│  - Ticker data                  │
│  - Historical klines            │
│  - Order placement              │
│  - Account info                 │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Binance REST API (Public/Auth) │
│  https://fapi.binance.com/      │
└─────────────────────────────────┘
```

## Key Features

### WebSocketMonitor
- ✅ **Auto-reconnection** — exponential backoff up to 30s
- ✅ **Exit detection** — Stop Loss, Take Profit 1, Trailing Stop
- ✅ **Bid/Ask tracking** — uses bookTicker for precise pricing
- ✅ **PnL calculation** — returns percentage gain/loss on exit
- ✅ **Connection status** — get real-time monitor health
- ✅ **Callback support** — execute custom logic on exit

### BinanceWebSocketClient
- ✅ **Multiple stream types** — bookTicker, kline, trade, aggTrade
- ✅ **Async callbacks** — non-blocking price updates
- ✅ **Auto-reconnection** — seamless recovery from disconnects
- ✅ **JSON parsing** — automatic message deserialization

### BinanceRESTClient
- ✅ **Ticker data** — current price, 24h change, volume
- ✅ **Historical candles** — klines for backtesting
- ✅ **Account info** — requires API key
- ✅ **Order placement** — market orders with signature
- ✅ **Leverage setting** — futures-specific params

## Usage Examples

### 1. Monitor Position Until Exit

```python
import asyncio
from websocket_monitor import WebSocketMonitor

position = {
    "direction": "LONG",
    "entry_price": 2500.00,
    "stop_price": 2450.00,      # 2% SL
    "tp1_price": 2550.00,       # 2% TP1
    "tp1_hit": False,
}

ws_url = "wss://fstream.binance.com/ws/ethusdt@bookTicker"
monitor = WebSocketMonitor(ws_url, position, ema_fast=2480.00)

def on_exit(exit_info):
    print(f"Exit: {exit_info['reason']} @ {exit_info['price']:.2f}")
    print(f"PnL: {exit_info['pnl_pct']:.2f}%")

monitor.set_exit_callback(on_exit)

# Run until position closes
exit_result = await monitor.monitor()
```

### 2. Stream Real-Time Prices

```python
from websocket_direct import BinanceWebSocketClient

client = BinanceWebSocketClient("ETHUSDT", "bookTicker")

async def on_price_update(data):
    print(f"Price: {data['mid']:.2f} | Bid: {data['bid']:.2f} | Ask: {data['ask']:.2f}")

client.set_callback(on_price_update)

# Start streaming
await client.connect()
```

### 3. Multi-Symbol Monitoring

```python
from websocket_direct import MultiSymbolMonitor

monitor = MultiSymbolMonitor()
monitor.add_symbol("ETHUSDT", "bookTicker")
monitor.add_symbol("BTCUSDT", "bookTicker")

async def on_update(data):
    prices = monitor.get_prices()
    print(f"ETH: ${prices.get('ethusdt')} | BTC: ${prices.get('btcusdt')}")

monitor.set_global_callback(on_update)

# Run both simultaneously
await monitor.start()
```

### 4. REST API Calls

```python
from websocket_direct import BinanceRESTClient

client = BinanceRESTClient()

# Get current price
ticker = client.get_ticker("ETHUSDT")
print(f"Price: ${ticker['lastPrice']}")

# Get 100 1H candles
klines = client.get_klines("ETHUSDT", "1h", limit=100)
for kline in klines:
    print(f"Close: {float(kline[4])}")

# Place order (requires API key)
order = client.place_market_order("ETHUSDT", "BUY", 1.0)
```

## Configuration

Set environment variables:

```bash
# Binance credentials
export BINANCE_API_KEY="your_key"
export BINANCE_API_SECRET="your_secret"

# Use testnet (optional)
export BINANCE_TESTNET="true"

# Trading mode
export TRADING_MODE="paper"  # or "live"
```

## Error Handling

All modules include automatic reconnection:

```python
monitor = WebSocketMonitor(ws_url, position, ema_fast)

# Monitor auto-retries up to 10 times with exponential backoff
# Max wait between attempts: 30 seconds
await monitor.monitor()  # Returns on exit or max retries

# Check status
status = monitor.get_connection_status()
print(f"Connected: {status['connected']}")
print(f"Reconnect attempts: {status['reconnect_attempts']}")
```

## Stream Types

### bookTicker (Recommended)
- Best bid/ask prices with quantities
- **Update frequency:** Every price change
- **Latency:** ~100-500ms
- **Use case:** Precise entry/exit detection

### kline
- Candlestick data
- **Update frequency:** Every trade within candle
- **Use case:** Technical analysis, trend detection

### aggTrade
- Aggregate trades
- **Update frequency:** Every trade
- **Use case:** Volume analysis

### trade
- Individual trades
- **Use case:** Ultra-low latency applications

## Testing

Run examples:

```bash
python websocket_example.py
```

Individual examples:

```python
# Test REST API only (no WebSocket)
asyncio.run(example_rest_api())

# Test position monitoring (requires live connection)
asyncio.run(example_monitor_position())

# Test multi-symbol streaming
asyncio.run(example_multi_symbol_streaming())
```

## Integration with Existing Code

### Replace CCXT WebSocket calls:

**Before (CCXT):**
```python
ws_url = exchange.get_websocket_url("ETH/USDT")
```

**After (Direct):**
```python
from websocket_direct import BinanceWebSocketClient
ws_url = "wss://fstream.binance.com/ws/ethusdt@bookTicker"
```

### Replace REST calls:

**Before (CCXT):**
```python
ticker = exchange.fetch_ticker("ETH/USDT")
price = float(ticker["last"])
```

**After (Direct):**
```python
from websocket_direct import BinanceRESTClient
client = BinanceRESTClient()
ticker = client.get_ticker("ETHUSDT")
price = float(ticker["lastPrice"])
```

## Performance Characteristics

| Operation | Latency | Frequency |
|-----------|---------|-----------|
| bookTicker update | 100-500ms | Per price change |
| Order placement | ~1000ms | On demand |
| Kline close | 1 minute | Per candle |
| Account sync | ~500ms | On demand |

## Troubleshooting

### WebSocket keeps disconnecting
- Check network connectivity
- Verify URL is correct for testnet/mainnet
- Check max_reconnect_attempts (default: 10)

### Missing price updates
- Verify symbol format (ETHUSDT, not ETH/USDT)
- Check WebSocket callback is set
- Monitor logs for JSON parsing errors

### API signature errors
- Verify BINANCE_API_KEY and BINANCE_API_SECRET
- Check system clock is synced (API requires correct timestamp)
- Verify API key has required permissions

## Dependencies

```
websockets>=10.0
requests>=2.28.0
python-dotenv>=0.20.0
```

## Next Steps

1. **Integration:** Replace CCXT calls in `exchange.py` and traders
2. **Testing:** Run `websocket_example.py` on testnet
3. **Monitoring:** Add logging to CloudWatch or similar
4. **Deployment:** Deploy to VPS with 24/7 connection
