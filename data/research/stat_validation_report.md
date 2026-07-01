# Statistical Validation Report

Generated: 2026-06-22 13:37 UTC

## STEP 0 — Schema inspection

- `new_strategies_results.json`: summary only (no per-trade rows). Keys: ['Trend Breakdown', 'Funding Squeeze']. Fields per strategy: ['n', 'avg_net_bps', 'wr'].
- `c4_trades_cache.pkl`: tactical (222, 12), columns ['entry_ts', 'exit_ts', 'direction', 'entry', 'exit', 'reason', 'gross_pct', 'net_pct', 'r', 'hold_min', 'sl_dist_pct', 'strategy']; mc (9, 5), columns ['entry_ts', 'exit_ts', 'entry', 'net_pct', 'reason'].
  - tactical: `direction` -1=short +1=long; `net_pct`/`gross_pct` in **percent points** (bps = net_pct x 100); `strategy` in {TB, FS}; BTC-only combined run.
  - mc: roundtrip spans with `net_pct` (percent), no direction column.

Per-leg ETH / side splits are **not** in cached files — regenerated via `run()` on BTC/ETH datasets inside this script.


### A1-A3 Full sample (2022-06 -> 2026-06)

| Leg                |    N |  mean bps |      std |   WR% |    PF |      t |      p |           CI mean |           CI PF | flags |
|--------------------|------|-----------|----------|-------|-------|--------|--------|-------------------|-----------------|----------|
| TB_short_BTC       |  123 |     +22.1 |    241.0 |  44.7 |  1.26 |  +1.02 |  0.311 |         [-21,+67] |     [0.80,1.94] | t<2,PF~1 |
| TB_long_BTC        |   84 |     +67.8 |    556.7 |  20.2 |  1.53 |  +1.12 |  0.267 |        [-39,+192] |     [0.72,2.66] | t<2,PF~1 |
| TB_long_ETH        |   58 |    +183.3 |    637.9 |  31.0 |  2.32 |  +2.19 |  0.033 |        [+27,+354] |     [1.17,4.06] | - |
| FS_BTC             |   15 |     +74.1 |    177.5 |  53.3 |  2.65 |  +1.62 |  0.128 |        [-12,+162] |    [0.84,10.21] | N<30,t<2,PF~1 |
| FS_ETH             |   39 |     +63.9 |    255.2 |  51.3 |  1.82 |  +1.56 |  0.126 |        [-14,+144] |     [0.87,3.78] | t<2,PF~1 |
| MC_BTC             |    9 |   +2235.5 |   4334.6 |  66.7 |  9.45 |  +1.55 |  0.160 |       [+63,+5314] |   [1.13,120.06] | N<30,t<2 |
| TB+FS_portfolio    |  222 |     +42.9 |    388.6 |  36.0 |  1.43 |  +1.65 |  0.101 |          [-6,+97] |     [0.94,2.07] | t<2,PF~1 |

### A4 — Cost stress

| Leg | mult | mean bps | PF | BE mult |
|-----|------|----------|-----|---------|
| TB_short_BTC | 1.0 | +22.1 | 1.26 | 3.21 |
| TB_short_BTC | 1.5 | +17.1 | 1.19 | 3.21 |
| TB_short_BTC | 2.0 | +12.1 | 1.13 | 3.21 |
| TB_long_BTC | 1.0 | +67.8 | 1.53 | 7.78 |
| TB_long_BTC | 1.5 | +62.8 | 1.48 | 7.78 |
| TB_long_BTC | 2.0 | +57.8 | 1.43 | 7.78 |
| TB_long_ETH | 1.0 | +183.3 | 2.32 | 19.33 |
| TB_long_ETH | 1.5 | +178.3 | 2.26 | 19.33 |
| TB_long_ETH | 2.0 | +173.3 | 2.19 | 19.33 |
| FS_BTC | 1.0 | +74.1 | 2.65 | 8.41 |
| FS_BTC | 1.5 | +69.1 | 2.47 | 8.41 |
| FS_BTC | 2.0 | +64.1 | 2.30 | 8.41 |
| FS_ETH | 1.0 | +63.9 | 1.82 | 7.39 |
| FS_ETH | 1.5 | +58.9 | 1.74 | 7.39 |
| FS_ETH | 2.0 | +53.9 | 1.65 | 7.39 |
| MC_BTC | 1.0 | +2235.5 | 9.45 | n/a |
| MC_BTC | 1.5 | +2230.5 | 9.38 | n/a |
| MC_BTC | 2.0 | +2225.5 | 9.31 | n/a |
| TB+FS_portfolio | 1.0 | +42.9 | 1.43 | 5.29 |
| TB+FS_portfolio | 1.5 | +37.9 | 1.37 | 5.29 |
| TB+FS_portfolio | 2.0 | +32.9 | 1.31 | 5.29 |

### A5 — MacroCore beta attribution

