# Configuration Documentation

The bot is configured primarily via the `.env` file. This allows for separation of secrets (API Keys) and tunable trading parameters.

## Core Configuration

| Variable | Description | Example |
| :--- | :--- | :--- |
| `DERIBIT_API_KEY` | Your Deribit API Key | `728HjK...` |
| `DERIBIT_API_SECRET` | Your Deribit API Secret | `882...` |
| `DERIBIT_ENV` | Environment (`test` or `prod`) | `test` |
| `LOG_LEVEL` | Logging verbosity (`INFO`, `DEBUG`) | `INFO` |

## Strategy Enablement
Control which strategies are active. All disabled strategies are skipped during startup.

```ini
STRATEGY_SMART_MONEY_ENABLED=true  # Enable Smart Money
WM_ENABLED=true                    # Enable W/M Formation
BRINGS_ENABLED=true                # Enable NY Brings
```

## Strategy Parameters

### Smart Money
| Variable | Description | Default |
| :--- | :--- | :--- |
| `SM_WHALE_MIN_VALUE` | Minimum trade size (USD) to track | `500000` |
| `SM_TIME_WINDOW_START` | Start hour (UTC) | `14` |
| `SM_TIME_WINDOW_END` | End hour (UTC) | `17` |
| `SM_BINANCE_SYMBOL` | Source symbol for volume | `BTC/USDT` |

### W/M Formation
| Variable | Description | Default |
| :--- | :--- | :--- |
| `WM_DERIBIT_SYMBOL` | Instrument to trade | `BTC-PERPETUAL` |
| `WM_PRIMARY_TIMEFRAME`| Timeframe for pattern detection | `15m` |
| `WM_RISK_PER_TRADE_PCT`| Portfolio risk per trade | `0.02` (2%) |

### NY Brings Strategy
| Variable | Description | Default |
| :--- | :--- | :--- |
| `BRINGS_DERIBIT_SYMBOL`| Instrument to trade | `BTC-PERPETUAL` |
| `BRINGS_TIMEZONE` | Timezone for definition of "Brings" hour | `Europe/Rome` |
| `BRINGS_TIMEFRAME` | Timeframe for vector analysis (5m rec.) | `5m` |
| `BRINGS_STOP_LOSS_BUFFER`| Buffer beyond session High/Low | `0.002` (0.2%) |
| `BRINGS_TAKE_PROFIT_RATIO`| RR Ratio (Legacy, replaced by Trailing) | `1.5` |
