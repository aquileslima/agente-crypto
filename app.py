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
import time
import logging
import threading
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
_bot_was_started = False  # True após qualquer start (manual ou automático via watchdog)

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


def _start_bot_process():
    """Inicia o subprocess bot.py e registra o PID."""
    global _bot_process, _bot_was_started
    os.makedirs("trades", exist_ok=True)
    log_file = open("trades/bot.log", "a", encoding="utf-8")
    _bot_process = subprocess.Popen(
        [sys.executable, "bot.py"],
        stdout=log_file,
        stderr=log_file,
    )
    _save_pid(_bot_process.pid)
    _bot_was_started = True
    app.logger.info(f"Bot process started (PID {_bot_process.pid})")
    return _bot_process


def _bot_watchdog():
    """
    Thread de vigilância: auto-inicia e reinicia o bot se morrer.

    Lógica de auto-start:
    - Se TRADING_MODE estiver definido (ambiente de produção/Coolify),
      o bot é iniciado SEMPRE ao subir o container, sem depender de
      arquivos no volume (que podem não persistir entre deploys).
    - Após iniciado, verifica a cada 60s e reinicia em caso de crash.
    - Stop manual via dashboard seta _bot_was_started=False, impedindo
      restart automático até o próximo deploy do container.
    """
    import time
    time.sleep(10)  # Aguarda Flask iniciar completamente

    # Auto-start em produção:
    # Condição 1: TRADING_MODE definido no ambiente (Coolify/VPS)
    # Condição 2: PID file existe no volume (bot estava rodando antes do restart)
    # Ambas indicam que o bot deve rodar; só NÃO iniciamos em dev local sem essas condições
    mode_set = bool(os.getenv("TRADING_MODE"))
    pid_exists = os.path.exists(_BOT_PID_FILE)
    app.logger.info(
        f"Watchdog: TRADING_MODE={'set' if mode_set else 'NOT SET'} | "
        f"PID file={'exists' if pid_exists else 'absent'}"
    )
    if (mode_set or pid_exists) and not _is_bot_running():
        try:
            mode = os.getenv("TRADING_MODE", "paper").upper()
            app.logger.info(f"Watchdog: auto-iniciando bot (TRADING_MODE={mode}, pid_file={pid_exists})...")
            _start_bot_process()
        except Exception as e:
            app.logger.error(f"Watchdog auto-start falhou: {e}")

    while True:
        time.sleep(60)  # Verifica a cada 60 segundos
        try:
            if _bot_was_started and not _is_bot_running():
                app.logger.warning("Watchdog: bot morreu inesperadamente — reiniciando...")
                _start_bot_process()
        except Exception as e:
            app.logger.error(f"Watchdog restart falhou: {e}")


# Inicia watchdog em background (daemon=True → morre junto com Flask)
threading.Thread(target=_bot_watchdog, daemon=True, name="bot-watchdog").start()


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
    if _is_bot_running():
        return jsonify({"ok": False, "message": "Bot já está rodando."})
    try:
        proc = _start_bot_process()
        return jsonify({"ok": True, "pid": proc.pid,
                        "message": f"Bot iniciado (PID {proc.pid})"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/bot/stop", methods=["POST"])
@_require_auth
def api_bot_stop():
    global _bot_process, _bot_was_started
    if not _is_bot_running():
        return jsonify({"ok": False, "message": "Bot não está rodando."})
    try:
        # Case 1: processo em memória (iniciado nesta sessão Flask)
        if _bot_process is not None:
            _bot_process.terminate()
            try:
                _bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _bot_process.kill()
        else:
            # Case 2: processo detectado via PID file (sessão anterior / container restart)
            if os.path.exists(_BOT_PID_FILE):
                try:
                    pid = int(open(_BOT_PID_FILE).read().strip())
                    os.kill(pid, 15)   # SIGTERM
                    time.sleep(2)
                    if _pid_alive(pid):
                        os.kill(pid, 9)  # SIGKILL forçado
                except Exception as ke:
                    app.logger.warning(f"Kill via PID falhou: {ke}")
        _bot_process = None
        _bot_was_started = False  # Watchdog NÃO reinicia após stop manual
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


@app.route("/api/analyses")
@_require_auth
def api_analyses():
    """Retorna os últimos 10 ciclos onde não houve entrada (entry_allowed=false)."""
    signals = _read_json("trades/signals_log.json") or []
    no_entry = [s for s in signals if not s.get("entry_allowed", False)]
    return jsonify(list(reversed(no_entry[-10:])))  # últimas 10, mais recentes primeiro


@app.route("/api/ohlcv")
@_require_auth
def api_ohlcv():
    """Retorna últimos 200 candles 1H com indicadores para o gráfico de preço."""
    try:
        import pandas as pd
        from backtest import add_indicators, DEFAULT_PARAMS
        from config import SYMBOL, TIMEFRAME_ENTRY

        safe_sym = SYMBOL.replace("/", "")
        cache_file = os.path.join("data_cache", f"{safe_sym}_{TIMEFRAME_ENTRY}_0.5y.pkl")

        if not os.path.exists(cache_file):
            return jsonify({"candles": [], "position": None, "trades": [],
                            "message": "Cache ainda não disponível. Aguarde o primeiro ciclo do bot."})

        df = pd.read_pickle(cache_file)
        df = add_indicators(df, DEFAULT_PARAMS)
        df = df.dropna(subset=["ema_fast", "ema_mid", "ema_slow", "rsi"]).tail(200)

        candles = []
        for ts, row in df.iterrows():
            ts_int = int(ts.timestamp())
            candles.append({
                "time":     ts_int,
                "open":     round(float(row["open"]),  2),
                "high":     round(float(row["high"]),  2),
                "low":      round(float(row["low"]),   2),
                "close":    round(float(row["close"]), 2),
                "ema_fast": round(float(row["ema_fast"]), 2),
                "ema_mid":  round(float(row["ema_mid"]),  2),
                "ema_slow": round(float(row["ema_slow"]), 2),
                "rsi":      round(float(row["rsi"]),      2),
            })

        # Posição atual
        state = _paper_state()
        position = state.get("position")

        # Últimos 20 trades fechados para marcadores de entrada/saída
        trades = _read_json("trades/trade_history.json") or []
        trades = trades[-20:]

        return jsonify({"candles": candles, "position": position, "trades": trades})
    except Exception as e:
        app.logger.error(f"OHLCV endpoint error: {e}")
        return jsonify({"candles": [], "position": None, "trades": [], "error": str(e)})


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
