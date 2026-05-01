"""
Dashboard Flask — web interface for the ETH/USDT trading agent.
Run: python app.py
Then open http://localhost:5000
"""
import json
import os
import re
import subprocess
import sys
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response
from functools import wraps

load_dotenv(override=True)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ── HTTP Basic Auth ───────────────────────────────────────────────────────────
_DASH_USER = os.getenv("DASHBOARD_USER", "admin")
_DASH_PASS = os.getenv("DASHBOARD_PASS", "crypto123")

def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != _DASH_USER or auth.password != _DASH_PASS:
            return Response(
                "Acesso negado. Informe usuário e senha.",
                401,
                {"WWW-Authenticate": 'Basic realm="Agente Crypto"'},
            )
        return f(*args, **kwargs)
    return decorated

# ── Bot process tracking ──────────────────────────────────────────────────────
_bot_process: subprocess.Popen | None = None
_BOT_PID_FILE = "trades/bot.pid"

def _save_pid(pid: int) -> None:
    os.makedirs("trades", exist_ok=True)
    with open(_BOT_PID_FILE, "w") as f:
        f.write(str(pid))

def _clear_pid() -> None:
    if os.path.exists(_BOT_PID_FILE):
        os.remove(_BOT_PID_FILE)

def _pid_alive(pid: int) -> bool:
    """Check if a PID is running (Linux/Mac). Falls back gracefully on Windows."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _paper_state() -> dict:
    return _read_json("trades/paper_state.json") or {
        "capital": 500.0, "initial_capital": 500.0,
        "position": None, "total_trades": 0,
        "winning_trades": 0, "total_pnl": 0.0,
    }


def _read_config() -> dict:
    try:
        import importlib
        import config as cfg
        importlib.reload(cfg)
        return {
            "EMA_FAST":           cfg.EMA_FAST,
            "EMA_MID":            cfg.EMA_MID,
            "EMA_SLOW":           cfg.EMA_SLOW,
            "LONG_RSI_MIN":       cfg.LONG_RSI_MIN,
            "LONG_RSI_MAX":       cfg.LONG_RSI_MAX,
            "SHORT_RSI_MIN":      cfg.SHORT_RSI_MIN,
            "SHORT_RSI_MAX":      cfg.SHORT_RSI_MAX,
            "TP1_RATIO":          cfg.TP1_RATIO,
            "TP1_SIZE":           cfg.TP1_SIZE,
            "STOP_LOSS_BUFFER":   cfg.STOP_LOSS_BUFFER,
            "RISK_PER_TRADE":     cfg.RISK_PER_TRADE,
            "LEVERAGE":           cfg.LEVERAGE,
            "USE_TRAILING_STOP":  cfg.USE_TRAILING_STOP,
            "STARTING_CAPITAL":   cfg.STARTING_CAPITAL,
        }
    except Exception as e:
        app.logger.error(f"Config read error: {e}")
        return {}


def _update_config_value(key: str, value) -> None:
    with open("config.py", "r", encoding="utf-8") as f:
        content = f.read()

    if isinstance(value, bool):
        val_str = str(value)
    elif isinstance(value, float):
        val_str = str(value)
    else:
        val_str = str(value)

    # Preserve inline comments
    def replacer(m):
        comment = f"  {m.group(2)}" if m.group(2) else ""
        return f"{key} = {val_str}{comment}"

    content = re.sub(
        rf"^{key}\s*=\s*[^\n#]*(#[^\n]*)?",
        replacer,
        content,
        flags=re.MULTILINE,
    )
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(content)


def _is_bot_running() -> bool:
    global _bot_process
    # 1. Check in-memory reference first
    if _bot_process is not None and _bot_process.poll() is None:
        return True
    # 2. Fall back to PID file (survives dashboard restarts)
    if os.path.exists(_BOT_PID_FILE):
        try:
            pid = int(open(_BOT_PID_FILE).read().strip())
            if _pid_alive(pid):
                return True
        except Exception:
            pass
        _clear_pid()
    return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
@_require_auth
def index():
    return render_template("index.html")


@app.route("/api/status")
@_require_auth
def api_status():
    state = _paper_state()
    signals = _read_json("trades/signals_log.json") or []
    last = signals[-1] if signals else None

    capital = state["capital"]
    initial = state["initial_capital"]
    ret_pct = (capital - initial) / initial * 100 if initial else 0
    n = state["total_trades"]
    wins = state.get("winning_trades", 0)

    return jsonify({
        "bot_running":      _is_bot_running(),
        "mode":             os.getenv("TRADING_MODE", "paper").upper(),
        "capital":          round(capital, 2),
        "initial_capital":  round(initial, 2),
        "return_pct":       round(ret_pct, 2),
        "total_pnl":        round(state["total_pnl"], 2),
        "total_trades":     n,
        "win_rate":         round(wins / n * 100, 1) if n else 0,
        "has_position":     state["position"] is not None,
        "position":         state["position"],
        "last_decision":    last["decision"] if last else "—",
        "last_signal_time": last["timestamp"] if last else None,
    })


@app.route("/api/signal")
@_require_auth
def api_signal():
    signals = _read_json("trades/signals_log.json") or []
    if not signals:
        return jsonify(None)
    last = signals[-1]
    ms = last.get("market_state", {})
    qr = last.get("quant_result", {})
    sr = last.get("sentiment_result", {})
    return jsonify({
        "timestamp":        last.get("timestamp"),
        "decision":         last.get("decision", "N/A"),
        "confidence":       last.get("confidence", 0),
        "entry_allowed":    last.get("entry_allowed", False),
        "justification":    last.get("justification", ""),
        "risk_note":        last.get("risk_note", ""),
        "price":            ms.get("price", 0),
        "rsi":              ms.get("rsi", 0),
        "ema_fast":         ms.get("ema_fast", 0),
        "ema_mid":          ms.get("ema_mid", 0),
        "ema_slow":         ms.get("ema_slow", 0),
        "trend_4h":         "BULLISH" if ms.get("trend_4h_bullish") else "BEARISH",
        "volume_ok":        ms.get("volume_above_avg", False),
        "quant_signal":     qr.get("signal", "N/A"),
        "quant_confidence": qr.get("confidence", 0),
        "sentiment_score":  sr.get("score", 50),
        "sentiment_label":  sr.get("label", "Neutral"),
        "reddit_tone":      sr.get("reddit_tone", "neutral"),
    })


@app.route("/api/trades")
@_require_auth
def api_trades():
    history = _read_json("trades/trade_history.json") or []
    return jsonify(list(reversed(history[-50:])))


@app.route("/api/equity")
@_require_auth
def api_equity():
    state = _paper_state()
    history = _read_json("trades/trade_history.json") or []
    initial = state["initial_capital"]

    labels = ["Início"]
    values = [initial]
    running = initial
    for t in history:
        running += t.get("pnl", 0)
        ts = t.get("exit_time", "")[:16].replace("T", " ")
        labels.append(ts)
        values.append(round(running, 2))

    return jsonify({"labels": labels, "values": values})


@app.route("/api/config", methods=["GET", "POST"])
@_require_auth
def api_config():
    if request.method == "GET":
        return jsonify(_read_config())

    data = request.get_json()
    errors = []
    type_map = {
        "EMA_FAST": int, "EMA_MID": int, "EMA_SLOW": int,
        "LONG_RSI_MIN": int, "LONG_RSI_MAX": int,
        "SHORT_RSI_MIN": int, "SHORT_RSI_MAX": int,
        "LEVERAGE": int,
        "TP1_RATIO": float, "TP1_SIZE": float,
        "STOP_LOSS_BUFFER": float, "RISK_PER_TRADE": float,
        "STARTING_CAPITAL": float,
        "USE_TRAILING_STOP": bool,
    }
    for key, value in data.items():
        try:
            cast = type_map.get(key, str)
            if cast == bool:
                typed = bool(value)
            else:
                typed = cast(value)
            _update_config_value(key, typed)
        except Exception as e:
            errors.append(f"{key}: {e}")

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    return jsonify({"ok": True, "message": "Configurações salvas. Reinicie o bot para aplicar."})


@app.route("/api/bot/start", methods=["POST"])
@_require_auth
def api_bot_start():
    global _bot_process
    if _is_bot_running():
        return jsonify({"ok": False, "message": "Bot já está rodando."})
    try:
        os.makedirs("trades", exist_ok=True)
        log_file = open("trades/bot.log", "a", encoding="utf-8")
        _bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=log_file,
            stderr=log_file,
        )
        _save_pid(_bot_process.pid)
        return jsonify({"ok": True, "pid": _bot_process.pid,
                        "message": f"Bot iniciado (PID {_bot_process.pid})"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/bot/stop", methods=["POST"])
@_require_auth
def api_bot_stop():
    global _bot_process
    if not _is_bot_running():
        return jsonify({"ok": False, "message": "Bot não está rodando."})
    try:
        _bot_process.terminate()
        _bot_process.wait(timeout=5)
        _bot_process = None
        _clear_pid()
        return jsonify({"ok": True, "message": "Bot parado com sucesso."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/bot/run-once", methods=["POST"])
@_require_auth
def api_bot_run_once():
    try:
        result = subprocess.run(
            [sys.executable, "bot.py", "--once"],
            capture_output=True, text=True, timeout=180,
        )
        return jsonify({"ok": True, "output": result.stdout[-3000:] + result.stderr[-1000:]})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "Timeout após 3 minutos."}), 500
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/logs")
@_require_auth
def api_logs():
    path = "trades/bot.log"
    if not os.path.exists(path):
        return jsonify([])
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return jsonify([l.rstrip() for l in lines[-80:]])
    except Exception as e:
        return jsonify([f"Erro ao ler log: {e}"])


if __name__ == "__main__":
    print("=" * 50)
    print("  Agente Crypto — Dashboard")
    print("  http://localhost:5000")
    print(f"  Usuário: {_DASH_USER}")
    print("=" * 50)
    app.run(debug=False, port=5000, host="0.0.0.0", threaded=True)
