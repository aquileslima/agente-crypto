"""
WebSocket Runner — async task to monitor positions in real-time.
Runs in background while main bot loop executes.
"""
import asyncio
import logging
from datetime import datetime, timezone

from market_state import get_current_market_state

logger = logging.getLogger(__name__)


async def monitor_position_in_background(trader, interval_seconds: int = 5) -> None:
    """
    Monitor open position via WebSocket in background.
    Checks every N seconds while position is open.
    """
    while trader.has_position():
        try:
            # Get current EMA for trailing stop
            ms = get_current_market_state(max_cache_hours=0.5)
            ema_fast = ms.get("ema_fast", 0)

            pos = trader.get_position()
            if pos and hasattr(trader, "monitor_exits_async"):
                # RealTrader with async support
                logger.debug(f"WebSocket monitoring active for {pos['direction']}")
                await trader.monitor_exits_async(ema_fast)
                # If monitor returns, position was closed
                break
            else:
                # PaperTrader - just sleep
                await asyncio.sleep(interval_seconds)

        except Exception as e:
            logger.error(f"WebSocket monitor error: {e}")
            await asyncio.sleep(interval_seconds)


def start_websocket_monitor(trader, loop: asyncio.AbstractEventLoop) -> asyncio.Task | None:
    """
    Start WebSocket monitoring task in background.
    Returns task handle or None if not applicable.
    """
    if hasattr(trader, "monitor_exits_async"):
        logger.info("Starting WebSocket monitor...")
        return loop.create_task(monitor_position_in_background(trader))
    return None
