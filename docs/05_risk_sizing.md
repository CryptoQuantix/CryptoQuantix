# Risk management — sizing, cap di portafoglio, kill switch

> Aggiornato: giugno 2026. Implementazione: `src/core/risk_manager.py`.
> La versione precedente (focalizzata su Kelly teorico e condor) è in
> `docs/archive/` (repo privato).

Il rischio è gestito su **quattro livelli indipendenti**: per-trade
(sizing), per-portafoglio (cap lordo + max posizioni), per-giornata (kill
switch) e per-posizione (mai senza stop sul venue).

## 1. Sizing per-trade: 3-factor dinamico

`RiskManager.calculate_dynamic_size()` — usato da TB e FS:

```
base_risk = equity × BASE_RISK_PCT          (default 1%)
adj_risk  = base_risk × vol_scalar × regime_scalar × kelly_scalar
quantity  = adj_risk / |entry − SL|
```

| Fattore | Valori |
|---|---|
| Volatilità (percentile ATR) | <30 → 1.0 · 30-70 → 0.75 · ≥70 → 0.50 |
| Regime | TREND 1.0 · RANGE 0.80 · EXPANSION 0.70 · COMPRESSION 0.60 · UNKNOWN 0.70 |
| Kelly frazionario | kelly = 2×WR−1, clip [0.05, 0.25], normalizzato /0.25 |

Cap finali in cascata: leverage effettivo ≤ 10×, poi **cap di esposizione
lorda aggregata** (sotto). Nota operativa: con `model_winrate=0.50` il
kelly_scalar vale 0.2 → il rischio tattico reale è ~0.15-0.2% per trade,
non l'1% nominale (scelta conservativa documentata).

Il Macro Core non usa il 3-factor: la size core è
`equity × MC_EXPOSURE_FRACTION × bucket vol-target`, comunque cappata dal
limite lordo.

## 2. Cap di portafoglio (anti-oversizing multi-strategia)

Con 5 istanze attive (TB BTC+ETH, FS BTC+ETH, MC BTC) più strategie possono
aprire nello stesso momento. Due limiti:

- **`MAX_GROSS_EXPOSURE=1.5`**: somma del nozionale ASSOLUTO di tutte le
  posizioni futures ≤ 1.5 × equity. Ogni nuova size viene cappata ad
  `available_gross_usd()`; a cap raggiunto le entry sono bloccate.
- **`MAX_OPEN_TRADES=3`**: numero massimo di posizioni sul venue.

`can_open_new_position()` è il gate unico: kill switch → max posizioni →
cap lordo. Nota strutturale: i macro-gate rendono impossibili posizioni
OPPOSTE sullo stesso strumento (MC long esiste solo in macro bull, TB short
solo in macro bear) — niente netting conflict su venue netted.

## 3. Kill switch giornaliero

- Ogni P&L di trade chiuso è registrato (`register_trade_pnl`)
- Se il P&L del giorno ≤ −(equity × `MAX_DAILY_LOSS_PCT`, default 3%) →
  **trading sospeso fino a mezzanotte** (reset al cambio di data)
- Visibile nella dashboard (pagina Rischio & Esposizione)

## 4. Ciclo di vita ordini: mai posizioni nude

In `OrderManager.execute_generic_trade`:

1. **Entry market** (una limit non fillata lascerebbe SL/TP reduce-only
   rejected e, fillando dopo, una posizione SENZA stop — bug reale risolto
   a giu 2026)
2. **SL stop_market reduce-only con retry 3×** (pausa 0.5s); se fallisce
   tutte → **EMERGENCY CLOSE** reduce-only della posizione appena aperta
3. TP limit reduce-only (best effort)
4. SL/TP registrati nell'`OrderRegistry` → il management loop (30s) cancella
   gli ordini rimasti orfani dopo ogni chiusura (`check_orphan_orders`)

In più: `FailureHandler` chiude tutto se l'API resta giù oltre
`MAX_API_DOWN_SEC`; il Macro Core tiene uno stop disastro a -25% sul venue
per i crash a bot offline.

## 5. Vol-target sul Macro Core (C4)

```
expo = clip(MC_VOL_TARGET / vol_realizzata_30d, 0, 1)
       quantizzata a MC_EXPO_STEP (0.25) → bucket 0.25/0.50/0.75/1.0
```

Ribilancio solo quando il bucket cambia (churn minimo, ordini
`mc_rebal_up/down`). Risultato in equity sim 4y: maxDD di portafoglio
29.6% → 21.5%, Calmar 2.43 → 2.61, peggior anno 0.0%, a fronte di
rendimento +770% → +491%. **Adottato**; testati e bocciati: Kelly 0.25×
e de-risk su drawdown (entrambi Calmar peggiore).
Numeri completi: `microevolutive/PLAN_BULL_EVOLUTION.md` (repo privato) (sezione C4).

## 6. Equity e testnet

`get_total_equity()` = equity BTC + equity ETH convertite in USD al prezzo
indice. In **testnet** l'equity di sizing è cappata a $50.000: i fondi
faucet gonfierebbero le size oltre i limiti di mercato.

## Guardrail live (monitoraggio continuo)

| Condizione | Azione |
|---|---|
| PF rolling < 0.8 dopo ≥ 30 trade live | disattivare la strategia e rivalidare |
| DD strategia > 1.5× il maxDD di backtest | disattivare SUBITO |
| Ordine orfano / posizione senza SL in dashboard | investigare immediatamente |
