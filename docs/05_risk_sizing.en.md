# Risk management — sizing, portfolio caps, kill switch

> Updated: June 2026. Implementation: `src/core/risk_manager.py`.

Risk is managed on **four independent levels**: per-trade (sizing),
per-portfolio (gross cap + max positions), per-day (kill switch) and
per-position (never without a stop on the venue).

## 1. Per-trade sizing: dynamic 3-factor

`RiskManager.calculate_dynamic_size()` — used by the tactical strategies:

```
base_risk = equity × BASE_RISK_PCT          (default 1%)
adj_risk  = base_risk × vol_scalar × regime_scalar × kelly_scalar
quantity  = adj_risk / |entry − SL|
```

| Factor | Values |
|---|---|
| Volatility (ATR percentile) | <30 → 1.0 · 30-70 → 0.75 · ≥70 → 0.50 |
| Regime | TREND 1.0 · RANGE 0.80 · EXPANSION 0.70 · COMPRESSION 0.60 · UNKNOWN 0.70 |
| Fractional Kelly | kelly = 2×WR−1, clipped [0.05, 0.25], normalized /0.25 |

Final caps applied in cascade: effective leverage ≤ 10×, then the
**aggregate gross exposure cap** (below). The core position does not use
the 3-factor model: its size is equity × exposure fraction × vol-target
bucket, still subject to the gross cap.

## 2. Portfolio caps (multi-strategy anti-oversizing)

With 5 active instances, multiple strategies can open positions at the
same time. Two limits:

- **`MAX_GROSS_EXPOSURE=1.5`**: the sum of ABSOLUTE notional of all open
  futures positions ≤ 1.5 × equity. Every new size is capped to the
  remaining headroom; at the cap, new entries are blocked.
- **`MAX_OPEN_TRADES=3`**: maximum number of venue positions.

`can_open_new_position()` is the single gate: kill switch → max
positions → gross cap. Structural note: the macro gates make OPPOSITE
positions on the same instrument impossible — no netting conflicts on a
netted venue.

## 3. Daily kill switch

- Every closed trade's P&L is registered
- If the day's P&L ≤ −(equity × `MAX_DAILY_LOSS_PCT`, default 3%) →
  **trading suspended until midnight** (resets on date change)
- A **manual kill switch** is also available from the dashboard (flag
  file honored by the RiskManager)
- Visible in the dashboard (Risk & Exposure page)

## 4. Order lifecycle: never naked positions

In `OrderManager.execute_generic_trade`:

1. **Market entry** (an unfilled limit would leave rejected reduce-only
   SL/TP orders and, filling later, a position WITHOUT a stop — a real
   bug found and fixed in June 2026)
2. **Reduce-only stop_market SL with 3× retry**; if all fail →
   **EMERGENCY CLOSE** of the just-opened position
3. Reduce-only limit TP (best effort)
4. SL/TP registered in the `OrderRegistry` → the management loop (30s)
   cancels orphaned orders after every close

Additionally: the `FailureHandler` closes everything if the API stays
down too long; the core position keeps a venue disaster stop for crashes
while the bot is offline.

## 5. Vol-targeting on the core position

```
expo = clip(vol_target / realized_vol, 0, 1)
       quantized to discrete buckets (rebalance only on bucket change)
```

Result in the 4-year equity simulation: portfolio maxDD 29.6% → 21.5%,
Calmar 2.43 → 2.61, worst year 0.0%. **Adopted**; tested and rejected:
fractional Kelly and drawdown-triggered de-risking (both worsened
Calmar).

## 6. Equity and testnet

Total equity = BTC + ETH equity converted to USD at index prices. On
**testnet**, sizing equity is capped at $50,000 (faucet funds would
inflate sizes beyond market limits).

## Live guardrails (continuous monitoring)

| Condition | Action |
|---|---|
| Rolling PF < 0.8 after ≥ 30 live trades | disable the strategy and re-validate |
| Strategy DD > 1.5× backtest maxDD | disable IMMEDIATELY |
| Orphan order / SL-less position in the dashboard | investigate immediately |
