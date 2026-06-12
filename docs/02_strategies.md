# Le strategie attive — Trend Breakdown, Funding Squeeze, Macro Core

> Aggiornato: giugno 2026. Fonte di verità per i numeri:
> [../microevolutive/PLAN_BULL_EVOLUTION.md](../microevolutive/PLAN_BULL_EVOLUTION.md)
> e i report in `data/research/` (multicycle_report.txt, eth_validation.txt,
> legacy_validation_btc.txt). Questo documento descrive la LOGICA; i numeri
> citati sono gli headline della validazione 4 anni (giu 2022 → giu 2026,
> backtest sul codice reale, costi 0.20% roundtrip, no lookahead).

Tutte le strategie implementano l'interfaccia immutabile `BaseStrategy`
(`scan` / `execute_entry` / `manage_positions`) e ricevono il
`KlineProvider` **iniettabile**: lo stesso identico codice gira live (klines
REST Binance) e in backtest (provider storico a finestra). Questo elimina la
classe di bug "il backtest fa una cosa, il live un'altra".

---

## 1. Trend Breakdown (`src/strategies/trend_breakdown.py`)

Strategia tattica **bidirezionale macro-gated**: ogni lato esiste solo
nella fase macro in cui è stato validato.

### Lato SHORT — breakdown del minimo 48h (solo macro BEAR)

Condizioni (valutate una volta per barra 1h CHIUSA):
1. close 1h < minimo delle 48 barre precedenti (Donchian low)
2. close < SMA48 oraria (filtro trend)
3. `buy_ratio` della barra < 0.50 (i taker stanno vendendo)
4. **Macro gate: close daily < SMA200d** (senza: -24 bps/trade in bull)

Uscite: SL = entry + 2×ATR(1h,14) · TP = 2R · time exit 24h.
Validazione BTC: **+22 bps/trade, PF 1.26, 123 trade**; sul solo bear
2025-26: +50 bps PF 1.8 (IS/OOS). **ETH: BOCCIATO** (PF 0.87) → short
attivo solo su BTC (`TB_SHORT_SYMBOLS`).

### Lato LONG — breakout del massimo 7 giorni (solo macro BULL)

Condizioni: close 1h > massimo delle 168 barre precedenti, close > SMA48,
`buy_ratio` > 0.50, **close daily > SMA200d**.

Uscite: SL = entry − 2×ATR · **nessun TP** (`TB_RR_LONG=0`) · time exit
7 giorni. Lasciar correre i winner raddoppia l'edge rispetto a TP 3R/48h.
Validazione: **BTC +68 bps PF 1.53 (84 trade) · ETH +183 bps PF 2.32 (58
trade)**. Lookback più corti (48h) sono breakeven; pullback-buy e momentum
3d testati NEGATIVI — solo il breakout 168h sopravvive.

### Note operative
- Un trade alla volta per istanza; un segnale per barra 1h.
- Entry **market** (una limit non fillata lascerebbe SL/TP orfani).
- Sizing: `RiskManager.calculate_dynamic_size` (vedi
  [05_risk_sizing.md](05_risk_sizing.md)).

---

## 2. Funding Squeeze (`src/strategies/funding_squeeze.py`)

**Specialista della capitolazione deep-bear**, bassa frequenza per design
(~4 trade/anno). Short contrarian quando i long pagano funding al cap
mentre il downtrend macro accelera.

