# Agente Crypto — Histórico de Desenvolvimento

**Data:** 2026-05-01 | **Status:** Paper Trading Ativo (hourly, fase de validação) → WebSocket em implementação

---

## 📋 Visão Geral do Projeto

**Objetivo:** Bot autônomo de trading ETH/USDT 3x leverage em Binance Futures com 4 agentes Claude (Haiku 4.5) para decisões inteligentes.

**Arquitetura de 3 Etapas:**
1. ✅ **Etapa 1 (Backtest)** — Engine vectorizado NumPy (50-100x mais rápido que pandas)
2. ✅ **Etapa 2 (Paper Trading)** — Simula operações com preços reais
3. 🔄 **Etapa 3 (Live Trading)** — Execução real (testnet → live depois)

---

## 🎯 Estratégia de Trading

### Timeframe
- **Entrada:** 1H (EMA21/50/200, RSI14)
- **Confirmação:** 4H (trend bullish/bearish)
- **Saída:** Real-time (SL, TP1, trailing stop)

### Parâmetros Otimizados (via Random Search 1000 samples)

| Parâmetro | Valor | Impacto |
|-----------|-------|--------|
| EMA_FAST | 21 | Crossover rápido |
| EMA_MID | 50 | Suporte/resistência |
| EMA_SLOW | 200 | Tendência geral |
| LONG_RSI_MIN | 45 | Zone válida para entrada |
| LONG_RSI_MAX | 75 | Evita overbought extremo |
| SHORT_RSI_MIN | 25 | Zone válida SHORT |
| SHORT_RSI_MAX | 55 | Evita oversold extremo |
| **TP1_RATIO** | **2.5x risk** | +171% de retorno vs 1.5x ⭐ |
| TP1_SIZE | 50% | Partial close, deixa trailing |
| STOP_LOSS_BUFFER | 1% | Distância do EMA_MID |
| RISK_PER_TRADE | 2% | Risco por operação |
| LEVERAGE | 3x | Capital efetivo = 1500 USDT |
| USE_TRAILING_STOP | true | EMA21 como trailing |
| STARTING_CAPITAL | 500 USDT | |

### Lógica de Entrada

```
LONG se:
  ✓ EMA_fast > EMA_mid (crossover)
  ✓ EMA_mid > EMA_slow (bullish stack)
  ✓ RSI em [45-75] (safe zone)
  ✓ 4H trend = BULLISH (confirmação)
  ✓ Volume > MA 20D (força)
  → Decisor aprova (confidence ≥60%)

SHORT = inverso, com RSI [25-55]

NEUTRAL se:
  - Volume fraco (não confirma)
  - RSI overbought/oversold extremo
  - Sentiment extremo (Fear ≤15 ou Greed ≥85 sem quorum)
```

### Lógica de Saída

1. **Stop Loss** → preço ≤ SL (calculado: EMA_mid × (1 - 1%))
2. **TP1 Partial Close** → preço ≥ entry + 2.5x×risk → fecha 50%, leave 50% em trailing
3. **Trailing Stop** → preço cruza EMA21 (ambos os lados)

---

## 4️⃣ Agentes Claude (Haiku 4.5 com Prompt Caching)

### 1. **Reflect Agent**
- Lê histórico de trades (wins/losses)
- Identifica padrões (perdeu sem volume? ganhou com bullish 4H?)
- Ajusta bias (conservative/normal/aggressive)
- Cache: 4h TTL em `reflect_memory.json`
- Custo: ~$0.20/mês (chamado 1x/dia)

### 2. **Quant Agent**
- Analisa EMAs, RSI, volume, tendência 4H
- Retorna: BULLISH/BEARISH/NEUTRAL com confidence 0-100
- Cache: ephemeral (reutilizado em análises rápidas)
- Custo: ~$5/mês (24 chamadas/dia)

### 3. **Sentiment Agent**
- Fear & Greed Index (api.alternative.me/fng)
- Reddit tone (r/ethtrader, r/CryptoCurrency)
- Score 0-100 + label (Fear/Greed/Neutral)
- Custo: ~$5/mês

### 4. **Decisor Agent**
- Recebe output dos 3 anteriores
- Faz final decision: LONG / SHORT / NEUTRAL
- Regras: contrarian em Extreme Fear (≤15), override em Extreme Greed (≥85)
- Custo: ~$5/mês

**Total:** ~$15-20/mês (prompt caching + batch) ✅

---

## 📊 Backtest → Otimização

### Processo
1. **Backtest vetorizado** (NumPy): 154ms por run
2. **Random Search** 1000 samples (seed=42): 162s total
3. **Grid explorado:** EMA_FAST, EMA_MID, EMA_SLOW, RSI ranges, TP1_RATIO, etc.

### Descoberta Crítica
```
Baseline (EMA21/50/200, TP1_RATIO=1.5x):
  Return: +40% | Win rate: 54% | Max DD: -15%

Otimizado (mesmo, TP1_RATIO=2.5x):
  Return: +211% | Win rate: 54% | Max DD: -18%
  → +171% incremental (risk/reward melhor)
```

---

## 🚀 Paper Trading — Status Atual

### Arquivos Críticos

```
bot.py                 ← Orquestrador hourly (loop infinito)
orchestrator.py        ← Coordena 4 agentes + log de sinais
paper_trader.py        ← Simula posições (state em JSON)
real_trader.py         ← Executa ordens reais (ccxt binanceusdm)
websocket_monitor.py   ← Monitora SL/TP em real-time (NOVO)
exchange.py            ← Binance Futures connector
agents/                ← Quant, Sentiment, Reflect, Decisor
app.py                 ← Flask dashboard (auth básica)
```