- OLS daily: r_MC = alpha + beta * r_BTC  (n=1459 days)
- beta = -0.024
- alpha (daily) = 0.1197%
- alpha (annualized) = +43.7%
- t-stat(alpha) = 2.30, p = 0.0218
- R² = 0.001
- MC total return = +315.4%
- BTC buy&hold = +136.4%
- Approx beta contribution = -3.2%
- Cumulative alpha (hedged) = +330.6%

**Conclusione:** del +315% MC, circa
-3% è spiegabile come esposizione beta
(beta~-0.02 * B&H BTC); la componente alpha cumulata
hedged è +330.6% (alpha giornaliero
significativo a 5%).


### A6 — Portfolio path-dependent metrics

| Config | Total% | CAGR% | maxDD% | Sharpe | Sortino | Calmar |
|--------|--------|-------|--------|--------|---------|--------|
| baseline_fix1_mc_fixed | +769.5 | 71.8 | 29.6 | 1.46 | 2.12 | 2.43 |
| adopted_fix1_volT30 | +491.5 | 56.0 | 21.5 | 1.56 | 2.53 | 2.61 |

### A7 — Multiple testing / Deflated Sharpe

- Estimated trials (conservative): **39**
- Portfolio Sharpe (adopted volT30): **1.56**
- Expected max SR under null (SR*): **2.18**
- DSR P(SR > 0 | selection bias): **0.0%**

### B — OOS TEST period only

| Leg                |    N |  mean bps |      std |   WR% |    PF |      t |      p |           CI mean |           CI PF | flags |
|--------------------|------|-----------|----------|-------|-------|--------|--------|-------------------|-----------------|----------|
| TB_short_BTC       |   76 |     +48.7 |    224.5 |  50.0 |  1.71 |  +1.89 |  0.062 |          [-1,+99] |     [0.99,2.87] | t<2,PF~1 |
| TB_long_BTC        |    9 |     -12.3 |    230.5 |  22.2 |  0.87 |  -0.16 |  0.877 |       [-127,+144] |     [0.00,3.49] | N<30,t<2,PF~1 |
| TB_long_ETH        |    7 |    +142.4 |    732.5 |  28.6 |  1.89 |  +0.51 |  0.625 |       [-234,+705] |     [0.00,9.31] | N<30,t<2,PF~1 |
| FS_BTC             |   13 |     +53.1 |    182.1 |  46.2 |  2.03 |  +1.05 |  0.314 |        [-39,+151] |     [0.52,8.04] | N<30,t<2,PF~1 |
| FS_ETH             |    2 |    +213.6 |    168.1 | 100.0 |   inf |  +1.80 |  0.323 |        [+95,+332] |       [nan,nan] | N<30,t<2 |
| MC_BTC             |    2 |    -457.6 |     63.0 |   0.0 |  0.00 | -10.27 |  0.062 |       [-502,-413] |     [0.00,0.00] | N<30 |
| TB+FS_portfolio    |   98 |     +43.7 |    218.6 |  46.9 |  1.63 |  +1.98 |  0.051 |          [+2,+88] |     [1.02,2.60] | t<2 |

### B — In-sample vs OOS comparison

| Leg | IS mean bps | OOS mean bps | IS PF | OOS PF | IS t | OOS t | degradation |
|-----|-------------|--------------|-------|--------|------|-------|-------------|
| TB_short_BTC | +22.1 | +48.7 | 1.26 | 1.71 | +1.02 | +1.89 | OOS better/similar |
| TB_long_BTC | +67.8 | -12.3 | 1.53 | 0.87 | +1.12 | -0.16 | OOS worse |
| TB_long_ETH | +183.3 | +142.4 | 2.32 | 1.89 | +2.19 | +0.51 | OOS worse |
| FS_BTC | +74.1 | +53.1 | 2.65 | 2.03 | +1.62 | +1.05 | OOS worse |
| FS_ETH | +63.9 | +213.6 | 1.82 | inf | +1.56 | +1.80 | OOS better/similar |
| MC_BTC | +2235.5 | -457.6 | 9.45 | 0.00 | +1.55 | -10.27 | OOS worse |
| TB+FS_portfolio | +42.9 | +43.7 | 1.43 | 1.63 | +1.65 | +1.98 | OOS better/similar |

> **Nota metodologica:** parametri fissi ai default `.env`, scelti vedendo l'intero storico 2022–2026. Questo OOS è un *sanity check semi-contaminato*, non prova definitiva di generalizzazione.


### Verdetto per gamba

| Leg | Verdict | Rationale |
|-----|---------|-----------|
| TB_short_BTC | **PLAUSIBILE** | t=1.02; PF CI includes 1 |
| TB_long_BTC | **PLAUSIBILE** | t=1.12; PF CI includes 1 |
| TB_long_ETH | **PLAUSIBILE** | passes filters |
| FS_BTC | **PLAUSIBILE** | N=15; t=1.62; PF CI includes 1 |
| FS_ETH | **PLAUSIBILE** | t=1.56; PF CI includes 1 |
| MC_BTC | **PLAUSIBILE** | N=9; t=1.55; low R2 vs BTC |
| TB+FS_portfolio | **PLAUSIBILE** | t=1.65; PF CI includes 1 |