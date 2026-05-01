"""
WebSocket Integration Example — demonstrates using websocket_monitor and websocket_direct
"""
import asyncio
import logging
from datetime import datetime, timezone

from websocket_monitor import WebSocketMonitor
from websocket_direct import BinanceWebSocketClient, MultiSymbolMonitor, BinanceRESTClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Example 1: Single position monitoring with exit detection
# ============================================================================
async def example_monitor_position():
    """Monitor a single position until exit (SL/TP/trailing stop)."""
    logger.info("=== Example 1: Position Monitoring ===")

    # Simulated position
    position = {
        "direction": "LONG",
        "entry_price": 2500.00,
        "stop_price": 2450.00,      # Stop loss 2% below entry
        "tp1_price": 2550.00,       # Take profit 1 at 2% above
        "tp1_hit": False,
    }

    # Monitor setup
    ws_url = "wss://fstream.binance.com/ws/ethusdt@bookTicker"
    monitor = WebSocketMonitor(ws_url, position, ema_fast=2480.00)

    # Set exit callback
    def on_exit(exit_info):
        logger.warning(f"EXIT SIGNAL: {exit_info['reason']} @ {exit_info['price']:.2f}")
        logger.warning(f"  PnL: {exit_info.get('pnl_pct', 0):.2f}%")

    monitor.set_exit_callback(on_exit)

    # Start monitoring
    logger.info("Starting position monitor...")
    result = await asyncio.wait_for(monitor.monitor(), timeout=300)  # 5 min timeout

    if result:
        logger.info(f"Position closed: {result}")
    else:
        logger.info("Monitor completed without exit")

    # Status
    status = monitor.get_connection_status()
    logger.info(f"Final status: {status}")


# ============================================================================
# Example 2: Real-time price streaming with multiple symbols
# ============================================================================
async def example_multi_symbol_streaming():
    """Stream real-time prices for multiple symbols."""
    logger.info("=== Example 2: Multi-Symbol Streaming ===")

    monitor = MultiSymbolMonitor()
    monitor.add_symbol("ETHUSDT", "bookTicker")
    monitor.add_symbol("BTCUSDT", "bookTicker")

    # Global callback for all price updates
    async def on_price_update(data):
        if data["type"] == "price_update":
            symbol = data["symbol"].upper()
            mid = data["mid"]
            bid = data["bid"]
            ask = data["ask"]
            logger.info(f"{symbol}: ${mid:.2f} (bid=${bid:.2f} ask=${ask:.2f})")

    monitor.set_global_callback(on_price_update)

    # Run for 30 seconds
    try:
        await asyncio.wait_for(monitor.start(), timeout=30)
    except asyncio.TimeoutError:
        logger.info("Time limit reached")
    finally:
        monitor.stop()
        prices = monitor.get_prices()
        logger.info(f"Final prices: {prices}")


# ============================================================================
# Example 3: Using REST client for order placement
# ============================================================================
async def example_rest_api():
    """Demonstrate REST API calls."""
    logger.info("=== Example 3: REST API Usage ===")

    client = BinanceRESTClient()

    # Get current price
    try:
        ticker = client.get_ticker("ETHUSDT")
        logger.info(f"ETH Last Price: ${ticker['lastPrice']}")
        logger.info(f"ETH 24h Change: {ticker['priceChangePercent']:.2f}%")
    except Exception as e:
        logger.error(f"Failed to get ticker: {e}")

    # Get historical klines
    try:
        klines = client.get_klines("ETHUSDT", "1h", limit=5)
        logger.info("Last 5 1H candles:")
        for kline in klines[-5:]:
            timestamp = datetime.fromtimestamp(int(kline[0]) / 1000, tz=timezone.utc)
            open_price = float(kline[1])
            close_price = float(kline[4])
            volume = float(kline[7])
            logger.info(f"  {timestamp}: O={open_price:.2f} C={close_price:.2f} V={volume:.0f}")
    except Exception as e:
        logger.error(f"Failed to get klines: {e}")


# ============================================================================
# Example 4: Combined monitoring + REST client
# ============================================================================
async def example_integrated_monitoring():
    """Monitor price with REST API for entry decision."""
    logger.info("=== Example 4: Integrated Monitoring ===")

    rest_client = BinanceRESTClient()

    # Get current market state
    try:
        ticker = rest_client.get_ticker("ETHUSDT")
        current_price = float(ticker["lastPrice"])
        logger.info(f"Current ETH Price: ${current_price:.2f}")

        # Hypothetical position
        entry_price = current_price - 10  # Assume entry 10$ below current
        position = {
            "direction": "LONG",
            "entry_price": entry_price,
            "stop_price": entry_price - 20,  # 2% stop
            "tp1_price": entry_price + 30,   # 3% TP1
            "tp1_hit": False,
        }

        logger.info(f"Position: LONG @ ${entry_price:.2f} | SL: ${position['stop_price']:.2f} | TP1: ${position['tp1_price']:.2f}")

        # Start monitoring
        ws_url = "wss://fstream.binance.com/ws/ethusdt@bookTicker"
        monitor = WebSocketMonitor(ws_url, position, ema_fast=current_price - 5)

        def on_exit(exit_info):
            logger.warning(f"POSITION CLOSED: {exit_info['reason']}")

        monitor.set_exit_callback(on_exit)

        # Monitor with 60 second timeout
        logger.info("Monitoring position (60s)...")
        await asyncio.wait_for(monitor.monitor(), timeout=60)

    except Exception as e:
        logger.error(f"Integrated monitoring failed: {e}")


# ============================================================================
# Main runner
# ============================================================================
async def main():
    """Run examples."""
    # Example 3 (REST) doesn't require testnet
    await example_rest_api()

    # Uncomment to test others (requires WebSocket connectivity)
    # await example_monitor_position()
    # await example_multi_symbol_streaming()
    # await example_integrated_monitoring()


if __name__ == "__main__":
    asyncio.run(main())
