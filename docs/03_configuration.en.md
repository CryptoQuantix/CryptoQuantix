# Configuration — the `.env` file

!!! info "Structure"

    The `.env` is organized in three blocks: **operational** (API, risk,
    monitoring), **ACTIVE STRATEGIES** (validated parameters — do not
    touch without re-validating) and **DISABLED STRATEGIES** (rejected
    on the data, verdict in the comments). The bot reads the `.env` ONLY
    at startup: every change requires a restart.

## Operational block

```env
# Deribit
DERIBIT_API_KEY=...           # never commit; the dashboard never shows them
DERIBIT_API_SECRET=...
DERIBIT_ENV=test              # test | prod

# Risk management (see 05_risk_sizing.md)
INITIAL_EQUITY=10000
BASE_RISK_PCT=0.01            # 1% risk per tactical trade
MAX_DAILY_LOSS_PCT=0.03       # kill switch after -3% daily
MAX_OPEN_TRADES=3             # max open positions on the venue
MAX_GROSS_EXPOSURE=1.5        # aggregate gross notional max 1.5x equity

# Monitoring
MONITORING_INTERVAL_MINUTES=15   # signal scan frequency
HEALTH_CHECK_INTERVAL_SEC=5
MAX_API_DOWN_SEC=30              # emergency close after 30s of API down
LOG_LEVEL=INFO

# Telegram (optional, empty = disabled)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## Active strategies

Each strategy is enabled with `TB_ENABLED` / `FS_ENABLED` / `MC_ENABLED`
and has its own parameter block in the `.env` (prefixes `TB_`, `FS_`,
`MC_`). The defaults are the values **validated over the 4 years**:
changing a parameter means leaving the validation → re-run the pipeline
before trusting any result.

### Multi-symbol
`TB_SYMBOLS` / `FS_SYMBOLS` / `MC_SYMBOLS` accept a list
(`BTCUSDT,ETHUSDT`): the bot creates ONE INSTANCE per symbol with the
derived Deribit instrument (`ETHUSDT` → `ETH-PERPETUAL`). Each side of
each strategy is enabled only on the symbols where validation passed.

!!! warning "🔒 Proprietary parameters"

    **The complete strategy parameter tables** (lookbacks, thresholds,
    multipliers and their validated ranges) **are proprietary** —
    available under the commercial license (contact:
    lantoniotrento@gmail.com). The dashboard editor still exposes them
    to the operator with the validated ranges as bounds.

## Disabled strategies

All with `*_ENABLED=false` and the validation verdict in the `.env`
comments. **Do not re-enable without a full new validation.**

```env
VB_ENABLED=false        # Volume Breakout : PF 0.42-0.74 — no edge
MR_ENABLED=false        # Mean Reversion  : PF 0.28-0.53
LIQ_ENABLED=false       # Liq Squeeze     : PF 0.06-0.30
IS_ENABLED=false        # Imbalance Scalp : fee-bound, PF 0.18-0.50
BRINGS_ENABLED=false    # NY Brings       : PF 0.64, negative every year
WM_ENABLED=false        # W/M Formation   : non-structural edge
STRATEGY_SMART_MONEY_ENABLED=false
STRATEGY_IRON_CONDOR_ENABLED=false   # options, out of project scope
```

## Notes

- `Config.load_strategies()` is the single point that translates the
  `.env` into instances: the dashboard uses the same function, so it sees
  exactly the instances the bot builds.
- Testnet: sizing equity is capped at $50k (testnet faucet funds inflate
  equity and would produce out-of-scale orders).
- Config validation at startup: missing keys or an invalid `DERIBIT_ENV`
  block the bootstrap.
