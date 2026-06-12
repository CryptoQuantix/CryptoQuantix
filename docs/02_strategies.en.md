# Active strategies — overview

> Updated: June 2026. CryptoQuantix runs **three quantitatively validated
> strategies** on 4 years of multi-cycle data (Jun 2022 → Jun 2026: bear,
> bull and bear again), with backtests executed on the **actual production
> code** — not a reimplementation — using realistic costs (0.20%
> roundtrip) and no lookahead.
>
> 🔒 **The complete operational specifications** (exact entry/exit rules
> and validated parameters) **are proprietary** and available under a
> commercial license agreement — see [license](#license-and-access).

All strategies implement the `BaseStrategy` plugin interface
(`scan` / `execute_entry` / `manage_positions`) and receive an
**injectable** data provider: the exact same code runs live and in
backtest, eliminating by construction the entire class of "the backtest
does one thing, live does another" bugs.

---

## The three strategies

| Strategy | Category | Validation (BTC, 4 years) |
|---|---|---|
| **Trend Breakdown** | Macro-gated two-sided tactical: breakdowns in bear phases, breakouts in bull phases | short +22 bps/trade PF 1.26 · long +68 bps PF 1.53 |
| **Funding Squeeze** | Contrarian deep-bear capitulation specialist (funding crowding) | +74 bps/trade PF 2.65 · ETH +64 bps PF 1.82 |
| **Macro Core** | Regime-following core position with disciplined exit and vol-targeting | +315%/4y vs +136% buy&hold, maxDD 24.7% |

Live instances: 5 (Trend Breakdown and Funding Squeeze on BTC+ETH, Macro
Core on BTC). Each side of each strategy is active ONLY on the market and
macro phase where it passed validation.

**Portfolio** (4-year equity simulation, all instances together): +491%
with 21.5% maxDD, Calmar 2.61, worst year 0.0% — after adopting
vol-targeting on the core position (tested and rejected on the data:
fractional Kelly and drawdown de-risking).

## Automatic 3-level gating

The system decides on its own what it is allowed to trade, and when:

| Level | Horizon | Mechanism |
|---|---|---|
| Macro | days-months | primary-trend phase filter: each side is structurally inactive in its adverse phase |
| Regime | hours | TREND/RANGE/COMPRESSION/EXPANSION classification with per-strategy rules |
| Performance | rolling | a strategy underperforming live gets disabled automatically |

Live guardrails: rolling profit factor below threshold after a minimum
trade sample → disable and re-validate; drawdown beyond 1.5× the backtest
maximum → disable immediately.

## The validation process (why the numbers can be trusted)

Before deployment, every strategy passes a strict pipeline:

1. **Backtest on the real code** — the data provider is injectable, the
   strategy code is identical between live and simulation
2. **4 years, multi-cycle** — the edge must survive bear, bull and
   transitions, not a single lucky phase
3. **Realistic costs** (fees + slippage) and **no lookahead**
4. Temporal **in-sample / out-of-sample**
5. **Robustness to neighboring parameters** — no edge that only lives on
   one magic combination
6. **Minimum profit factor** on the full sample

## The rejected strategies (transparency)

The same pipeline **rejected eight legacy strategies on the data** — they
remain in the codebase, disabled, with their verdicts documented:

| Strategy | 4-year verdict |
|---|---|
| Volume Breakout | PF 0.42-0.74 — no edge, negative in every phase and year |
| Mean Reversion (VWAP fade) | PF 0.28-0.53 |
| Liquidation Squeeze | by the time the cascade is visible, the move is over |
| Imbalance Scalp | fee-bound across 29k+ trades — zero gross edge |
| NY Brings | negative every single year (718 trades) |
| W/M Formation | non-structural edge (does not replicate cross-asset) |
| Smart Money | testable components already falsified |
| Iron Condor | options — out of project scope |

A system that publishes what does NOT work is a system whose method you
can verify.

## License and access

The code is **source-available** under a dual license: free for
noncommercial use (including trading your own personal capital), while
**any commercial use requires a paid license** — which includes access to
the complete operational specifications of the strategies and the full
validation reports.

Contact: **lantoniotrento@gmail.com**
