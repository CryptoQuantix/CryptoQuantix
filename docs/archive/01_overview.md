# Coinmaker Bot - Architecture Overview

## Introduction
Coinmaker is a modular, multi-strategy trading bot designed for **Deribit** (Futures/Options) and **Binance** (Data Analysis). It is built in Python and runs in a Dockerized environment.

## 1. Core Architecture
The bot operates on a main event loop orchestrated by `TradingBot` class. It separates concerns into distinct modules for API interaction, risk management, order execution, and strategy logic.

### Directory Structure
```
src/
├── core/                  # System core components
│   ├── deribit_client.py  # REST/WebSocket wrapper for Deribit
│   ├── order_manager.py   # Order placement and tracking
│   ├── position_monitor.py# Real-time position updates
│   ├── risk_manager.py    # Global risk checks (Equity, Drawdown)
│   └── state_manager.py   # State persistence (optional)
├── strategies/            # Trading strategies
│   ├── base_strategy.py   # Abstract Base Class
│   ├── wm_formation.py    # W/M Pattern Strategy
│   ├── brings_strategy.py # NY Brings Strategy
│   ├── smart_money.py     # Whale/Volume Analysis
│   └── pvsra_analyzer.py  # Volume spread analysis tool
└── trading_bot.py         # Main entry point and orchestrator
```

## 2. Key Components

### TradingBot (`src/trading_bot.py`)
- **Role**: Conductor.
- **Responsibilities**:
  - Initializes connections (Deribit Client).
  - Loads configurations from `.env`.
  - Instantiates enabled strategies.
  - Runs the main loop (`while True`) scheduling scans and position management tasks.

### DeribitClient (`src/core/deribit_client.py`)
- **Role**: Interface.
- **Responsibilities**:
  - Authenticates with API Key/Secret.
  - Wraps private endpoints (`buy`, `sell`, `get_positions`).
  - Fetches public market data (Orderbook, Ticker).

### OrderManager (`src/core/order_manager.py`)
- **Role**: Execution.
- **Responsibilities**:
  - Handles order placement logic (Market/Limit).
  - Manages Stop Loss and Take Profit orders.
  - Can update/cancel existing orders.

### RiskManager (`src/core/risk_manager.py`)
- **Role**: Guardian.
- **Responsibilities**:
  - Calculates position sizing based on Equity.
  - Enforces Max Drawdown limits.
  - Checks Max Open Positions.

## 3. Workflow
1. **Startup**: Bot loads `.env`, connects to Deribit.
2. **Strategy Init**: Strategies (`W/M`, `Brings`, `SmartMoney`) are initialized with their specific configs.
3. **Loop**:
   - **Scan**: Every X seconds, each strategy's `scan()` method is called.
   - **Signal**: If `scan()` returns a signal, `TradingBot` validates it via `RiskManager`.
   - **Execute**: If valid, `OrderManager` executes the trade.
   - **Manage**: Strategies `manage_positions()` are called to update Trailing Stops or check exits.
