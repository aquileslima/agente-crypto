"""
Orchestrator — coordinates all 4 agents to produce a final trade signal.

Flow:
  1. Reflect Agent  → learning context from past trades (cached 4h)
  2. Market State   → current indicators snapshot
  3. Quant Agent    → technical analysis (uses market state + reflect context)
  4. Sentiment Agent→ Reddit + Fear & Greed (uses reflect context)
  5. Decisor Agent  → final LONG/SHORT/NEUTRAL decision
  6. Return & log full analysis report
"""
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from market_state import get_current_market_state
from agents import reflect_agent, quant_agent, sentiment_agent, decisor_agent
from config import SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND

SIGNALS_LOG_PATH = "trades/signals_log.json"


def _log_signal(signal_record: dict) -> None:
    os.makedirs("trades", exist_ok=True)
    history = []
    if os.path.exists(SIGNALS_LOG_PATH):
        try:
            with open(SIGNALS_LOG_PATH) as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(signal_record)
    with open(SIGNALS_LOG_PATH, "w") as f:
        json.dump(history, f, indent=2, default=str)


def run_analysis(verbose: bool = True) -> dict:
    """
    Run all agents and return the consolidated trade signal.

    Returns:
        dict with keys:
          - timestamp
          - market_state (price, EMAs, RSI, volume, 4H trend)
          - quant_result
          - sentiment_result
          - reflect_context
          - decision (LONG / SHORT / NEUTRAL)
          - confidence (0-100)
          - justification
          - entry_allowed (bool)
    """
    run_ts = datetime.now(timezone.utc).isoformat()
    logger.info("=" * 60)
    logger.info(f"ORCHESTRATOR RUN — {run_ts}")
    logger.info("=" * 60)

    # ── Step 1: Reflect agent (fast — uses cache if < 4h old) ──────────────
    logger.info("[1/5] Reflect Agent...")
    reflect_context = reflect_agent.analyze_and_update()
    if verbose:
        logger.info(f"  Reflect context: {reflect_context[:120]}...")

    # ── Step 2: Current market state ─────────────────────────────────────────
    logger.info("[2/5] Market State...")
    market_state = get_current_market_state(max_cache_hours=0.1)  # Sempre dados frescos (máx 6 min cache)
    if verbose:
        logger.info(
            f"  Price: ${market_state['price']:,.2f} | "
            f"RSI: {market_state['rsi']:.1f} | "
            f"4H trend: {'BULLISH' if market_state['trend_4h_bullish'] else 'BEARISH'}"
        )

    # ── Step 3: Quant agent ───────────────────────────────────────────────────
    logger.info("[3/5] Quant Agent...")
    quant_result = quant_agent.analyze(market_state, reflect_context)
    if verbose:
        logger.info(
            f"  Quant: {quant_result.get('signal')} "
            f"(confidence {quant_result.get('confidence')}) — "
            f"{quant_result.get('reasoning', '')[:100]}"
        )

    # ── Step 4: Sentiment agent ───────────────────────────────────────────────
    logger.info("[4/5] Sentiment Agent...")
    sentiment_result = sentiment_agent.analyze(reflect_context)
    if verbose:
        logger.info(
            f"  Sentiment: {sentiment_result.get('score')}/100 "
            f"({sentiment_result.get('label')}) | "
            f"Reddit: {sentiment_result.get('reddit_tone')}"
        )

    # ── Step 5: Decisor ───────────────────────────────────────────────────────
    logger.info("[5/5] Decisor Agent...")
    decision_result = decisor_agent.decide(quant_result, sentiment_result, reflect_context)

    # ── Build full report ─────────────────────────────────────────────────────
    report = {
        "timestamp": run_ts,
        "symbol": SYMBOL,
        "market_state": {
            "timestamp": market_state["timestamp"],
            "price": market_state["price"],
            "ema_fast": market_state["ema_fast"],
            "ema_mid": market_state["ema_mid"],
            "ema_slow": market_state["ema_slow"],
            "rsi": market_state["rsi"],
            "volume_above_avg": market_state["volume_above_avg"],
            "ema_cross_up": market_state["ema_cross_up"],
            "ema_cross_down": market_state["ema_cross_down"],
            "trend_4h_bullish": market_state["trend_4h_bullish"],
        },
        "quant_result": quant_result,
        "sentiment_result": sentiment_result,
        "reflect_context": reflect_context,
        "decision": decision_result.get("decision", "NEUTRAL"),
        "confidence": decision_result.get("confidence", 0),
        "justification": decision_result.get("justification", ""),
        "risk_note": decision_result.get("risk_note", ""),
        "entry_allowed": decision_result.get("entry_allowed", False),
    }

    _log_signal(report)

    # ── Print summary ─────────────────────────────────────────────────────────
    _print_summary(report)
    return report


def _print_summary(report: dict) -> None:
    ms = report["market_state"]
    decision = report["decision"]
    confidence = report["confidence"]
    entry = report["entry_allowed"]

    border = "=" * 60
    print(f"\n{border}")
    print(f"  TRADE SIGNAL — {report['symbol']}")
    print(border)
    print(f"  Time:       {report['timestamp']}")
    print(f"  Price:      ${ms['price']:,.2f}")
    print(f"  EMAs:       Fast={ms['ema_fast']:,.0f} | Mid={ms['ema_mid']:,.0f} | Slow={ms['ema_slow']:,.0f}")
    print(f"  RSI:        {ms['rsi']:.1f}")
    print(f"  4H Trend:   {'BULLISH' if ms['trend_4h_bullish'] else 'BEARISH'}")
    print(f"  Volume OK:  {ms['volume_above_avg']}")
    print(f"  Quant:      {report['quant_result'].get('signal')} ({report['quant_result'].get('confidence')}%)")
    print(f"  Sentiment:  {report['sentiment_result'].get('score')}/100 ({report['sentiment_result'].get('label')})")
    print(border)
    arrow = "▲ LONG" if decision == "LONG" else "▼ SHORT" if decision == "SHORT" else "— NEUTRAL"
    print(f"  DECISION:   {arrow}  |  Confidence: {confidence}%  |  Entry: {'YES' if entry else 'NO'}")
    print(f"  Rationale:  {report['justification']}")
    if report.get("risk_note"):
        print(f"  Risk note:  {report['risk_note']}")
    print(f"{border}\n")


if __name__ == "__main__":
    run_analysis()
