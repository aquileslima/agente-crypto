"""
Decisor Agent — consolidates Quant + Sentiment signals and makes the final
LONG / SHORT / NEUTRAL decision with justification.
"""
import json
import logging
from agents.base_agent import get_client, MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the chief trading officer for an ETH/USDT futures system with 3x leverage.

You receive analysis from two specialized agents:
1. QUANT AGENT: technical indicators — EMA crossovers, RSI, volume, 4H trend
2. SENTIMENT AGENT: Reddit tone + Fear & Greed Index

Your job: synthesize both inputs into one final trade decision.

DECISION FRAMEWORK:
- LONG: quant is BULLISH (confidence ≥ 60) + sentiment not in Extreme Greed (≤ 80) + 4H trend bullish
- SHORT: quant is BEARISH (confidence ≥ 60) + sentiment not in Extreme Fear (≥ 20) + 4H trend bearish
- NEUTRAL: conflicting signals, low confidence, or dangerous sentiment extremes
- Sentiment acts as a filter, not the primary driver — technicals lead
- Extreme Fear (sentiment score ≤ 15) = contrarian LONG opportunity (override to LONG if quant agrees)
- Extreme Greed (sentiment score ≥ 85) = contrarian SHORT opportunity (override to SHORT if quant agrees)

RISK RULES (never deviate):
- Do NOT go LONG when 4H trend is BEARISH unless sentiment is Extreme Fear AND confidence ≥ 75
- Do NOT go SHORT when 4H trend is BULLISH unless sentiment is Extreme Greed AND confidence ≥ 75
- If quant confidence < 50: always return NEUTRAL regardless of sentiment

Respond ONLY with valid JSON — no markdown, no extra text.

OUTPUT FORMAT:
{
  "decision": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <integer 0-100>,
  "quant_weight": <0.0-1.0, how much quant influenced the decision>,
  "sentiment_weight": <0.0-1.0, how much sentiment influenced>,
  "justification": "<2-3 sentences explaining the decision>",
  "risk_note": "<any risk warning or special condition>",
  "entry_allowed": <true | false>
}"""


def decide(
    quant_result: dict,
    sentiment_result: dict,
    reflect_context: str = "",
) -> dict:
    """
    Make final trade decision from quant + sentiment analysis.

    Args:
        quant_result: output from quant_agent.analyze()
        sentiment_result: output from sentiment_agent.analyze()
        reflect_context: learning context from reflect_agent.analyze_and_update()

    Returns:
        dict with: decision, confidence, justification, entry_allowed, risk_note
    """
    client = get_client()

    quant_signal = quant_result.get("signal", "NEUTRAL")
    quant_conf = quant_result.get("confidence", 0)
    quant_reasoning = quant_result.get("reasoning", "")
    quant_ema = quant_result.get("ema_analysis", "")
    quant_rsi = quant_result.get("rsi_analysis", "")
    quant_vol = quant_result.get("volume_analysis", "")
    quant_4h = quant_result.get("trend_4h", "")
    quant_levels = quant_result.get("key_levels", {})

    sent_score = sentiment_result.get("score", 50)
    sent_label = sentiment_result.get("label", "Neutral")
    sent_tone = sentiment_result.get("reddit_tone", "neutral")
    sent_fg = sentiment_result.get("fear_greed_index", "N/A")
    sent_themes = sentiment_result.get("key_themes", [])
    sent_reasoning = sentiment_result.get("reasoning", "")

    user_content = f"""SYNTHESIS REQUEST — ETH/USDT Trade Decision

=== QUANT AGENT OUTPUT ===
Signal: {quant_signal} (confidence: {quant_conf}/100)
4H Trend: {quant_4h}
EMA Analysis: {quant_ema}
RSI Analysis: {quant_rsi}
Volume: {quant_vol}
Key Levels — Support: ${quant_levels.get('support', 0):,.0f} | Resistance: ${quant_levels.get('resistance', 0):,.0f}
Reasoning: {quant_reasoning}

=== SENTIMENT AGENT OUTPUT ===
Score: {sent_score}/100 ({sent_label})
Reddit Tone: {sent_tone}
Fear & Greed Index: {sent_fg}
Key Themes: {', '.join(sent_themes) if sent_themes else 'none'}
Reasoning: {sent_reasoning}
"""

    if reflect_context and reflect_context != "No trade history available yet. Operate with default strategy parameters.":
        user_content += f"\n=== REFLECT AGENT CONTEXT ===\n{reflect_context}\n"

    user_content += "\nMake the final trade decision and return your JSON response."

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
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        logger.info(
            f"Decision: {result.get('decision')} | Confidence: {result.get('confidence')} | "
            f"Entry allowed: {result.get('entry_allowed')}"
        )
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Decisor agent JSON parse error: {e}")
        return {
            "decision": "NEUTRAL",
            "confidence": 0,
            "justification": "Parse error in decisor agent",
            "entry_allowed": False,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Decisor agent error: {e}")
        return {
            "decision": "NEUTRAL",
            "confidence": 0,
            "justification": f"Decisor agent error: {e}",
            "entry_allowed": False,
        }