Condizioni (solo entro 60 min da un settlement funding — 00/08/16 UTC,
il timing su cui l'edge è stato validato):
1. Funding rate ≥ 0.01%/8h (= cap dell'exchange su BTC)
2. close 1h < SMA48 oraria
3. **Macro gate doppio: close daily < SMA200d E SMA200d più bassa di 30
   giorni fa** (SMA in discesa = downtrend in forza, non un dip)

Uscite: SL = entry + 2×ATR(1h) · TP 2R · time exit 24h · cooldown 8h
(un trade per finestra funding).

Validazione: **BTC +74 bps/trade, PF 2.65, 15 trade/4y · ETH +64 bps,
PF 1.82, 39 trade**. La versione naive (senza il gate doppio) perdeva
-23 bps in bull e sanguinava nelle transizioni di trend — i due failure
mode sono eliminati per costruzione.

---

## 3. Macro Core (`src/strategies/macro_core.py`)

**Posizione core long di regime** (hold settimane/mesi), non una tattica.
Cattura il grosso del bull market con un'uscita disciplinata.

- **Entry**: close daily > SMA200d (valutato una volta per barra daily chiusa)
- **Exit**: chandelier — close daily < (max close dall'entry − 5×ATR20d).
  Esce dal blow-off top ~5 ATR sotto il picco, mesi prima della croce SMA200
  che costava -17% alla versione naive.
- **Stop disastro** sul venue a entry×(1−25%): protegge da crash col bot
  offline. L'uscita vera è il chandelier in `manage_positions()`.
- **Vol-target 30%** (C4): esposizione = clip(0.30 / vol realizzata 30d,
  0, 1) quantizzata a step 0.25; ribilancio solo al cambio di bucket.
- **Stato persistente** (`data/macro_core_state.json`): la posizione vive
  mesi attraverso i restart; riconciliata col venue al primo
  `manage_positions`.

Validazione BTC: **+315%/4y vs +136% buy&hold, maxDD 24.7%, 9 trade**,
2025 -1%. Plateau robusto k∈[4.5, 6]. **ETH: BOCCIATA** (= buy&hold con
maxDD 58%) → solo BTC. Con più simboli in `MC_SYMBOLS` il budget di
esposizione si DIVIDE (BTC/ETH correlano ~0.8).

---

## Portafoglio e gating automatico

Equity sim 4y delle 5 istanze insieme (C4, `scripts/equity_sim.py`):
baseline +770% maxDD 29.6%; **con vol-target 30% su MC (adottato):
+491%, maxDD 21.5%, Calmar 2.61, peggior anno 0.0%**. Kelly 0.25× e
de-risk su DD testati e BOCCIATI (Calmar peggiore).

Tre livelli di attivazione automatica (nessun intervento manuale):

| Livello | Meccanismo | Dove |
|---|---|---|
| Macro (giorni-mesi) | SMA200d daily: bear→TB short+FS, bull→TB long+MC | dentro ogni strategia |
| Regime (ore) | REGIME_RULES per TREND/RANGE/COMPRESSION/EXPANSION | `src/engine/scoring.py` |
| Performance (rolling) | score = WR×expectancy×Sharpe sotto soglia → off | `ScoringEngine.should_trade` |

Guardrail live (dal piano): PF rolling < 0.8 dopo ≥30 trade → disattivare
e rivalidare; DD > 1.5× il maxDD di backtest → disattivare subito.

---

## Strategie disattivate (bocciate coi dati)

Tutte validate con la stessa pipeline e tenute nel codice come riferimento.
Verdetti completi nel `.env` e nei report citati in testa.

| Strategia | Verdetto 4y |
|---|---|
| Volume Breakout | PF 0.42-0.74, -13/-20 bps, negativa in OGNI fase e anno |
| Mean Reversion (VWAP fade) | PF 0.28-0.53, -22/-47 bps |
| Liquidation Squeeze | PF 0.06-0.30 — quando la cascata è visibile, il movimento è finito |
| Imbalance Scalp | PF 0.18-0.50 su 29k+ trade — fee-bound, edge lordo zero |
| NY Brings | PF 0.64, -17.5 bps, negativa ogni anno (718 trade) |
| W/M Formation | unica con edge BTC (+17 bps PF 1.21) ma 2024 negativa e ETH negativa → non strutturale |
| Smart Money | componenti testabili già falliti (stagionalità) |
| Iron Condor | opzioni — fuori direzione progetto |
