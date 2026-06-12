# Piano microevolutivo — Strategie per il prossimo bull market

> **Data**: 2026-06-11 · **Stato**: pianificato, da implementare nella prossima sessione
> **Metodo**: evoluzione a piccoli passi — ogni candidato passa i gate o viene scartato.
> Nessun parametro va cambiato senza rivalidazione completa (pipeline sotto).

---

## 0. Baseline attuale (già implementato e validato)

Backtest 4 anni (giu 2022 → giu 2026, codice reale, costi 0,20% roundtrip, no lookahead):

| Strategia | Trade | Avg/trade | PF | Cumulato |
|---|---|---|---|---|
| TrendBreakdown SHORT (48h-low, macro bear) | 123 | +22 bps | 1.26 | +27% |
| TrendBreakdown LONG (7d-high, macro bull, noTP/168h) | 84 | +68 bps | 1.53 | +57% |
| FundingSqueeze (funding al cap + SMA200d giù) | 15 | +74 bps | 2.65 | +11% |
| **Portafoglio** | **222** | **+43 bps** | **1.43** | **+95%** |

Per anno: 2023 +32% · 2024 +43% · 2025 **-18%** · 2026 (5,5 mesi) +39%.
Peggior anno = 2025 (blow-off top): è il punto debole da attaccare.

**Strategie scartate per sempre** (zero edge lordo su 4 anni, perdita ≈ costi):
breakout intraday 20-bar (VolumeBreakout), fade VWAP ±2σ (MeanReversion),
scalp continuation su flow (ImbalanceScalp), cavalcata cascate (LiqSqueeze),
pullback long su SMA oraria, momentum 3 giorni, stagionalità oraria/settimanale.
**Non re-investire tempo qui.**

---

## 1. Pipeline di validazione (obbligatoria per ogni candidato)

```
1. Ipotesi economica scritta PRIMA del test (perché l'edge dovrebbe esistere?)
2. Event study vettoriale          -> scripts/quant_research.py come modello
3. Simulazione trade-by-trade      -> scripts/strategy_lab.py (simulate)
   - dataset: data/research/btc_1m_4y.csv.gz (refresh con scripts/download_multicycle.py)
   - segmentazione per fase        -> multicycle_research.compute_phase / phase_report
4. Gate quantitativi (TUTTI necessari):
   - PF >= 1.2 sul campione completo
   - positivo in ALMENO 2 anni bull distinti (2023 E 2024, non solo uno)
   - peggior anno > -15%
   - N >= 30 trade (o motivazione esplicita se specialista raro)
   - robustezza: le celle adiacenti della griglia parametri restano positive
5. Implementazione classe BaseStrategy con kline_provider iniettabile
6. Backtest event-driven del CODICE REALE -> scripts/backtest_new_strategies.py
   (i numeri devono replicare il punto 3 entro ~20%)
7. Dry run offline                  -> scripts/dry_run_strategies.py (FakeKlineProvider)
8. 2-4 settimane testnet Deribit, confronto trade live vs attesi (signal_log)
```

**Trappole note** (già pagate care):
- `pandas.resample` etichetta a SINISTRA → spostare gli eventi a fine barra
  (`make_events(..., bar_minutes)`) o lookahead di 1h che gonfia 3x
- `reindex(ffill)` su serie 1h/1d → indicizzare per *close time*
- warmup SMA200d: i primi 200 giorni del backtest non tradano (live no)
- entry timing del funding: validato SOLO entro 60 min dal settlement

---

## 2. Candidati in ordine di priorità

