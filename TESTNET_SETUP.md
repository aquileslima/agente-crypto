# Binance Testnet Setup & WebSocket Real-Time Monitoring

## Overview
Esta implementação permite:
- ✅ Integração com Binance Testnet (sem risco de dinheiro real)
- ✅ WebSocket real-time para monitoramento de SL/TP (responde em milissegundos, não horas)
- ✅ Migração fácil para Live Mode depois

## Arquivos Adicionados

1. **websocket_monitor.py** — Monitora preço via WebSocket bookTicker
2. **real_trader.py** — Executa ordens reais na Binance (testnet ou live)
3. **websocket_runner.py** — Orquestra monitoramento assíncrono
4. **exchange.py** (atualizado) — Suporte a Testnet + URLs de WebSocket

## Configuração Testnet

### Passo 1: Criar credenciais de Testnet
1. Acesse: https://testnet.binancefuture.com
2. Sign in com sua conta Binance (ou crie uma nova)
3. Vá para: Account > API Management
4. Crie uma nova API Key:
   - Label: "AgenteCrypto-Testnet"
   - Permissions: **Enable Futures (read + trade)**
   - Disable IP restrictions para facilitar (ou whitelist seu VPS IP)
5. Copie:
   - **API Key**
   - **Secret Key**

### Passo 2: Atualizar .env (local + VPS)

Adicione ao seu `.env`:

```bash
BINANCE_API_KEY=<sua_testnet_api_key>
BINANCE_API_SECRET=<sua_testnet_secret>
BINANCE_TESTNET=true
TRADING_MODE=live
```

**Importante:**
- `BINANCE_TESTNET=true` → Usa testnet.binancefuture.com (sem risco)
- `TRADING_MODE=live` → Ativa RealTrader (em vez de PaperTrader)
- `TRADING_MODE=paper` → Mantém PaperTrader (seguro para validação)

### Passo 3: Commit & Push (se na VPS)

```bash
git add exchange.py real_trader.py websocket_monitor.py websocket_runner.py requirements.txt bot.py
git commit -m "feat: Add Binance Testnet integration with WebSocket real-time monitoring"
git push origin master
```

Depois, redeploy no Coolify.

## Testing Strategy

### Fase 1: Papel → Testnet (Validação de Integração)
```bash
TRADING_MODE=paper  # Continua com paper trader
# Validar que nada quebrou
python bot.py --once
```

### Fase 2: Ativar Testnet
```bash
TRADING_MODE=live
BINANCE_TESTNET=true  # Importante!
# Testa ordens reais, mas em testnet (sem risco)
python bot.py --once
```

Você verá logs como:
```
[REAL] Opened LONG order 123456 @ $2345.67 | size=0.5000
[REAL] TP1 close order 789012 @ $2350.00
[REAL] Closed LONG @ $2346.00 | Reason: TRAILING STOP | PnL=+$2.50
```

### Fase 3: Validar WebSocket
O WebSocket conecta automaticamente quando há posição aberta:
```
WebSocket connected to wss://stream.testnet.binancefuture.com/ws/ethusdt@bookTicker
Exit detected: TP1
```

### Fase 4: Monitor de Performance
- Deixar rodando 2-4 semanas em testnet
- Acumular ~30 trades para validar estatísticas
- Comparar com paper trading results
- Se semelhante → confiança para live mode

## Migração para Live Mode

Quando pronto:
```bash
BINANCE_TESTNET=false  # ou omita (false é default)
# Gere credenciais LIVE em: https://www.binance.com/en/my/settings/api-management
# Coloque em .env:
BINANCE_API_KEY=<sua_live_api_key>
BINANCE_API_SECRET=<sua_live_secret>
```

⚠️ **Importante:** Sempre comece com capital pequeno em live mode!

## WebSocket Behavior

### Real-Time Detection
- Preço atualiza via WebSocket (não espera 1 hora)
- Detecta SL/TP em milissegundos
- Executa exit order imediatamente

### Que sinais são detectados:
1. **STOP LOSS** — Se preço bate SL
2. **TP1** — Se preço bate TP1 (fecha 50%)
3. **TRAILING STOP** — Se preço bate EMA21

### Timeout
- Se WebSocket cai, timeout após 60 segundos
- Bot reconecta automaticamente

## Troubleshooting

### "ModuleNotFoundError: No module named 'websockets'"
```bash
pip install websockets>=12.0
```

### "BINANCE_API_KEY not found"
- Verifique `.env` tem as credenciais corretas
- Testnet keys SÃO diferentes das live keys!

### "Connection refused wss://stream.testnet..."
- Testnet pode estar down (rare)
- Tente com live URL: `wss://fstream.binance.com/...`

### Ordem não fecha
- WebSocket pode estar desconectado
- Verifique logs: `WebSocket connected to...`
- Bot aguarda próxima hora se WebSocket falha (fallback)

## Files Summary

```
exchange.py           ← Atualizado (Testnet + WebSocket URL)
real_trader.py        ← Novo (executa ordens)
websocket_monitor.py  ← Novo (detecta SL/TP)
websocket_runner.py   ← Novo (task assíncrona)
bot.py                ← Atualizado (usa RealTrader quando live)
requirements.txt      ← Atualizado (+websockets)
TESTNET_SETUP.md      ← Este arquivo
```

## Next Steps

1. ✅ Obter credenciais Testnet da Binance
2. ✅ Atualizar `.env` com Testnet keys
3. ✅ Commit e Push para GitHub
4. ✅ Redeploy no Coolify
5. ✅ Testar com `TRADING_MODE=live BINANCE_TESTNET=true`
6. ✅ Deixar rodando 2-4 semanas em testnet
7. ✅ Migrar para live quando confiante
