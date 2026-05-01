"""
WebSocket Direct — Direct connection to Binance WebSocket without CCXT.
Pure requests/websockets implementation for real-time monitoring.
"""
import asyncio
import json
import logging
import os
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import requests
import websockets

logger = logging.getLogger(__name__)

# Binance API settings
BINANCE_BASE_URL = "https://testnet.binancefuture.com" if os.getenv("BINANCE_TESTNET", "false").lower() == "true" else "https://fapi.binance.com"
BINANCE_WS_BASE = "wss://stream.testnet.binancefuture.com" if os.getenv("BINANCE_TESTNET", "false").lower() == "true" else "wss://fstream.binance.com"
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")


class BinanceRESTClient:
    """Synchronous REST client for Binance Futures API."""

    def __init__(self, testnet: bool = False):
        self.base_url = BINANCE_BASE_URL
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.testnet = testnet

    def _sign_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add signature to request."""
        timestamp = int(time.time() * 1000)
        params["timestamp"] = timestamp
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, signed: bool = False) -> Dict:
        """Make HTTP request to Binance API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key} if self.api_key else {}

        if signed and params:
            params = self._sign_request(params)

        try:
            if method == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, params=params, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"REST request failed: {e}")
            raise

    def get_ticker(self, symbol: str = "ETHUSDT") -> Dict[str, Any]:
        """Get current ticker info."""
        return self._make_request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol})

    def get_klines(self, symbol: str = "ETHUSDT", interval: str = "1h", limit: int = 100) -> list:
        """Get historical candles."""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return self._make_request("GET", "/fapi/v1/klines", params)

    def get_account_info(self) -> Dict[str, Any]:
        """Get account info (requires API key)."""
        return self._make_request("GET", "/fapi/v2/account", {}, signed=True)

    def get_positions(self, symbol: str = "ETHUSDT") -> Dict[str, Any]:
        """Get open positions for a symbol."""
        return self._make_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)

    def place_market_order(self, symbol: str, side: str, quantity: float, reduce_only: bool = False) -> Dict:
        """Place market order (requires API key)."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        return self._make_request("POST", "/fapi/v1/order", params, signed=True)

    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Set leverage for symbol."""
        params = {"symbol": symbol, "leverage": leverage}
        return self._make_request("POST", "/fapi/v1/leverage", params, signed=True)


class BinanceWebSocketClient:
    """Async WebSocket client for Binance real-time price updates."""

    def __init__(self, symbol: str = "ETHUSDT", stream_type: str = "bookTicker"):
        """
        Args:
            symbol: Trading pair (e.g., ETHUSDT)
            stream_type: Stream type (bookTicker, kline, trade, aggTrade)
        """
        self.symbol = symbol.lower()
        self.stream_type = stream_type
        self.ws_url = f"{BINANCE_WS_BASE}/ws/{self.symbol}@{stream_type}"
        self.ws = None
        self.running = False
        self.last_price = None
        self.last_bid = None
        self.last_ask = None
        self.callback = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10

    def set_callback(self, callback) -> None:
        """Set callback function for price updates."""
        self.callback = callback

    async def connect(self) -> None:
        """Connect and start streaming."""
        self.running = True
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self._stream()
            except Exception as e:
                self.reconnect_attempts += 1
                wait_time = min(2 ** self.reconnect_attempts, 30)
                logger.warning(
                    f"WebSocket error (attempt {self.reconnect_attempts}/"
                    f"{self.max_reconnect_attempts}): {e}. Reconnecting in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

    async def _stream(self) -> None:
        """Stream data from WebSocket."""
        async with websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=10,
            compression=None,
        ) as ws:
            self.ws = ws
            self.reconnect_attempts = 0
            logger.info(f"WebSocket connected: {self.ws_url}")

            while self.running:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=60)
                    data = json.loads(message)
                    await self._process_message(data)
                except asyncio.TimeoutError:
                    logger.warning("WebSocket timeout")
                    raise ConnectionError("WebSocket timeout")
                except json.JSONDecodeError:
                    logger.debug("Invalid JSON from WebSocket")
                    continue

    async def _process_message(self, data: Dict[str, Any]) -> None:
        """Process incoming message based on stream type."""
        if self.stream_type == "bookTicker":
            self.last_bid = float(data.get("b", 0))
            self.last_ask = float(data.get("a", 0))
            self.last_price = (self.last_bid + self.last_ask) / 2

            if self.callback:
                await self.callback({
                    "type": "price_update",
                    "symbol": self.symbol,
                    "bid": self.last_bid,
                    "ask": self.last_ask,
                    "mid": self.last_price,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        elif self.stream_type == "kline":
            kline = data.get("k", {})
            close_price = float(kline.get("c", 0))
            volume = float(kline.get("v", 0))
            time_ms = int(kline.get("T", 0))

            if self.callback:
                await self.callback({
                    "type": "kline",
                    "symbol": self.symbol,
                    "close": close_price,
                    "volume": volume,
                    "time": datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).isoformat(),
                    "is_closed": bool(kline.get("x")),
                })

    def stop(self) -> None:
        """Stop streaming."""
        self.running = False
        logger.info(f"WebSocket stream stopped: {self.symbol}")

    def get_last_price(self) -> Optional[float]:
        """Get last received price."""
        return self.last_price


class MultiSymbolMonitor:
    """Monitor multiple symbols simultaneously."""

    def __init__(self):
        self.clients: Dict[str, BinanceWebSocketClient] = {}
        self.tasks = []
        self.global_callback = None

    def add_symbol(self, symbol: str, stream_type: str = "bookTicker") -> None:
        """Add symbol to monitoring."""
        if symbol not in self.clients:
            client = BinanceWebSocketClient(symbol, stream_type)
            client.set_callback(self._on_update)
            self.clients[symbol] = client
            logger.info(f"Added symbol to monitor: {symbol}")

    async def _on_update(self, data: Dict[str, Any]) -> None:
        """Handle price update from any symbol."""
        if self.global_callback:
            await self.global_callback(data)

    def set_global_callback(self, callback) -> None:
        """Set global callback for all updates."""
        self.global_callback = callback

    async def start(self) -> None:
        """Start monitoring all symbols."""
        self.tasks = [
            asyncio.create_task(client.connect())
            for client in self.clients.values()
        ]
        logger.info(f"Started monitoring {len(self.tasks)} symbol(s)")
        await asyncio.gather(*self.tasks)

    def stop(self) -> None:
        """Stop all monitoring."""
        for client in self.clients.values():
            client.stop()
        for task in self.tasks:
            task.cancel()
        logger.info("All monitors stopped")

    def get_prices(self) -> Dict[str, float]:
        """Get last prices for all symbols."""
        return {symbol: client.get_last_price() for symbol, client in self.clients.items()}
