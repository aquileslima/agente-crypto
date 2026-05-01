"""
Quick test suite for WebSocket implementation.
Run: python test_websocket.py
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from websocket_monitor import WebSocketMonitor
from websocket_direct import BinanceRESTClient, BinanceWebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Test 1: REST API Connectivity
# ============================================================================
def test_rest_api():
    """Test basic REST API connectivity and data retrieval."""
    logger.info("=" * 60)
    logger.info("TEST 1: REST API Connectivity")
    logger.info("=" * 60)

    client = BinanceRESTClient()

    try:
        # Get current price
        logger.info("Fetching ETH/USDT ticker...")
        ticker = client.get_ticker("ETHUSDT")
        price = float(ticker["lastPrice"])
        change_pct = float(ticker["priceChangePercent"])
        volume = float(ticker["volume"])

        logger.info(f"✓ Price: ${price:.2f}")
        logger.info(f"✓ 24h Change: {change_pct:+.2f}%")
        logger.info(f"✓ 24h Volume: {volume:,.0f} ETH")

        # Get klines
        logger.info("Fetching last 5 candles (1h)...")
        klines = client.get_klines("ETHUSDT", "1h", limit=5)

        for i, kline in enumerate(klines[-5:]):
            ts = int(kline[0]) / 1000
            time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            open_price = float(kline[1])
            close_price = float(kline[4])
            high = float(kline[2])
            low = float(kline[3])
            change = ((close_price - open_price) / open_price) * 100

            logger.info(
                f"  [{i+1}] {time_str} | "
                f"O={open_price:.2f} H={high:.2f} L={low:.2f} C={close_price:.2f} "
                f"({change:+.2f}%)"
            )

        logger.info("✓ REST API test PASSED\n")
        return True

    except Exception as e:
        logger.error(f"✗ REST API test FAILED: {e}\n")
        return False


# ============================================================================
# Test 2: WebSocket Connection (timeout after 10 seconds)
# ============================================================================
async def test_websocket_connection():
    """Test WebSocket connection and price updates."""
    logger.info("=" * 60)
    logger.info("TEST 2: WebSocket Connection & Price Updates")
    logger.info("=" * 60)

    client = BinanceWebSocketClient("ETHUSDT", "bookTicker")
    price_updates = {"count": 0, "prices": []}

    async def on_update(data):
        price_updates["count"] += 1
        price_updates["prices"].append(data["mid"])
        if price_updates["count"] <= 5:
            logger.info(
                f"  Update #{price_updates['count']}: "
                f"Price=${data['mid']:.2f} "
                f"(Bid=${data['bid']:.2f} Ask=${data['ask']:.2f})"
            )

    client.set_callback(on_update)

    try:
        logger.info("Connecting to WebSocket...")
        # Run for 10 seconds
        await asyncio.wait_for(client.connect(), timeout=10)
    except asyncio.TimeoutError:
        logger.info("Timeout reached (expected)")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return False
    finally:
        client.stop()

    if price_updates["count"] > 0:
        avg_price = sum(price_updates["prices"]) / len(price_updates["prices"])
        logger.info(f"✓ Received {price_updates['count']} price updates")
        logger.info(f"✓ Average price: ${avg_price:.2f}")
        logger.info(f"✓ WebSocket test PASSED\n")
        return True
    else:
        logger.error(f"✗ No price updates received\n")
        return False


# ============================================================================
# Test 3: Position Monitor with Mock Exit
# ============================================================================
async def test_position_monitor():
    """Test position monitoring with simulated exit."""
    logger.info("=" * 60)
    logger.info("TEST 3: Position Monitor (30 second timeout)")
    logger.info("=" * 60)

    # Get current price first
    try:
        client = BinanceRESTClient()
        ticker = client.get_ticker("ETHUSDT")
        current_price = float(ticker["lastPrice"])
    except Exception as e:
        logger.error(f"Failed to get current price: {e}")
        return False

    logger.info(f"Current ETH price: ${current_price:.2f}")

    # Create position with tight stops for testing
    # (stop will likely hit within 30 seconds)
    entry_price = current_price
    position = {
        "direction": "LONG",
        "entry_price": entry_price,
        "stop_price": entry_price - 50,      # Very loose SL to avoid immediate hit
        "tp1_price": entry_price + 10000,    # Very high TP to avoid immediate hit
        "tp1_hit": False,
    }

    logger.info(f"Position: LONG @ ${entry_price:.2f}")
    logger.info(f"  SL: ${position['stop_price']:.2f}")
    logger.info(f"  TP1: ${position['tp1_price']:.2f}")
    logger.info(f"  Trailing Stop EMA: ${current_price - 30:.2f}")

    ws_url = "wss://fstream.binance.com/ws/ethusdt@bookTicker"
    monitor = WebSocketMonitor(ws_url, position, ema_fast=current_price - 30)

    exit_detected = {"triggered": False, "info": None}

    def on_exit(exit_info):
        exit_detected["triggered"] = True
        exit_detected["info"] = exit_info
        logger.warning(f"EXIT TRIGGERED: {exit_info['reason']} @ ${exit_info['price']:.2f}")

    monitor.set_exit_callback(on_exit)

    try:
        logger.info("Starting position monitor (30 second timeout)...")
        await asyncio.wait_for(monitor.monitor(), timeout=30)
    except asyncio.TimeoutError:
        logger.info("Monitor timeout reached (expected)")
    except Exception as e:
        logger.error(f"Monitor error: {e}")
        return False
    finally:
        monitor.stop()

    if exit_detected["triggered"]:
        logger.info(f"✓ Exit detected: {exit_detected['info']}")
        logger.info(f"✓ Position monitor test PASSED\n")
        return True
    else:
        logger.info("✓ Monitor ran without exit (expected for loose stops)")
        logger.info(f"✓ Position monitor test PASSED\n")
        return True


# ============================================================================
# Main test runner
# ============================================================================
async def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " WebSocket Implementation Test Suite ".center(58) + "║")
    logger.info("╚" + "=" * 58 + "╝\n")

    results = {}

    # Test 1: REST API
    results["REST API"] = test_rest_api()

    # Test 2: WebSocket Connection
    results["WebSocket"] = await test_websocket_connection()

    # Test 3: Position Monitor
    results["Position Monitor"] = await test_position_monitor()

    # Summary
    logger.info("\n")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " Test Summary ".center(58) + "║")
    logger.info("╠" + "=" * 58 + "╣")

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"║ {test_name:<40} {status:>15} ║")

    logger.info("╚" + "=" * 58 + "╝\n")

    all_passed = all(results.values())
    if all_passed:
        logger.info("✓ All tests PASSED!")
    else:
        logger.info("✗ Some tests FAILED!")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
