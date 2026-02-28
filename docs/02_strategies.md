# Trading Strategies Documentation

This document details the logic, parameters, and usage of the active strategies in Coinmaker.

## 1. Smart Money Strategy (`src/strategies/smart_money.py`)
**Goal**: Follow "Whales" by tracking large transactions on Binance and entering in the same direction on Deribit.

### Logic
1.  **Whale Monitoring**: Connects to Binance WebSocket (`aggTrade`).
2.  **Filtering**: Filters trades larger than `SM_WHALE_MIN_VALUE` (e.g., $500,000).
3.  **Absorption Detection**: Checks if large volume is absorbed by limit orders without moving price (Iceberg detection).
4.  **Signal**:
    - **Long**: High buying volume + price stability (Absorption) or Breakout.
    - **Short**: High selling volume + price stability.
5.  **Execution**: Market order on Deribit.

### Key Parameters (`.env`)
- `SM_WHALE_MIN_VALUE`: Minimum USD value to consider a trade a "Whale" (Default: 500000).
- `SM_TIME_WINDOW_START/END`: Trading hours (e.g., 14-17 UTC).
- `SM_ABSORPTION_MIN_VOL`: Volume threshold for absorption logic.

---

## 2. W/M Formation Strategy (`src/strategies/wm_formation.py`)
**Goal**: Identify Reversal patterns (W-Bottoms for Longs, M-Tops for Shorts) confirmed by Vector Candles.

### Logic
1.  **Pattern Recognition**: Scans for price structures resembling 'W' or 'M' on `15m` timeframe.
2.  **PVSRA Confirmation**: Uses **Vector Candles** (Volume > 150/200% average) to confirm market maker intent at the peaks/troughs.
3.  **Modes**:
    - **Reclaim**: Wait for price to reclaim the structural level (neckline).
    - **Breakout**: Enter on the break of the formation.
4.  **Filters**:
    - **RSI**: Checks for divergence or extreme levels.
    - **Trend**: Optional EMA trend filter (200/800 EMA).

### Key Parameters (`.env`)
- `WM_DERIBIT_SYMBOL`: Instrument to trade.
- `WM_PRIMARY_TIMEFRAME`: Timeframe to find patterns (Default: 15m).
- `WM_ENTRY_MODE`: `reclaim` or `breakout`.

---

## 3. NY Brings Strategy (`src/strategies/brings_strategy.py`)
**Goal**: Trade the reversal of the move created during the London/New York overlap manipulation hour (15:00 - 16:00 CET).

### Logic
1.  **Session Analysis**: Monitors the **"Brings" session** (15:00 - 16:00 CET/Europe/Rome).
2.  **Bias Determination**:
    - Counts **Vector Candles** (PVSRA) during this hour.
    - **Bias Long**: If Market Makers dumped (Red Vectors) > Pumped.
    - **Bias Short**: If Market Makers pumped (Green Vectors) > Dumped.
3.  **Entry Trigger (Confirmation)**:
    - Waits for a **Breakout** of the Vector Candle's High (for Long) or Low (for Short) *after* 16:00 CET.
    - This confirms the reversal has started.
4.  **Management**:
    - **Stop Loss**: Set at Session Low (Long) or Session High (Short).
    - **Trailing Stop**: Dynamic trailing (Activates at +0.5% profit, trails by 0.5%).

### Key Parameters (`.env`)
- `BRINGS_ENABLED`: `true` to enable.
- `BRINGS_TIMEZONE`: `Europe/Rome` (Critical for session timing).
- `BRINGS_TIMEFRAME`: `5m` (Timeframe to analyze vectors).
