"""
Reflect Agent — learns from past trade history, persists insights to JSON,
and provides learning context to other agents.
"""
import json
import logging
import os
from datetime import datetime, timezone
from agents.base_agent import get_client, MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)

TRADE_HISTORY_PATH = "trades/trade_history.json"
REFLECT_MEMORY_PATH = "trades/reflect_memory.json"

_SYSTEM_PROMPT = """You are a trading performance analyst for an ETH/USDT futures strategy.

Your role: analyze recent trade history to identify patterns, extract lessons, and provide
actionable guidance for the next trade decision.

ANALYSIS FOCUS:
1. What market conditions led to winning trades? (EMA alignment, RSI zone, volume, 4H trend)
2. What conditions preceded losing trades?
3. Are there recurring entry/exit timing issues?
4. What is the current momentum (win/loss streak)?
5. Should the system be more aggressive or more conservative right now?

Respond ONLY with valid JSON — no markdown, no extra text.

OUTPUT FORMAT:
{
  "insights": ["<actionable lesson 1>", "<actionable lesson 2>", "<lesson 3>"],
  "win_conditions": ["<condition that preceded wins>"],
  "loss_conditions": ["<condition that preceded losses>"],
  "current_streak": {"type": "win" | "loss" | "none", "count": <integer>},
  "bias": "aggressive" | "normal" | "conservative",
  "context_summary": "<2-3 sentence summary to inject into other agents>"
}"""


def _load_json(path: str) -> list | dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return None


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _compute_streak(trades: list) -> dict:
    if not trades:
        return {"type": "none", "count": 0}
    recent = sorted(trades, key=lambda t: t.get("exit_time", ""), reverse=True)
    first_type = "win" if recent[0].get("pnl", 0) > 0 else "loss"
    count = 0
    for t in recent:
        is_win = t.get("pnl", 0) > 0
        if (first_type == "win" and is_win) or (first_type == "loss" and not is_win):
            count += 1
        else:
            break
    return {"type": first_type, "count": count}


def _summarize_trades_for_prompt(trades: list) -> str:
    if not trades:
        return "No trades recorded yet."
    recent = sorted(trades, key=lambda t: t.get("exit_time", ""), reverse=True)[:20]
    wins = [t for t in recent if t.get("pnl", 0) > 0]
    losses = [t for t in recent if t.get("pnl", 0) <= 0]
    total_pnl = sum(t.get("pnl", 0) for t in recent)
    win_rate = len(wins) / len(recent) * 100 if recent else 0

    lines = [
        f"Last {len(recent)} trades: {len(wins)} wins / {len(losses)} losses | Win rate: {win_rate:.1f}% | Net PnL: ${total_pnl:+.2f}",
        "",
        "Recent trades (newest first):",
    ]
    for t in recent[:10]:
        pnl = t.get("pnl", 0)
        direction = t.get("direction", "?")
        reason = t.get("exit_reason", "?")
        entry = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        rsi = t.get("rsi_at_entry", "?")
        vol_ok = t.get("volume_above_avg", "?")
        trend = t.get("trend_4h", "?")
        lines.append(
            f"  {direction} | Entry ${entry:,.0f} → Exit ${exit_p:,.0f} | PnL ${pnl:+.2f} | "
            f"Reason: {reason} | RSI: {rsi} | Vol OK: {vol_ok} | 4H: {trend}"
        )
    return "\n".join(lines)


def analyze_and_update(force_refresh: bool = False) -> str:
    """
    Load trade history, analyze with Claude, update reflect_memory.json,
    and return a context string to inject into other agents.

    Returns:
        str: context_summary for injection into quant/decisor prompts
    """
    trades = _load_json(TRADE_HISTORY_PATH) or []
    memory = _load_json(REFLECT_MEMORY_PATH) or {}

    # Use cached memory if fresh (< 4 hours old) and not forced
    if not force_refresh and memory:
        last_updated = memory.get("last_updated", "")
        if last_updated:
            try:
                age_h = (
                    datetime.now(timezone.utc) -
                    datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                ).total_seconds() / 3600
                if age_h < 4:
                    logger.info(f"Using cached reflect memory ({age_h:.1f}h old)")
                    return memory.get("context_summary", "No prior insights available.")
            except Exception:
                pass

    if not trades:
        logger.info("No trade history found — skipping reflect analysis.")
        return "No trade history available yet. Operate with default strategy parameters."

    streak = _compute_streak(trades)
    trades_summary = _summarize_trades_for_prompt(trades)
    client = get_client()

    user_content = f"""TRADE HISTORY ANALYSIS REQUEST

{trades_summary}

Current streak: {streak['count']} consecutive {streak['type']}s

Please analyze these results and extract lessons for the trading system."""

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

        # Persist to reflect_memory.json
        result["last_updated"] = datetime.now(timezone.utc).isoformat()
        result["trade_count"] = len(trades)
        _save_json(REFLECT_MEMORY_PATH, result)

        context = result.get("context_summary", "")
        logger.info(f"Reflect agent updated memory. Bias: {result.get('bias')}")
        return context

    except json.JSONDecodeError as e:
        logger.error(f"Reflect agent JSON parse error: {e}")
        return "Reflect analysis failed — operating with default parameters."
    except Exception as e:
        logger.error(f"Reflect agent error: {e}")
        return "Reflect analysis unavailable."


def save_trade(trade: dict) -> None:
    """
    Append a completed trade to trade_history.json.
    Call this after every closed position (live or paper mode).
    """
    trades = _load_json(TRADE_HISTORY_PATH) or []
    trade["recorded_at"] = datetime.now(timezone.utc).isoformat()
    trades.append(trade)
    _save_json(TRADE_HISTORY_PATH, trades)
    logger.info(f"Trade saved. Total history: {len(trades)} trades.")
