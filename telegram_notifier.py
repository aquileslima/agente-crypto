"""
Telegram Notifier — sends trade signals and status updates via Telegram Bot API.
Uses plain HTTP requests (no async) for simplicity.
"""
import os
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_BASE_URL = f"https://api.telegram.org/bot{_BOT_TOKEN}"


def _send(text: str) -> bool:
    if not _BOT_TOKEN or not _CHAT_ID:
        logger.warning("Telegram not configured — skipping notification.")
        return False
    try:
        r = requests.post(
            f"{_BASE_URL}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def send_signal(report: dict) -> None:
    ms = report["market_state"]
    decision = report["decision"]
    confidence = report["confidence"]
    entry = report["entry_allowed"]

    arrow = "🟢 <b>LONG</b>" if decision == "LONG" else "🔴 <b>SHORT</b>" if decision == "SHORT" else "⚪ <b>NEUTRAL</b>"
    entry_str = "✅ ENTRADA PERMITIDA" if entry else "🚫 Sem entrada"

    msg = (
        f"📊 <b>ETH/USDT — Sinal {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC</b>\n"
        f"\n"
        f"Decisão: {arrow}\n"
        f"Confiança: {confidence}%\n"
        f"{entry_str}\n"
        f"\n"
        f"💰 Preço: <code>${ms['price']:,.2f}</code>\n"
        f"📈 EMA Fast/Mid/Slow: {ms['ema_fast']:,.0f} / {ms['ema_mid']:,.0f} / {ms['ema_slow']:,.0f}\n"
        f"📉 RSI: {ms['rsi']:.1f}\n"
        f"🔊 Volume OK: {'Sim' if ms['volume_above_avg'] else 'Não'}\n"
        f"📡 Tendência 4H: {'🐂 Alta' if ms['trend_4h_bullish'] else '🐻 Baixa'}\n"
        f"\n"
        f"🤖 Quant: {report['quant_result'].get('signal')} ({report['quant_result'].get('confidence')}%)\n"
        f"😶 Sentimento: {report['sentiment_result'].get('score')}/100 ({report['sentiment_result'].get('label')})\n"
        f"\n"
        f"📝 {report['justification']}"
    )
    _send(msg)


def send_trade_opened(position: dict, capital: float) -> None:
    direction = position["direction"]
    arrow = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    msg = (
        f"🚀 <b>TRADE ABERTO — {arrow}</b>\n"
        f"\n"
        f"💰 Entrada: <code>${position['entry_price']:,.2f}</code>\n"
        f"🛑 Stop Loss: <code>${position['stop_price']:,.2f}</code>\n"
        f"🎯 TP1: <code>${position['tp1_price']:,.2f}</code>\n"
        f"📦 Tamanho: {position['original_size']:.4f} ETH\n"
        f"💵 Capital: <code>${capital:,.2f}</code>\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
    )
    _send(msg)


def send_trade_closed(trade: dict, capital: float) -> None:
    pnl = trade.get("pnl", 0)
    pnl_emoji = "💚" if pnl > 0 else "❤️"
    reason = trade.get("reason", "?")
    msg = (
        f"{pnl_emoji} <b>TRADE FECHADO — {reason}</b>\n"
        f"\n"
        f"Direção: {trade.get('direction')}\n"
        f"💰 Entrada: <code>${trade.get('entry_price', 0):,.2f}</code>\n"
        f"💰 Saída:   <code>${trade.get('exit_price', 0):,.2f}</code>\n"
        f"📊 PnL: <b>${pnl:+,.2f}</b>\n"
        f"⏱ Duração: {trade.get('duration_h', 0):.1f}h\n"
        f"💵 Capital atual: <code>${capital:,.2f}</code>\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
    )
    _send(msg)


def send_position_update(position: dict, current_price: float, capital: float) -> None:
    direction = position["direction"]
    entry = position["entry_price"]
    pnl_open = (current_price - entry) * position["current_size"] if direction == "LONG" \
               else (entry - current_price) * position["current_size"]
    pnl_open += position.get("tp1_profit", 0)
    tp1_status = "✅ Atingido" if position["tp1_hit"] else "⏳ Pendente"
    msg = (
        f"📍 <b>Posição Aberta — {direction}</b>\n"
        f"Entrada: <code>${entry:,.2f}</code> → Atual: <code>${current_price:,.2f}</code>\n"
        f"PnL aberto: <b>${pnl_open:+,.2f}</b>\n"
        f"TP1: {tp1_status}\n"
        f"Stop: <code>${position['stop_price']:,.2f}</code>\n"
        f"Capital: <code>${capital:,.2f}</code>"
    )
    _send(msg)


def send_error(error: str) -> None:
    _send(f"⚠️ <b>Bot Error</b>\n<code>{error[:500]}</code>")


def send_startup(mode: str, capital: float) -> None:
    _send(
        f"🤖 <b>Agente Crypto iniciado</b>\n"
        f"Modo: <b>{mode.upper()}</b>\n"
        f"Capital: <code>${capital:,.2f}</code>\n"
        f"Par: ETH/USDT Futuros 3x\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
    )
