# Dataset di ricerca quantitativa

## btc_1m_4y/ — dataset multi-ciclo (COMMITTATO)
Candele 1m BTCUSDT Binance Futures, **12 giu 2022 → 11 giu 2026** (2.102.400 candele):
bear 2022, bull 2023-2025, bear 2025-26. Spezzato in chunk annuali (<11 MB
ciascuno) per stare nei limiti GitHub:

```
btc_1m_2022.csv.gz ... btc_1m_2026.csv.gz
colonne: t (ms epoch), o, h, l, c, v (volume), bv (taker buy volume)
```

Caricamento: `scripts/multicycle_research.py -> load_4y()` (concatena i chunk).
Refresh: `python scripts/download_multicycle.py` (riscrive i chunk).

## btc_funding_4y.json — funding rate 4 anni (COMMITTATO)
4.380 eventi `{t, rate}` (settlement ogni 8h). Stesso periodo del dataset 1m.

## Report di validazione (COMMITTATI)
- `multicycle_report.txt` — le 4 strategie vecchie per fase bull/bear (verdetto: zero edge)
- `candidates*_report.txt` — i round di ricerca (1-2-3: edge short 2025-26; 4: macro gate + lato long; 5: fix FundingSqueeze)
- `research_report.txt` — event study A-I sul dataset 270g
- `new_strategies_results.json` — output ultimo backtest del codice reale

## File NON committati (rigenerabili)
- `btc_1m_research.json.gz` + `btc_funding.json` — dataset 270g (sottoinsieme
  del 4y): `python scripts/download_research_data.py`
