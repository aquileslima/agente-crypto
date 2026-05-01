#!/usr/bin/env python3
"""
Test RealTrader WebSocket integration.
Verifies that the new pure WebSocket implementation works correctly.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

def test_exit_condition_detection():
    """Test the _check_exit_condition method without WebSocket."""
    logger.info("=" * 60)
    logger.info("TEST 1: Exit Condition Detection (Unit Test)")
    logger.info("=" * 60)

    from real_trader import RealTrader

    # Create trader instance
    trader = RealTrader()

    # Simulate a LONG position
    position = {
        "direction": "LONG",
        "entry_price": 2500.00,
        "stop_price": 2450.00,
        "tp1_price": 2550.00,
        "tp1_hit": False,
    }
    trader.state["position"] = position

    # Test scenarios
    test_cases = [
        # (current_price, ema_fast, expected_exit_reason)
        (2450.00, 2480.00, "STOP LOSS"),    # Hit SL
        (2550.00, 2480.00, "TP1"),          # Hit TP1
        (2475.00, 2475.00, "TRAILING STOP"), # EMA trailing stop
        (2475.00, 2480.00, None),           # No exit
    ]

    passed = 0
    failed = 0

    for current_price, ema_fast, expected in test_cases:
        result = trader._check_exit_condition(current_price, ema_fast)
        reason = result["reason"] if result else None
        status = "✓" if reason == expected else "✗"

        if reason == expected:
            passed += 1
            logger.info(f"{status} Price ${current_price:.2f}: {reason or 'No exit'} (expected)")
        else:
            failed += 1
            logger.error(f"{status} Price ${current_price:.2f}: Got {reason}, expected {expected}")

    logger.info(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_imports():
    """Test that all necessary imports work."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Import Verification")
    logger.info("=" * 60)

    try:
        from real_trader import RealTrader
        logger.info("✓ RealTrader imported")

        from websocket_direct import BinanceWebSocketClient
        logger.info("✓ BinanceWebSocketClient imported")

        from websocket_direct import BinanceRESTClient
        logger.info("✓ BinanceRESTClient imported")

        # Check method exists
        trader = RealTrader()
        assert hasattr(trader, "monitor_exits_async"), "monitor_exits_async method missing"
        logger.info("✓ monitor_exits_async method exists")

        assert hasattr(trader, "_check_exit_condition"), "_check_exit_condition method missing"
        logger.info("✓ _check_exit_condition method exists")

        logger.info("\n✓ All imports OK")
        return True

    except Exception as e:
        logger.error(f"✗ Import test failed: {e}")
        return False


def test_state_persistence():
    """Test that trader state is persisted correctly."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: State Persistence")
    logger.info("=" * 60)

    from real_trader import RealTrader

    try:
        # Create trader
        trader1 = RealTrader()
        initial_capital = trader1.capital
        logger.info(f"✓ Trader 1 created with capital: ${initial_capital:,.2f}")

        # Modify state
        trader1.state["capital"] = initial_capital + 100
        trader1._save_state()
        logger.info("✓ State modified and saved")

        # Create new trader (should load persisted state)
        trader2 = RealTrader()
        assert trader2.capital == initial_capital + 100, "State not persisted"
        logger.info(f"✓ Trader 2 loaded persisted state: ${trader2.capital:,.2f}")

        # Restore original
        trader2.state["capital"] = initial_capital
        trader2._save_state()
        logger.info("✓ State restored")

        return True

    except Exception as e:
        logger.error(f"✗ State persistence test failed: {e}")
        return False


def test_websocket_client_creation():
    """Test that BinanceWebSocketClient can be created."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: WebSocket Client Creation")
    logger.info("=" * 60)

    try:
        from websocket_direct import BinanceWebSocketClient

        # Create client
        client = BinanceWebSocketClient("ETHUSDT", "bookTicker")
        logger.info("✓ BinanceWebSocketClient created")

        # Check properties
        assert client.symbol == "ethusdt", "Symbol not set correctly"
        logger.info(f"✓ Symbol: {client.symbol}")

        assert client.stream_type == "bookTicker", "Stream type not set"
        logger.info(f"✓ Stream type: {client.stream_type}")

        assert client.ws_url, "WebSocket URL not set"
        logger.info(f"✓ WebSocket URL ready")

        # Check methods
        assert hasattr(client, "connect"), "connect method missing"
        assert hasattr(client, "set_callback"), "set_callback method missing"
        assert hasattr(client, "stop"), "stop method missing"
        logger.info("✓ All required methods exist")

        return True

    except Exception as e:
        logger.error(f"✗ WebSocket client test failed: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " RealTrader WebSocket Integration Tests ".center(58) + "║")
    logger.info("╚" + "=" * 58 + "╝\n")

    results = {}

    # Test 1: Exit condition detection
    results["Exit Detection"] = test_exit_condition_detection()

    # Test 2: Imports
    results["Imports"] = test_imports()

    # Test 3: State persistence
    results["State Persistence"] = test_state_persistence()

    # Test 4: WebSocket client
    results["WebSocket Client"] = test_websocket_client_creation()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status:8} — {test_name}")

    logger.info("\n" + "=" * 60)
    if passed == total:
        logger.info(f"✓ All {total} tests PASSED! Ready for deployment.")
        return 0
    else:
        logger.info(f"✗ {total - passed} of {total} tests FAILED.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
