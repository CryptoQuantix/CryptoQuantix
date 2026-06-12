---
search:
  exclude: true
---

# Strategie — specifiche operative complete (RISERVATO)

> ⚠️ **PAGINA RISERVATA** — non linkata dalla navigazione, esclusa da
> ricerca e sitemap. Non condividere l'URL. Il contenuto è coperto dalla
> licenza CryptoQuantix: l'uso commerciale richiede accordo scritto.
>
> Fonte di verità per i numeri: `microevolutive/PLAN_BULL_EVOLUTION.md`
> e `data/research/` nel repo privato. Validazione: 4 anni BTCUSDT/ETHUSDT
> 1m (giu 2022 → giu 2026), backtest sul codice reale, costi 0.20%
> roundtrip, nessun lookahead.

Tutte le strategie implementano l'interfaccia immutabile `BaseStrategy`
(`scan` / `execute_entry` / `manage_positions`) e ricevono il
`KlineProvider` **iniettabile**: lo stesso identico codice gira live e in
backtest.

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

### Parametri validati (.env)

| Variabile | Default | Note |
|---|---|---|
| `TB_SYMBOLS` | BTCUSDT,ETHUSDT | un'istanza per simbolo |
| `TB_SHORT_SYMBOLS` | BTCUSDT | short solo dove validato |
| `TB_LOOKBACK_H` | 48 | Donchian low short (barre 1h) |
| `TB_LOOKBACK_LONG_H` | 168 | Donchian high long (7 giorni) |
| `TB_SMA_H` | 48 | filtro trend orario |
| `TB_SL_ATR_MULT` | 2.0 | stop = 2×ATR(1h,14) |
| `TB_RR_RATIO` | 2.0 | TP short = 2R |
| `TB_RR_LONG` | 0 | 0 = nessun TP sui long |
| `TB_MAX_HOLD_HOURS` | 24 | time exit short |
| `TB_MAX_HOLD_LONG_HOURS` | 168 | time exit long |
| `TB_FLOW_CONFIRM` | 0.50 | gate buy_ratio |
| `TB_MACRO_SMA_DAYS` | 200 | gate macro daily |

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
-23 bps in bull e sanguinava nelle transizioni di trend.

### Parametri validati (.env)

| Variabile | Default | Note |
|---|---|---|
| `FS_SYMBOLS` | BTCUSDT,ETHUSDT | |
| `FS_FUNDING_THRESHOLD` | 0.0001 | 0.01%/8h = cap exchange su BTC |
| `FS_SMA_H` | 48 | prezzo sotto SMA48 oraria |
| `FS_SL_ATR_MULT` | 2.0 | |
| `FS_TP_RR` | 2.0 | |
| `FS_MAX_HOLD_HOURS` | 24 | |
| `FS_COOLDOWN_HOURS` | 8 | un trade per finestra funding |
| `FS_MACRO_SMA_DAYS` | 200 | gate bear |
| `FS_SLOPE_DAYS` | 30 | SMA200d più bassa di 30gg fa |
| `FS_ENTRY_WINDOW_MIN` | 60 | entra solo dopo il settlement |

---

## 3. Macro Core (`src/strategies/macro_core.py`)

**Posizione core long di regime** (hold settimane/mesi).

- **Entry**: close daily > SMA200d (una volta per barra daily chiusa)
- **Exit**: chandelier — close daily < (max close dall'entry − 5×ATR20d).
  Esce dal blow-off top ~5 ATR sotto il picco, mesi prima della croce
  SMA200 che costava -17% alla versione naive.
- **Stop disastro** sul venue a entry×(1−25%).
- **Vol-target 30%**: esposizione = clip(0.30 / vol realizzata 30d, 0, 1)
  quantizzata a step 0.25; ribilancio solo al cambio di bucket.
- **Stato persistente** (`data/macro_core_state.json`).

Validazione BTC: **+315%/4y vs +136% buy&hold, maxDD 24.7%, 9 trade**,
2025 -1%. Plateau robusto k∈[4.5, 6]. **ETH: BOCCIATA** (= buy&hold con
maxDD 58%) → solo BTC.

### Parametri validati (.env)

| Variabile | Default | Note |
|---|---|---|
| `MC_SYMBOLS` | BTCUSDT | solo BTC (ETH bocciata) |
| `MC_SMA_DAYS` | 200 | filtro macro daily |
| `MC_ATR_DAYS` | 20 | ATR per il chandelier |
| `MC_CHANDELIER_K` | 5.0 | plateau robusto 4.5-6.0 |
| `MC_DISASTER_SL_PCT` | 0.25 | stop venue -25% |
| `MC_EXPOSURE_FRACTION` | 1.0 | size core = equity × frazione |
| `MC_VOL_TARGET` | 0.30 | vol-target annualizzata (0 = off) |
| `MC_VOL_LOOKBACK_DAYS` | 30 | finestra vol realizzata |
| `MC_EXPO_STEP` | 0.25 | bucket di esposizione |

---

## Portafoglio

Equity sim 4y delle 5 istanze insieme: baseline +770% maxDD 29.6%;
**con vol-target 30% su MC (adottato): +491%, maxDD 21.5%, Calmar 2.61,
peggior anno 0.0%**. Kelly 0.25× e de-risk su DD testati e BOCCIATI.

Guardrail live: PF rolling < 0.8 dopo ≥30 trade → disattivare e
rivalidare; DD > 1.5× il maxDD di backtest → disattivare subito.
