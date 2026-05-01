"""
Quant Agent — analyzes ETH/USDT technical indicators and outputs a structured signal.
Uses prompt caching on the static system prompt to minimize API costs.
"""
import json
import logging
from agents.base_agent import get_client, MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a quantitative analyst for an ETH/USDT futures trading system using 3x leverage.

STRATEGY RULES:
- Timeframes: 1H entry signals confirmed by 4H trend
- EMA system: EMA_fast (21) / EMA_mid (50) / EMA_slow (200)
- LONG entries: EMA_fast crosses above EMA_mid, price above EMA_slow on 4H, RSI 45-75, volume spike
- SHORT entries: EMA_fast crosses below EMA_mid, price below EMA_slow on 4H, RSI 25-55, volume spike
- Stop loss: EMA_mid ± 1% buffer; TP1 at 2.5x risk (50% close), then trail on EMA_fast

EMA ALIGNMENT SCORING:
- Bullish stack (price > EMA_fast > EMA_mid > EMA_slow): strong uptrend
- Bearish stack (price < EMA_fast < EMA_mid < EMA_slow): strong downtrend
- Mixed: weak or transitional

Respond ONLY with valid JSON — no markdown, no explanation outside the JSON block.

OUTPUT FORMAT:
{
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <integer 0-100>,
  "ema_analysis": "<EMA stack and crossover assessment>",
  "rsi_analysis": "<RSI level and zone interpretation>",
  "volume_analysis": "<volume vs average and what it implies>",
  "trend_4h": "<4H trend direction and strength>",
  "key_levels": {
    "support": <nearest support price as float>,
    "resistance": <nearest resistance price as float>
  },
  "reasoning": "<1-2 sentence trade rationale>"
}"""


def analyze(market_state: dict, reflect_context: str = "") -> dict:
    """
    Analyze current market state and return structured signal.

    Args:
        market_state: dict from market_state.get_current_market_state()
        reflect_context: optional learning context from reflect agent

    Returns:
        dict with keys: signal, confidence, ema_analysis, rsi_analysis,
                        volume_analysis, trend_4h, key_levels, reasoning
    """
    client = get_client()

    price = market_state["price"]
    ema_fast = market_state["ema_fast"]
    ema_mid = market_state["ema_mid"]
    ema_slow = market_state["ema_slow"]
    rsi = market_state["rsi"]
    volume = market_state["volume"]
    volume_ma = market_state["volume_ma"]
    volume_ratio = volume / volume_ma if volume_ma > 0 else 1.0
    trend_4h = market_state["trend_4h_bullish"]
    cross_up = market_state.get("ema_cross_up", False)
    cross_down = market_state.get("ema_cross_down", False)
    recent_closes = market_state.get("recent_closes", [])

    price_vs_fast = "above" if price > ema_fast else "below"
    price_vs_mid = "above" if price > ema_mid else "below"
    price_vs_slow = "above" if price > ema_slow else "below"
    fast_vs_mid = "above" if ema_fast > ema_mid else "below"

    user_content = f"""CURRENT MARKET STATE — ETH/USDT (1H candle):
Timestamp: {market_state.get('timestamp', 'N/A')}
Price: ${price:,.2f}

EMA Values:
  EMA_fast (21): ${ema_fast:,.2f}  → price is {price_vs_fast} EMA_fast
  EMA_mid  (50): ${ema_mid:,.2f}  → price is {price_vs_mid} EMA_mid, EMA_fast is {fast_vs_mid} EMA_mid
  EMA_slow (200): ${ema_slow:,.2f} → price is {price_vs_slow} EMA_slow

Crossover event this candle:
  EMA_fast crossed UP through EMA_mid: {cross_up}
  EMA_fast crossed DOWN through EMA_mid: {cross_down}

RSI (14): {rsi:.1f}
  LONG zone: 45-75 | SHORT zone: 25-55 | Current: {'in LONG zone' if 45 <= rsi <= 75 else 'in SHORT zone' if 25 <= rsi <= 55 else 'outside both zones'}

Volume: {volume:,.0f} | 20-period avg: {volume_ma:,.0f} | Ratio: {volume_ratio:.2f}x
  Volume signal: {'CONFIRMED (>1x avg)' if volume_ratio >= 1.0 else 'WEAK (<1x avg)'}

4H Trend: {'BULLISH (price > EMA_slow on 4H)' if trend_4h else 'BEARISH (price < EMA_slow on 4H)'}

Recent closes (last 10 candles, oldest→newest): {[f'{c:,.0f}' for c in recent_closes]}
"""

    if reflect_context:
        user_content += f"\nLEARNING CONTEXT FROM PAST TRADES:\n{reflect_context}\n"

    user_content += "\nAnalyze this setup and return your JSON assessment."

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        logger.info(f"Quant signal: {result.get('signal')} (confidence {result.get('confidence')})")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Quant agent JSON parse error: {e} | raw: {raw[:200]}")
        return {"signal": "NEUTRAL", "confidence": 0, "reasoning": "Parse error", "error": str(e)}
    except Exception as e:
        logger.error(f"Quant agent error: {e}")
        return {"signal": "NEUTRAL", "confidence": 0, "reasoning": "Agent error", "error": str(e)}
