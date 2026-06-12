# Piano microevolutivo — Dashboard Streamlit di gestione e monitoraggio

> **Data**: 2026-06-12 · **Stato**: pianificato, da implementare nelle prossime sessioni
> **Obiettivo**: un cockpit unico per (a) gestire TUTTE le impostazioni del bot,
> (b) monitorare i trade in corso in tempo reale, (c) consultare uno storico
> CHIARO di tutte le operazioni chiuse con importi precisi per operazione.
> Metodo: fasi piccole, ogni fase utilizzabile da sola e con criteri di
> accettazione espliciti.

---

## 0. Cosa esiste già (da riusare, non rifare)

| Pezzo | Stato | Riuso |
|---|---|---|
| `src/monitoring/dashboard.py` (TradingDashboard) | Streamlit read-only: equity, regime, health, orderflow | Base di partenza — si estende a multipagina |
| `src/journal/trade_logger.py` (journal.db SQLite) | Schema completo: entry/exit price, qty, pnl_usd, r_multiple, equity_at_entry, strategy, regime, exit_reason, timestamps | Fonte unica per lo storico operazioni |
| `src/journal/signal_log.py` (signal_log.db) | Segnali eseguiti/bloccati con motivo | Pannello "perché non ha tradato" |
| `logs/positions.log` (PositionLog) | Storico umano-leggibile | Solo riferimento |
| `data/scoring_state.json`, `data/macro_core_state.json` | Stato scoring + posizione core | Pannello stato strategie |
| DeribitClient REST | posizioni, ordini aperti, equity | Pannello live (sola lettura) |

**Architettura**: la dashboard è un PROCESSO SEPARATO dal bot
(`streamlit run scripts/run_dashboard.py`). Legge: journal.db, signal_log.db,
state JSON, .env, e Deribit via REST read-only. NON importa il bot in
esecuzione. Le azioni di scrittura (fase 2-3) passano da file (.env, flag
files) che il bot rilegge — mai chiamate dirette dentro il processo bot.

---

## Fase 1 — STORICO OPERAZIONI + TRADE LIVE (priorità massima, sola lettura)

**Deliverable**: la richiesta esplicita dell'utente — storico chiaro con
importi precisi per operazione.

1. Pagina **"Storico Operazioni"** (da journal.db):
   - tabella ordinabile/filtrabile: data entry, data exit, strategia, simbolo,
     direzione, **size USD**, prezzo entry, prezzo exit, **P&L $ preciso**,
     P&L %, R-multiple, motivo uscita (tp/sl/time/chandelier), durata
   - filtri: per strategia, simbolo, periodo, win/loss
   - footer aggregato: N trade, win rate, P&L totale $, fees totali stimate,
     expectancy, PF — sia complessivo sia per il filtro corrente
   - export CSV con un click
   - equity curve ricostruita dai trade chiusi (con marcatori per strategia)
2. Pagina **"Trade in corso"** (Deribit REST + state files):
   - posizioni aperte: strumento, direzione, size USD, prezzo medio, mark,
     **P&L non realizzato $**, distanza da SL/TP in %, età della posizione
   - quale strategia possiede la posizione (match con _open_trade dagli
     state files + label ordini)
   - ordini aperti sul venue (SL/TP/trailing) con riconciliazione:
     **evidenzia in rosso ordini senza posizione corrispondente (orfani)**
     e posizioni senza SL (nude) — il check "niente ordini appesi" a vista
3. Accettazione: con il bot in paper trading, ogni trade chiuso compare nello
   storico entro 60s con P&L identico al positions.log; un ordine orfano
   creato a mano viene evidenziato.

## Fase 2 — PANNELLO RISCHIO ed ESPOSIZIONE

1. Esposizione lorda corrente vs cap (`MAX_GROSS_EXPOSURE`): barra di
   utilizzo, breakdown per strumento e per strategia
2. Stato kill switch giornaliero, P&L giornaliero vs MAX_DAILY_LOSS_PCT
3. Vol-target MacroCore: esposizione bucket corrente (0.25/0.50/0.75/1.0)
   e vol realizzata 30d
4. Stato macro per simbolo: prezzo vs SMA200d (BULL/BEAR), chi può tradare
   cosa adesso (matrice strategia x lato abilitato)
5. Accettazione: numeri identici a quelli loggati dal RiskManager

## Fase 3 — GESTIONE IMPOSTAZIONI (.env editor con guardrail)

1. Editor settings raggruppato come il .env (Attive / Rischio / Disattivate):
   - widget tipizzati (slider/toggle/numero) con i RANGE VALIDATI come bound
     (es. TB_SL_ATR_MULT slider 1.5-3.0 con nota "validato: 2.0")
   - **mai mostrare** DERIBIT_API_KEY/SECRET (solo "impostata sì/no")
   - diff prima/dopo + backup automatico .env.bak con timestamp
   - banner "modifica parametri = invalidazione backtest — rivalidare con
     la pipeline" sui parametri strategia (vs parametri operativi liberi)
2. Toggle abilitazione per strategia/simbolo (TB_SYMBOLS ecc.)
3. Avviso "richiede riavvio bot" (il bot legge .env all'avvio) + pulsante
   opzionale di richiesta riavvio via flag file che il FailureHandler onora
4. Accettazione: modifica di un flag dalla UI → .env aggiornato e valido
   (Config.load_strategies() non solleva), backup creato

## Fase 4 — CONTROLLI OPERATIVI (azioni, dietro conferma doppia)

1. Pulsante **kill switch manuale** (flag file → bot blocca nuovi ingressi)
2. Chiusura manuale di una posizione (reduce-only market) con conferma
3. Pulizia orfani on-demand (richiama la logica di check_orphan_orders)
4. Accettazione: ogni azione scrive un audit log (chi/cosa/quando)

## Fase 5 — RIBALTAMENTO DOCS (richiesto: "ribaltare completamente")

Il funzionamento del bot è cambiato radicalmente (giu 2026): strategie
volumetriche → TB/FS/MC validate, multi-symbol, macro gating, vol-target.
1. Riscrivere `README.md`: architettura attuale, 3 strategie attive coi
   numeri di validazione, quickstart, dashboard
2. `docs/`: rigenerare 01_architecture, 02_strategies (TB/FS/MC),
   03_configuration (nuovo .env), 05_risk_sizing (gross cap, vol-target);
   ARCHIVIARE in docs/archive/ i file superati (smart money, condor,
   piani profittabilità vecchi)
3. Spostare/archiviare i .md sparsi nella root (SMART_MONEY_STRATEGY.md,
   PIANO_PROFITTABILITA.md, ecc.) in docs/archive/
4. Fonte di verità per i numeri: microevolutive/PLAN_BULL_EVOLUTION.md
   e data/research/*.txt — i docs LINKANO, non duplicano

---

## Ordine di esecuzione suggerito

1. Fase 1 (storico + live + riconciliazione ordini) — il valore maggiore
2. Fase 2 (rischio/esposizione) — riusa i dati della Fase 1
3. Fase 5 (docs) — indipendente, può andare in parallelo
4. Fase 3 (settings editor) — richiede guardrail accurati
5. Fase 4 (azioni operative) — per ultima: scrive verso il venue

Stima: Fase 1+2 in una sessione; Fase 5 in una; Fase 3+4 in una.

## Vincoli di sicurezza (validi per tutte le fasi)

- Dashboard di default in SOLA LETTURA; le azioni scrivono solo file locali
  o passano da conferma doppia
- Nessun secret a schermo, mai
- Il bot resta autonomo: la dashboard giù non deve impattare il trading
