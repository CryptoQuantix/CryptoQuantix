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

### C1 — MacroCore (il "guadagnare di più" vero) · PRIORITÀ MASSIMA
**Ipotesi**: nel bull la maggior parte del rendimento è drift; un'esposizione core
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

### C2 — Trailing stop engine per TrendBreakdown
**Ipotesi**: l'exit a tempo (168h) lascia profitti sul tavolo nei trend forti;
un chandelier ATR cattura le code senza allargare le perdite.
**Fatto finora**: noTP/168h ha già raddoppiato l'edge long (+22→+68bps).
**Micro-step**:
1. Estendere `strategy_lab.simulate()` con trailing: SL dinamico =
   max(SL, max_close_since_entry − k×ATR), k ∈ {3, 4, 5} long; simmetrico short
2. Se i gate passano (PF e cumulato ≥ baseline noTP/168h, 2025 non peggiorato):
   implementare in `manage_positions()` (modifica SL via order_manager —
   verificare API per edit/cancel-replace dello stop su Deribit)
3. Testare anche su lato SHORT (oggi TP 2R/24h)

### C3 — TrendBreakdown multi-symbol (ETH, poi SOL)
**Ipotesi**: l'edge Donchian+macro è strutturale, non BTC-specifico;
più simboli = più trade indipendenti = più rendimento totale a parità di edge.
**Micro-step**:
1. `download_multicycle.py --symbol ETHUSDT` (parametrizzare SYMBOL/OUT)
2. Rivalidare TB short+long su ETH 4y con la stessa griglia (NO ri-ottimizzare
   i parametri per simbolo: stessi parametri = test di robustezza)
3. Se gate ok: config TB con lista simboli, instrument ETH-PERPETUAL su Deribit
4. Cap di rischio aggregato: BTC ed ETH correlano ~0.8 → il RiskManager deve
   trattarli come ~1 posizione ai fini del rischio totale
5. Stesso esercizio per FundingSqueeze su ETH (funding cap diversi — verificare)

### C4 — Sizing evolution (più rendimento senza nuove strategie)
**Ipotesi**: il modo più sicuro di "guadagnare di più" è dimensionare meglio
ciò che già funziona.
**Micro-step**:
1. Simulatore di equity con sizing reale (oggi i backtest sono full-equity):
   estendere strategy_lab con equity compounding + risk_pct per trade
2. Testare: rischio fisso 1% vs 1,5% in regime favorevole (scoring engine) vs
   frazione di Kelly (cap 0,25×Kelly) su WR/payoff rolling
3. Drawdown-based de-risking: dimezza il rischio sotto -10% di DD equity
4. Gate: maxDD simulato < 20% con rendimento ≥ baseline

### C5 — Dip-buy v2 (parcheggiata — riprovare con trigger diversi)
v1 bocciata (instabile: 2023 +47%, 2024 -15%). Se si riprova:
- dip più profondi (-10% dal max 20d) o RSI daily < 30 in macro bull
- trigger di capitolazione: funding NEGATIVO in macro bull (rarità = qualità)
- gate severo: positiva in 2023 E 2024 separatamente, altrimenti scarto definitivo

### C6 — FundingSqueeze LONG mirror (parcheggiata)
Funding < -0,01% + macro bull: solo 4-11 eventi in 4 anni (N insufficiente).
Riconsiderare solo se il prossimo bull produce abbastanza eventi (monitorare
via signal_log senza tradare).

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

## 5. Ordine di esecuzione suggerito (prossima sessione)

1. C1 step 1-2 (sweep MacroCore + vol targeting) — solo ricerca, zero rischio
2. C2 step 1 (trailing nel simulatore) — sblocca anche C1 exit
3. C1 step 3 (implementazione MacroCore) se i gate passano
4. C4 step 1-2 (equity simulator + sizing)
5. C3 (ETH) quando 1-4 stabili

Stima: C1+C2 in una sessione; C3+C4 nella successiva.