### C1 — MacroCore · ✅ COMPLETATA (2026-06-12)
**Esito**: implementata in `src/strategies/macro_core.py` (MC_* in .env).
Lo sweep anti-whipsaw ha trovato il vincitore: **exit chandelier k=5**
(close < max_close dall'ingresso − 5×ATR20d) al posto dell'uscita SMA200:
**+315%/4y** (vs +193% della naive, +136% buy&hold), maxDD 24,7%, 9 trade,
2023 +108% · 2024 +100% · **2025 -1%** (whipsaw risolto). Plateau robusto
k∈[4.5, 6]. Backtest codice reale = sweep (scripts/backtest_macro_core.py).
Isteresi/slope/conferma-2gg: tutte peggiori del chandelier. Vol-targeting
entry-fixed non lega (expo media 0,94) → ribilanciamento giornaliero rinviato
a C4. Stato persistente su data/macro_core_state.json, stop disastro -25%.

**Ipotesi originale**: nel bull la maggior parte del rendimento è drift; un'esposizione core
con filtro di tendenza cattura più di qualsiasi strategia tattica.
**Pre-validazione (round 6, 2026-06-11)**: long se daily close > SMA200d:
**+193% in 4 anni** (buy&hold +136%), 16 roundtrip totali, maxDD 31,7%,
2023 +94,5% · 2024 +81,6% · 2025 -17% (whipsaw al top) · 2026 0% (flat, fuori mercato).

**Micro-step da eseguire**:
1. Sweep anti-whipsaw (obiettivo: 2025 > -10% senza uccidere 2023-24):
   - isteresi: entra sopra SMA200×(1+b), esci sotto SMA200×(1-b), b ∈ {1%, 2%, 3%}
   - filtro slope: solo se SMA200d > SMA200d di 20-30gg fa
   - exit alternativa: trailing ATR(d) ×{3, 4, 5} dal massimo (chandelier daily)
   - conferma: 2 chiusure daily consecutive oltre la soglia
2. Sizing: vol-targeting (esposizione = target_vol / vol_realizzata_30d, cap 1x)
   → riduce il maxDD 32% verso ~15-20% con poco costo sul rendimento
3. Implementazione `src/strategies/macro_core.py`:
   - scan 1×/giorno (dedupe per barra daily come TB fa per 1h)
   - kline 1d dal provider (già supportato, limit 230+)
   - **PERSISTENZA STATO**: la posizione dura mesi → salvare `_open_trade` su
     file (data/macro_core_state.json) e ricaricarlo al riavvio; verificare
     vs posizione reale sul venue all'avvio
   - niente SL stretto: exit = condizione macro o trailing; SL disastro a -25%
   - convivenza con TB long: entrambi long in bull → cap esposizione aggregata
     nel RiskManager (vedi C4)
4. Gate: pipeline §1 + maxDD < 25% con sizing scelto

### C2 — Trailing stop engine per TrendBreakdown · ❌ BOCCIATA (2026-06-12)
**Esito**: trailing implementato nel simulatore (`strategy_lab.simulate()`,
colonna `trail`) e testato su TB con k∈{3,4,5}, hold fino a 336h:
- LONG: migliore variante (k=5/336h) +53,2% cumulato vs **+59,2% baseline**
  noTP/168h → gate "cumulato ≥ baseline" FALLITO
- SHORT: tutte negative o ≈0 vs +22bps baseline TP 2R/24h → FALLITO
Il chandelier funziona solo a scala daily (MacroCore). **Niente trailing
engine live** — complessità order-edit evitata. Il supporto `trail` nel
simulatore resta per test futuri.

### C3 — Multi-symbol ETH · ✅ COMPLETATA (2026-06-12)
**Esito** (stessi parametri di BTC su ETH 4y, zero ri-ottimizzazione —
`scripts/validate_symbol.py --symbol ETH`, report `data/research/eth_validation.txt`):
- **TB LONG (7d-high): PROMOSSA su ETH** — +183bps/trade, PF 2.32, 58 trade,
  2023 +18% / 2024 +60% / 2025 +29% (3/3 anni positivi). L'edge long è
  strutturale.
- **TB SHORT (48h-low): BOCCIATA su ETH** — -17bps, PF 0.87: edge
  BTC-specifico → nuovo flag `enable_short` per config, gestito da
  `TB_SHORT_SYMBOLS=BTCUSDT`
- **FS: PROMOSSA su ETH** — +64bps, PF 1.82, 39 trade (il funding ETH non è
  clampato al cap: max 0.10% vs 0.01% BTC, la soglia lega più spesso)
- **MC: BOCCIATA su ETH** — +38.7% = buy&hold, maxDD 58%, 2025 -18%: il
  trend ETH è troppo choppy per SMA200+chandelier → MC_SYMBOLS=BTCUSDT
- Infrastruttura: `*_SYMBOLS` in config (istanza per simbolo, strumento
  derivato BTCUSDT→BTC-PERPETUAL), state path MacroCore per simbolo,
  **budget esposizione MC diviso tra i simboli** (corr ~0.8 = ~1 posizione)
- Bug fix: il FakeExecClient del backtest MacroCore interpretava i sell di
  ribilanciamento vol-target come exit → ora distingue per label (mc_exit)
- Default produzione: TB su BTC+ETH (short solo BTC), FS su BTC+ETH, MC solo BTC

### C4 — Sizing evolution · ✅ COMPLETATA (2026-06-12)
**Esito** (`scripts/equity_sim.py`: portafoglio TB+FS+MC su equity composta
giornaliera, sizing a rischio sui trade tattici, m2m daily su MacroCore,
griglia 18 varianti):
- Baseline (risk 1% / MC expo fissa): **+770%/4y**, maxDD 29,6%, CAGR 72%
- **Vol-target 30% su MacroCore: ADOTTATO** — migliora il Calmar in OGNI
  config (2.43→2.61; 2.68→2.87 con risk 1,5%), maxDD 29,6%→21,5%,
  peggior anno →0%. Implementato in macro_core.py: expo =
  clip(0.30/vol_30d, 0, 1) quantizzata 0,25, ribilancio daily in
  manage_positions (MC_VOL_TARGET, 0=off)
- **Kelly 0,25×: BOCCIATO** — Calmar peggiore del rischio fisso su 222
  trade (rumore, non segnale)
- **De-risk su DD -10%: BOCCIATO** — distrugge più rendimento del DD che
  salva (Calmar giù in ogni confronto)
- Rischio 1,5%: Calmar migliore (2.87) ma DD 23,1% — opzione aggressiva,
  default resta BASE_RISK_PCT=0.01
- **Nota gate**: maxDD<20% E rendimento ≥ baseline è irraggiungibile (ogni
  riduzione di rischio riduce il totale); il punto efficiente adottato è
  1%/volT30 → +491%, maxDD 21,5%, Calmar 2.61, peggior anno 0,0%

### C5 — Dip-buy v2 (parcheggiata — riprovare con trigger diversi)
v1 bocciata (instabile: 2023 +47%, 2024 -15%). Se si riprova:
- dip più profondi (-10% dal max 20d) o RSI daily < 30 in macro bull
- trigger di capitolazione: funding NEGATIVO in macro bull (rarità = qualità)
- gate severo: positiva in 2023 E 2024 separatamente, altrimenti scarto definitivo

### C6 — FundingSqueeze LONG mirror (parcheggiata)
Funding < -0,01% + macro bull: solo 4-11 eventi in 4 anni (N insufficiente).
Riconsiderare solo se il prossimo bull produce abbastanza eventi (monitorare
via signal_log senza tradare).

### C7 — Validazione strategie LEGACY (mai testate quantitativamente)
Iron Condor, Smart Money, W/M Formation, NY Brings: oggi OFF ma **mai
passate dalla pipeline** — da validare e migliorare se valide, o bocciare
con dati come le volumetriche.
**Priorità**: W/M e Brings (backtestabili subito sul dataset 4y; per W/M
esiste già `scripts/backtest_wm_strategy.py` — VERIFICARE lookahead) >
Smart Money (proxy OHLCV parziale; nota: la stagionalità oraria è già
risultata non robusta nella ricerca) > Iron Condor (servono dati storici
opzioni/IV — valutare se vale lo sforzo).
**Micro-step**: estrarre la regola core in forma vettoriale → test 4y con
fase bull/bear e costi → gate §1 → se passa, gating macro come TB; se
fallisce, documentare nel report e lasciare OFF per sempre.

---

## 3. Infrastruttura da costruire (prerequisiti C1-C4)

| Pezzo | Serve a | Note |
|---|---|---|
| Persistenza stato strategia | C1 (posizioni multi-mese) | JSON per strategia, riconciliazione con venue all'avvio |
| Trailing-stop in simulate() | C2 | ~30 righe in strategy_lab |
| Equity/compounding nel backtest | C4 | sostituire full-equity con risk_pct |
| download_multicycle parametrico | C3 | --symbol, --days, --out |
| Cap esposizione aggregata long | C1+C3 | RiskManager: somma esposizioni correlate |
| Edit dello stop su ordine vivo | C2 | verificare deribit_client (edit vs cancel/replace) |

---

## 4. Kill criteria in produzione (per OGNI strategia)

- PF rolling < 0,8 dopo ≥ 30 trade live → disattivare e rivalidare
- Drawdown della strategia > 1,5× il maxDD di backtest → disattivare subito
- Divergenza live vs backtest (slippage reale > 2× assunto) → rivedere costi
- Ogni 30 giorni: refresh dataset + re-run `backtest_new_strategies.py`;
  se i parametri non sono più nella zona robusta → NON ri-ottimizzare al volo,
  ripassare dalla pipeline §1

---

## 5. Ordine di esecuzione (aggiornato 2026-06-12)

1. ~~C1 (MacroCore)~~ ✅ FATTA — chandelier k=5, +315%/4y, in produzione
2. ~~C2 (trailing TB)~~ ❌ BOCCIATA — peggiore delle baseline su entrambi i lati
3. ~~C4 (equity sim + sizing)~~ ✅ FATTA — volT30 su MC adottato (DD 21,5%);
   Kelly e DD-derisk bocciati coi dati
4. ~~C3 (ETH multi-symbol)~~ ✅ FATTA — TB long + FS promosse su ETH;
   TB short e MC bocciate su ETH (BTC-only)
5. **PROSSIMA SESSIONE → C7** (validazione legacy: W/M e Brings prima,
   backtestabili subito sui dataset 4y BTC+ETH già nel repo)
6. Backlog restante: C5 (dip-buy v2, gate severo), C6 (FS long mirror,
   monitorare via signal_log), SOL come terzo simbolo per TB long