### Status Hoje

- **Rodando:** Paper mode em VPS (Coolify)
- **Ciclo:** Hourly (analisa a cada 1H)
- **Trades:** 1 trade finalizado (loss $3.27 = -0.65%, mas identificou missing volume)
- **Capital:** $496.73 (começou com $500)
- **Dashboard:** Acessível em https://crypto.arlprime.com

### Reflect Learning
Após primeira loss, o Reflect Agent notou:
```
"System recorded 1 loss on ETH/USDT long with bullish 4H setup 
but critically missing volume confirmation (Vol OK: False)"
```
→ Bot agora mais conservador (NEUTRAL em próximas análises sem volume) ✅

---

## 🔌 WebSocket Real-Time — Próximo Passo

### Problema Atual (Hourly)
- Se SL/TP bate intra-hora, bot não percebe
- Exemplo: SL hit às 22:30, bot acorda só às 23:00 (+30min)

### Solução WebSocket
```python
# websocket_monitor.py (implementado)
→ Conecta a wss://stream.binance.com/ws/ethusdt@bookTicker
→ Monitora bid/ask em tempo real
→ Detecta SL/TP em milissegundos
→ Callback executa exit order

# Integration no bot.py
Quando position aberta:
  1. Inicia WebSocket monitor em background
  2. Bot continua hourly (para novos sinais)
  3. WebSocket fecha posição se SL/TP bate
```

### Erros Anteriores + Fixes

**Erro 1:** CCXT estava chamando `sapi/v1/capital/config/getall` (Spot API live)
- **Fix:** Usar `requests` direto em vez de CCXT para testnet
- Já provado: `https://testnet.binancefuture.com/fapi/v2/account` retorna 200 com credenciais ✅

**Erro 2:** Testnet não precisa de Spot API
- **Fix:** Implementar RealTrader com `requests` puro (sem CCXT)
- Signature HMAC-SHA256 já validado

**Próxima Tentativa:**
- Usar `requests` direto em `real_trader.py` e `websocket_monitor.py`
- Skip CCXT para evitar internal spot API calls
- WebSocket via `websockets` library + async

---

## 📈 Métricas para Validação (2-4 semanas)

| Métrica | Target | Status |
|---------|--------|--------|
| Trades acumulados | ~30 | 1/30 |
| Win rate | >50% | Teste |
| Return total | Positivo | -0.65% (ainda cedo) |
| Max drawdown | <-20% do capital | Monitorar |
| API cost | <$25/mês | ~$1 (1 trade) |

---

## 🔑 Credentials Setup (Live)

**Testnet (current):**
```
BINANCE_TESTNET=true
TRADING_MODE=paper
BINANCE_API_KEY=DJ2BeyUbeG7o1c1FUvAHUIt3VMwNn4KOTTWl3WjoMcguoxcJ5JbTE76iiACORPiy
BINANCE_API_SECRET=3ep0NMHwc0VUeVqPADBGyBkrf4Z2BVVvNaIVAP4jgnasU8gHB5tslv7R48Qcazvn
```

**Live (quando pronto):**
```
TRADING_MODE=live
BINANCE_TESTNET=false
BINANCE_API_KEY=<real_key_from_binance.com>
BINANCE_API_SECRET=<real_secret>
```

---

## 📚 Estrutura de Decisão (4 Agentes)

```
Bot Loop (hourly)
│
├─ [1] Reflect Agent
│  └─ "Aprender com trades anteriores?"
│     └─ Bias: aggressive/normal/conservative
│
├─ [2] Market State
│  └─ "Qual é o cenário agora?"
│     └─ Price, EMAs, RSI, 4H trend, volume
│
├─ [3] Quant Agent
│  └─ "É bullish/bearish tecnicamente?"
│     └─ BULLISH/BEARISH/NEUTRAL (confidence)
│
├─ [4] Sentiment Agent
│  └─ "Qual é o sentimento geral?"
│     └─ Fear/Greed, Reddit tone
│
└─ [5] Decisor Agent
   └─ "Entra ou não?" (com regras contrarian)
      └─ LONG/SHORT/NEUTRAL + entry_allowed (bool)
```

---

## 🎓 Lessons Learned

1. **CCXT + Testnet = complexo** (spot API interference)
   → Solução: `requests` direto

2. **Hourly candles não são suficientes para SL/TP**
   → Solução: WebSocket real-time

3. **Reflect learning funciona** (bot se adaptou após primeira loss)
   → Validação: Agente identificou falta de volume

4. **Prompt caching é crítico** (cost $15-20/mês vs $100+/mês sem cache)
   → Implementado com ephemeral + TTL caches

5. **Paper trading valida tudo exceto latência/slippage**
   → Necessário para live: testar com WebSocket real-time

---

## 📝 Próximas Prioridades

1. **WebSocket real-time** (com `requests` direto)
   - Implementar `websocket_monitor.py` com async
   - Testar em testnet
   - Integrar no bot.py

2. **Validação 2-4 semanas**
   - Deixar rodar ~30 trades
   - Monitorar win rate, return, drawdown

3. **Live Mode Setup**
   - Gerar API keys reais em binance.com
   - Começar com $50-100 (not all capital)
   - Monitor rigorosamente

4. **Melhorias futuras**
   - Multi-pair support (BTC/USDT, etc)
   - Daily max drawdown limiter
   - Auto re-otimização via Reflect + backtest

---

**Última atualização:** 2026-05-01 21:53 UTC  
**Próximo checkpoint:** +1 semana (monitorar trades, validar win rate)
