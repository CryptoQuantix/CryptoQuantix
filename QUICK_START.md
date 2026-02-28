# 🚀 Quick Start - Coinmaker Bot

Guida rapida per iniziare in 5 minuti!

## ⚡ Setup Veloce

### 1. Installa Dipendenze (1 minuto)

```bash
pip install -r requirements.txt
```

### 2. Configura API Keys (2 minuti)

Copia il template:
```bash
copy .env.example .env
```

Modifica `.env` e inserisci le tue keys:
```env
DERIBIT_API_KEY=tua_key_qui
DERIBIT_API_SECRET=tuo_secret_qui
DERIBIT_ENV=test
```

**Dove trovo le API keys?**
1. Vai su [test.deribit.com](https://test.deribit.com)
2. Login → Account → API
3. Create New API Key
4. Copia Key e Secret

### 3. Crea Cartella Logs

```bash
mkdir logs
```

### 4. Test Connessione (1 minuto)

```bash
python test_connection.py
```

Se vedi `✓ Authentication successful` sei pronto!

### 5. Avvia il Bot (1 minuto)

```bash
python -m src.trading_bot
```

## ✅ Checklist Pre-Avvio

Prima di avviare il bot, verifica:

- [ ] Python 3.8+ installato
- [ ] Dipendenze installate (`pip install -r requirements.txt`)
- [ ] File `.env` configurato con API keys valide
- [ ] `DERIBIT_ENV=test` (usa SEMPRE testnet all'inizio!)
- [ ] Cartella `logs/` creata
- [ ] Test connessione passato (`python test_connection.py`)

## 🎮 Comandi Utili

### Visualizza Configurazione
```bash
python config.py
```

### Controlla Opportunità (senza tradare)
```bash
python scripts\check_opportunities.py
```

### Visualizza Posizioni Aperte
```bash
python scripts\view_positions.py
```

### Avvia Bot
```bash
python -m src.trading_bot
```

### Ferma Bot
Premi `Ctrl+C`

## 📊 Cosa Aspettarsi

### Dopo l'Avvio

Il bot:
1. ✅ Si autentica con Deribit
2. ✅ Carica la configurazione
3. ✅ Esegue scan iniziale
4. ✅ Entra in loop di monitoraggio

### Schedule Automatico

- **10:00 AM**: Scan per nuove posizioni
- **Ogni 5 min**: Monitora posizioni aperte

### Output Console

```
========================================
STARTING TRADING BOT
========================================
INFO - Successfully authenticated with Deribit
INFO - Bot initialized for test environment

SCANNING FOR NEW POSITIONS
INFO - Checking BTC...
INFO - Spot price: $95,234.50
INFO - ATM IV: 65.23%
INFO - IV conditions met: IV rank 72.3%
INFO - Built Iron Condor: BTC_27DEC24_...
INFO - ✓ Successfully opened condor
```

## ⚠️ Primi Passi IMPORTANTI

### 1. USA SEMPRE TESTNET

Il testnet usa fondi virtuali. Perfetto per imparare senza rischi!

**File `.env`:**
```env
DERIBIT_ENV=test  # ← Assicurati sia "test"
```

### 2. Monitora i Log

Apri `logs/trading_bot.log` in un editor e tienilo aperto mentre il bot gira.

### 3. Lascia Girare per Qualche Giorno

Non aspettarti trade immediati:
- Potrebbe non trovare opportunità subito
- L'IV potrebbe essere troppo bassa
- Nessuna scadenza nel range 7-10 DTE

È normale! Il bot è selettivo.

### 4. Controlla Manualmente su Deribit

Vai su [test.deribit.com](https://test.deribit.com) e verifica:
- Posizioni aperte
- Saldo account
- Ordini eseguiti

## 🔧 Troubleshooting Rapido

### "Authentication failed"
→ Controlla che API key/secret siano corretti in `.env`

### "Module not found"
→ Reinstalla: `pip install -r requirements.txt`

### "No opportunities found"
→ Normale! IV potrebbe essere bassa. Aspetta o prova più tardi

### Bot si ferma subito
→ Controlla `logs/trading_bot.log` per l'errore

## 📖 Dove Andare Dopo

Una volta che il bot gira in testnet:

1. **Giorno 1-3**: Osserva il bot, leggi i log
2. **Giorno 4-7**: Sperimenta con parametri in `.env`
3. **Giorno 8-14**: Monitora performance e P&L
4. **Settimana 3+**: Se tutto ok, considera prod (con capitale ridotto!)

## 📚 Documentazione Completa

- [README.md](README.md) - Documentazione principale
- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Setup dettagliato
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Architettura progetto

## 🎯 Obiettivi Primi Giorni

### Giorno 1
- [ ] Bot avviato con successo
- [ ] Capisco i log
- [ ] Ho visto almeno 1 scan

### Giorno 2-3
- [ ] Bot ha aperto almeno 1 posizione (se IV alta)
- [ ] Monitoro P&L su Deribit
- [ ] Capisco come funziona TP/SL

### Settimana 1
- [ ] Bot ha chiuso almeno 1 posizione
- [ ] Ho analizzato i log di trade
- [ ] Mi sento sicuro con testnet

## 💡 Tips Pro

1. **Non modificare i parametri** i primi giorni. Usa i default.
2. **Leggi SEMPRE i log** dopo un trade
3. **Non passare a prod** senza almeno 2 settimane di testnet
4. **Tieni un diario** di cosa osservi
5. **Fai domande** se qualcosa non è chiaro

## ⚡ Comandi Quick Reference

```bash
# Test
python test_connection.py

# Opportunità
python scripts\check_opportunities.py

# Posizioni
python scripts\view_positions.py

# Config
python config.py

# Bot
python -m src.trading_bot
```

---

## 🚨 RICORDA

> **Testnet First, Production Later!**
>
> Il testnet è lì proprio per imparare senza rischi.
> Non avere fretta di passare a prod!

---

**Pronto? Vai! 🚀**

```bash
python -m src.trading_bot
```

Buon trading! 🎉
