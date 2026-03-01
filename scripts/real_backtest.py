#!/usr/bin/env python3
"""
Real backtest — 60 giorni di dati Binance Futures 1m BTCUSDT.

Dati reali:
  - 86,400 kline 1m da Binance Futures REST API (con cache locale)
  - buy_volume = taker buy base volume (aggressori in acquisto)
  - sell_volume = volume - buy_volume   (aggressori in vendita)

Proxy OHLCV per segnali L2 non disponibili storicamente:
  book_imbalance   = buy_vol / total_vol        (trade flow directional pressure)
  aggression_ratio = buy_vol / total_vol        (stesso indicatore, angolazione diversa)
  is_absorption    = (close>open AND sell>buy*1.2) OR (close<open AND buy>sell*1.2)
  is_liq_vacuum    = candle_range > 2 * rolling_avg_range  (proxy per gap nel libro)
  liq_buy_10m      = rolling-10m buy_vol con buy_ratio > 0.70 (short squeeze proxy)
  liq_sell_10m     = rolling-10m sell_vol con sell_ratio > 0.70 (long dump proxy)

Tutte e 4 le strategie possono ora generare segnali.
"""
import json
import logging
import os
import sys
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("real_backtest")
logging.getLogger("src.engine").setLevel(logging.WARNING)
logging.getLogger("src.strategies").setLevel(logging.WARNING)
logging.getLogger("src.backtest").setLevel(logging.WARNING)
logging.getLogger("strategy").setLevel(logging.WARNING)

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
SYMBOL         = "BTCUSDT"
DAYS           = 60
LIMIT_PER_CALL = 1500
INITIAL_EQUITY = 10_000.0
SLIPPAGE_PCT   = 0.0005    # 0.05%
TAKER_FEE      = 0.0005   # 0.05%
SCAN_EVERY_N   = 5         # scan ogni 5 candle (= ogni 5 min)
BINANCE_BASE   = "https://fapi.binance.com"
CACHE_PATH     = "data/btc_1m_cache.json"

# Proxy thresholds
ABS_RATIO         = 1.20   # sv > bv * 1.20 per absorption buy (e viceversa)
VACUUM_MULT       = 2.0    # range > VACUUM_MULT * avg_range = liquidity vacuum
VACUUM_WINDOW     = 20     # candle per calcolare avg_range
LIQ_DIRECTIONALITY = 0.70  # buy_ratio > 70% = potenziale short squeeze
LIQ_WINDOW_CANDLES = 10    # 10 minuti rolling window per liquidation proxy


# ------------------------------------------------------------------ #
# Data download + cache
# ------------------------------------------------------------------ #

def load_or_download_candles(symbol: str, days: int) -> List[Dict]:
    """Carica da cache se fresca (<1 giorno), altrimenti scarica da Binance."""
    if os.path.exists(CACHE_PATH):
        age_h = (time.time() - os.path.getmtime(CACHE_PATH)) / 3600
        if age_h < 23:
            try:
                with open(CACHE_PATH) as f:
                    candles = json.load(f)
                if len(candles) >= 80_000:
                    logger.info(f"Cache loaded: {len(candles):,} candles (age {age_h:.1f}h)")
                    return candles
            except Exception:
                pass

    candles = _download_klines(symbol, days)
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(candles, f)
    logger.info(f"Cache saved to {CACHE_PATH}")
    return candles


def _download_klines(symbol: str, days: int) -> List[Dict]:
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000

    s = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    e = datetime.fromtimestamp(end_ms   / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"Downloading {days}d {symbol} 1m klines  {s} -> {e}")

    all_candles: List[Dict] = []
    current_start = start_ms
    call_count    = 0

    while current_start < end_ms:
        url = (
            f"{BINANCE_BASE}/fapi/v1/klines"
            f"?symbol={symbol}&interval=1m"
            f"&startTime={current_start}&endTime={end_ms}"
            f"&limit={LIMIT_PER_CALL}"
        )
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as ex:
            logger.error(f"Download error (batch {call_count + 1}): {ex}")
            break

        if not data:
            break

        for k in data:
            vol = float(k[5])
            bv  = float(k[9])
            all_candles.append({
                "timestamp_ms": int(k[0]),
                "open":         float(k[1]),
                "high":         float(k[2]),
                "low":          float(k[3]),
                "close":        float(k[4]),
                "volume":       vol,
                "buy_volume":   bv,
                "sell_volume":  vol - bv,
            })

        call_count += 1
        if len(data) < LIMIT_PER_CALL:
            break
        current_start = int(data[-1][0]) + 60_000
        if call_count % 10 == 0:
            pct = (current_start - start_ms) / (end_ms - start_ms) * 100
            logger.info(f"  {len(all_candles):,} candles ({pct:.0f}%)")
        time.sleep(0.08)

    logger.info(f"Download complete: {len(all_candles):,} candles in {call_count} API calls")
    return all_candles


# ------------------------------------------------------------------ #
# Backtest structs
# ------------------------------------------------------------------ #

@dataclass
class BtTrade:
    trade_id:    str
    strategy:    str
    direction:   str
    entry_price: float
    sl_price:    float
    tp_price:    float
    quantity:    float
    entry_ts:    int
    regime:      str = "UNKNOWN"
    exit_price:  float = 0.0
    exit_ts:     int = 0
    exit_reason: str = ""
    pnl_usd:     float = 0.0
    r_multiple:  float = 0.0
    fees_usd:    float = 0.0
    duration_min: float = 0.0


def _compute_pnl(trade: BtTrade, exit_price: float) -> float:
    if trade.direction == "buy":
        gross = (exit_price - trade.entry_price) * trade.quantity
    else:
        gross = (trade.entry_price - exit_price) * trade.quantity
    entry_fee = trade.entry_price * trade.quantity * TAKER_FEE
    exit_fee  = exit_price        * trade.quantity * TAKER_FEE
    trade.fees_usd = entry_fee + exit_fee
    return gross - trade.fees_usd


def _check_exits(
    open_trades: List[BtTrade],
    high: float, low: float, ts: int,
) -> List[BtTrade]:
    closed = []
    for t in open_trades:
        if t.direction == "buy":
            if t.sl_price > 0 and low  <= t.sl_price:
                t.exit_price, t.exit_reason = t.sl_price, "sl"
            elif t.tp_price > 0 and high >= t.tp_price:
                t.exit_price, t.exit_reason = t.tp_price, "tp"
        else:
            if t.sl_price > 0 and high >= t.sl_price:
                t.exit_price, t.exit_reason = t.sl_price, "sl"
            elif t.tp_price > 0 and low  <= t.tp_price:
                t.exit_price, t.exit_reason = t.tp_price, "tp"
        if t.exit_reason:
            t.exit_ts = ts
            t.pnl_usd = _compute_pnl(t, t.exit_price)
            t.duration_min = (ts - t.entry_ts) / 60_000
            risk = abs(t.entry_price - t.sl_price)
            if risk > 0 and t.quantity > 0:
                delta = (t.exit_price - t.entry_price) * (1 if t.direction == "buy" else -1)
                t.r_multiple = delta / risk
            closed.append(t)
    return closed


# ------------------------------------------------------------------ #
# Backtest loop
# ------------------------------------------------------------------ #

def run_strategy_backtest(
    strategy_class,
    config,
    candles: List[Dict],
    symbol: str,
) -> List[BtTrade]:
    """
    Loop di backtest con proxy OHLCV completi:
      - book_imbalance + aggression_ratio: buy_vol/total_vol
      - is_absorption: close vs open + volume directional divergence
      - is_liq_vacuum: candle range vs rolling avg range
      - liq_buy/sell_volume_10m: rolling 10m window di flusso direzionale estremo
    """
    from src.engine.orderflow import OrderflowEngine
    from src.engine.regime import RegimeDetector
    from src.engine.scoring import ScoringEngine
    from src.backtest.backtest_engine import MockOrderManager
    from src.data.binance_ingestion import AggTrade

    of_engine       = OrderflowEngine(symbols=[symbol])
    regime_detector = RegimeDetector()
    scoring_engine  = ScoringEngine()
    mock_om         = MockOrderManager(slippage_pct=SLIPPAGE_PCT)

    deps = {
        "order_manager":    mock_om,
        "orderflow_engine": of_engine,
        "regime_detector":  regime_detector,
        "scoring_engine":   scoring_engine,
        "position_monitor": None,
        "risk_manager":     None,
        "data_ingestion":   None,
        "trade_logger":     None,
    }

    strategy = strategy_class(client=None, config=config, dependencies=deps)
    strategy.order_manager = mock_om
    if hasattr(strategy, "_min_signal_interval_sec"):
        strategy._min_signal_interval_sec = 0

    # Rolling state for OHLCV proxies
    range_window:    deque = deque(maxlen=VACUUM_WINDOW)
    liq_buy_window:  deque = deque(maxlen=LIQ_WINDOW_CANDLES)
    liq_sell_window: deque = deque(maxlen=LIQ_WINDOW_CANDLES)

    open_trades:   List[BtTrade] = []
    closed_trades: List[BtTrade] = []
    trade_counter  = 0

    for i, candle in enumerate(candles):
        ts    = candle["timestamp_ms"]
        op    = candle["open"]
        close = candle["close"]
        high  = candle["high"]
        low   = candle["low"]
        vol   = candle["volume"]
        bv    = candle["buy_volume"]
        sv    = candle["sell_volume"]

        if close <= 0:
            continue

        total_vol = bv + sv

        # ---- Compute OHLCV proxies ----
        buy_ratio  = bv / total_vol if total_vol > 0 else 0.5

        # Absorption: price moved against the dominant flow
        is_abs_buy  = (close > op) and (sv > bv * ABS_RATIO)   # rally despite net selling
        is_abs_sell = (close < op) and (bv > sv * ABS_RATIO)   # drop despite net buying
        is_absorption = is_abs_buy or is_abs_sell

        # Liquidity vacuum: abnormally wide candle range
        candle_range = high - low
        range_window.append(candle_range)
        avg_range = float(np.mean(range_window)) if range_window else candle_range
        is_liq_vacuum = (len(range_window) >= 5) and (candle_range > VACUUM_MULT * avg_range)

        # Liquidation proxy: rolling 10m of extreme directional flow
        if buy_ratio > LIQ_DIRECTIONALITY:
            liq_buy_window.append(bv)
            liq_sell_window.append(0.0)
        elif buy_ratio < (1 - LIQ_DIRECTIONALITY):
            liq_buy_window.append(0.0)
            liq_sell_window.append(sv)
        else:
            liq_buy_window.append(0.0)
            liq_sell_window.append(0.0)

        liq_buy_10m  = float(sum(liq_buy_window))
        liq_sell_10m = float(sum(liq_sell_window))

        # ---- Feed candle to OrderflowEngine ----
        # Feed N proportional trades so that aggr_buy/aggr_sell counts
        # reflect the buy/sell ratio — otherwise the engine always gets
        # 1 buy + 1 sell → aggression_ratio = 0.5 always.
        GRAN = 10   # synthetic trade count per candle
        buy_count  = max(1, round(buy_ratio * GRAN))
        sell_count = max(1, GRAN - buy_count)
        unit_bv = bv / buy_count  if buy_count  > 0 else 0
        unit_sv = sv / sell_count if sell_count > 0 else 0
        for j in range(buy_count):
            if unit_bv > 0:
                of_engine.update_from_trade(AggTrade(
                    symbol=symbol, trade_id=ts * 100 + j, price=close,
                    quantity=unit_bv, timestamp_ms=ts, is_buyer_maker=False,
                ))
        for j in range(sell_count):
            if unit_sv > 0:
                of_engine.update_from_trade(AggTrade(
                    symbol=symbol, trade_id=ts * 100 + 50 + j, price=close,
                    quantity=unit_sv, timestamp_ms=ts, is_buyer_maker=True,
                ))

        # ---- Inject all proxies into the live snapshot ----
        # aggression_ratio is now computed correctly by the engine (proportional trade counts)
        # book_imbalance, is_liq_vacuum, liq_buy/sell_volume NOT overwritten by flush_snapshot
        # oi_change_pct is NOT overwritten by flush_snapshot → proxy is preserved
        snap = of_engine._snapshots.get(symbol.upper())
        if snap and total_vol > 0:
            snap.book_imbalance      = buy_ratio
            snap.is_absorption       = is_absorption
            snap.is_liq_vacuum       = is_liq_vacuum
            snap.liq_buy_volume_10m  = liq_buy_10m
            snap.liq_sell_volume_10m = liq_sell_10m
            # OI proxy: when extreme directional vol spike occurs, OI is likely
            # decreasing (forced liquidations). Proxy for LiquidationSqueezeStrategy.
            vol_z = snap.volume_zscore
            if (buy_ratio > LIQ_DIRECTIONALITY and vol_z > 1.0) or \
               (buy_ratio < (1 - LIQ_DIRECTIONALITY) and vol_z > 1.0):
                snap.oi_change_pct = -1.0   # forced closes proxy
            else:
                snap.oi_change_pct = 0.0

        # ---- Check SL/TP on open trades ----
        closed = _check_exits(open_trades, high, low, ts)
        closed_trades.extend(closed)
        open_trades = [t for t in open_trades if t not in closed]

        # ---- Update regime every 15 candles (15 min) ----
        if i >= 30 and i % 15 == 0:
            hist = of_engine.get_candle_history(symbol, 60, n=50)
            if len(hist) >= 20:
                snap_data = of_engine.get_snapshot(symbol)
                cvd = snap_data.cvd_1m if snap_data else 0.0
                imb = snap_data.book_imbalance if snap_data else 0.5
                regime_detector.detect(hist, symbol=symbol, cvd=cvd, book_imbalance=imb)

        # ---- Scan strategy every SCAN_EVERY_N candles ----
        if i < 30 or i % SCAN_EVERY_N != 0 or open_trades:
            continue

        try:
            mock_om.fills.clear()
            signals = strategy.scan()
        except Exception as ex:
            logger.debug(f"scan error at {i}: {ex}")
            continue

        for signal in signals:
            if open_trades:
                break
            raw_price  = signal.get("price", close)
            direction  = signal.get("direction", "buy").lower()
            slip       = raw_price * SLIPPAGE_PCT
            fill_price = raw_price + slip if direction == "buy" else raw_price - slip

            trade_counter += 1
            t = BtTrade(
                trade_id    = f"bt_{trade_counter:04d}",
                strategy    = strategy.name,
                direction   = direction,
                entry_price = fill_price,
                sl_price    = signal.get("stop_loss", 0),
                tp_price    = signal.get("take_profit", 0),
                quantity    = signal.get("quantity", 0.001),
                entry_ts    = ts,
                regime      = signal.get("regime", "UNKNOWN"),
            )
            open_trades.append(t)

    # Chiudi eventuali trade rimasti aperti all'ultimo prezzo
    last_price = candles[-1]["close"] if candles else 0
    last_ts    = candles[-1]["timestamp_ms"] if candles else 0
    for t in open_trades:
        t.exit_price   = last_price
        t.exit_reason  = "end_of_data"
        t.exit_ts      = last_ts
        t.pnl_usd      = _compute_pnl(t, last_price)
        t.duration_min = (last_ts - t.entry_ts) / 60_000
        closed_trades.append(t)

    return closed_trades


# ------------------------------------------------------------------ #
# Metrics
# ------------------------------------------------------------------ #

def full_report(trades: List[BtTrade]) -> Dict:
    if not trades:
        return {"error": "no trades"}

    pnls   = [t.pnl_usd    for t in trades]
    r_mult = [t.r_multiple for t in trades]
    total  = len(trades)
    wins   = sum(1 for t in trades if t.pnl_usd > 0)

    equity   = INITIAL_EQUITY
    eq_curve = [equity]
    for t in sorted(trades, key=lambda x: x.entry_ts):
        equity += t.pnl_usd
        eq_curve.append(equity)

    final_equity = eq_curve[-1]
    arr   = np.array(eq_curve)
    peak  = np.maximum.accumulate(arr)
    dd    = (peak - arr) / peak * 100
    max_dd = float(np.max(dd))

    r_arr    = np.array(r_mult)
    downside = r_arr[r_arr < 0]
    down_std = float(np.std(downside)) if len(downside) > 0 else 1e-9
    sharpe   = float(np.mean(r_arr) / np.std(r_arr)) if np.std(r_arr) > 0 else 0.0
    sortino  = float(np.mean(r_arr)) / down_std if down_std > 0 else 0.0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))
    pf           = gross_profit / gross_loss if gross_loss > 0 else 999.0
    avg_win      = float(np.mean([p for p in pnls if p > 0])) if gross_profit > 0 else 0.0
    avg_loss     = float(np.mean([p for p in pnls if p < 0])) if gross_loss   > 0 else 0.0
    payoff       = avg_win / abs(avg_loss) if avg_loss != 0 else 999.0
    total_return = (final_equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    calmar       = total_return / max_dd if max_dd > 0 else 0.0

    consec_loss = max_consec = 0
    for t in trades:
        if t.pnl_usd < 0:
            consec_loss += 1
            max_consec   = max(max_consec, consec_loss)
        else:
            consec_loss  = 0

    by_exit: Dict[str, int] = {}
    by_regime: Dict[str, int] = {}
    for t in trades:
        by_exit[t.exit_reason] = by_exit.get(t.exit_reason, 0) + 1
        by_regime[t.regime]    = by_regime.get(t.regime, 0) + 1

    return {
        "total_trades":           total,
        "wins":                   wins,
        "losses":                 total - wins,
        "winrate_pct":            round(wins / total * 100, 1),
        "initial_equity":         INITIAL_EQUITY,
        "final_equity":           round(final_equity, 2),
        "total_pnl":              round(final_equity - INITIAL_EQUITY, 2),
        "total_return_pct":       round(total_return, 2),
        "max_drawdown_pct":       round(max_dd, 2),
        "sharpe":                 round(sharpe, 4),
        "sortino":                round(sortino, 4),
        "calmar":                 round(calmar, 4),
        "profit_factor":          round(pf, 3),
        "payoff_ratio":           round(payoff, 3),
        "expectancy_r":           round(float(np.mean(r_arr)), 4),
        "avg_win_usd":            round(avg_win, 2),
        "avg_loss_usd":           round(avg_loss, 2),
        "gross_profit":           round(gross_profit, 2),
        "gross_loss":             round(gross_loss, 2),
        "total_fees":             round(sum(t.fees_usd for t in trades), 2),
        "avg_duration_min":       round(float(np.mean([t.duration_min for t in trades])), 1),
        "max_consecutive_losses": max_consec,
        "by_exit":                by_exit,
        "by_regime":              by_regime,
    }


def regime_breakdown(trades: List[BtTrade]) -> Dict:
    grouped: Dict[str, list] = {}
    for t in trades:
        grouped.setdefault(t.regime, []).append(t)
    result = {}
    for regime, ts in grouped.items():
        pnls  = [t.pnl_usd    for t in ts]
        rmult = [t.r_multiple for t in ts]
        wins  = sum(1 for t in ts if t.pnl_usd > 0)
        result[regime] = {
            "trades":       len(ts),
            "winrate_pct":  round(wins / len(ts) * 100, 1),
            "avg_pnl":      round(float(np.mean(pnls)), 2),
            "expectancy_r": round(float(np.mean(rmult)), 4),
            "total_pnl":    round(float(sum(pnls)), 2),
        }
    return result


def print_report(name: str, m: Dict, rb: Dict):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    if "error" in m:
        print(f"  [NO TRADES] {m['error']}")
        return
    print(f"  Trades:         {m['total_trades']}  (W:{m['wins']} L:{m['losses']})")
    print(f"  Win Rate:       {m['winrate_pct']:.1f}%")
    print(f"  Total P&L:      ${m['total_pnl']:+,.2f}  ({m['total_return_pct']:+.2f}%)")
    print(f"  Max Drawdown:   {m['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe:         {m['sharpe']:.3f}")
    print(f"  Sortino:        {m['sortino']:.3f}")
    print(f"  Calmar:         {m['calmar']:.3f}")
    print(f"  Profit Factor:  {m['profit_factor']:.3f}")
    print(f"  Expectancy:     {m['expectancy_r']:+.4f}R")
    print(f"  Avg Win/Loss:   ${m['avg_win_usd']:,.2f} / ${m['avg_loss_usd']:,.2f}")
    print(f"  Max Loss Streak:{m['max_consecutive_losses']}")
    print(f"  Total Fees:     ${m['total_fees']:,.2f}")
    print(f"  Avg Duration:   {m['avg_duration_min']:.0f} min")
    by_exit = m.get("by_exit", {})
    print(f"  Exits:  TP={by_exit.get('tp',0)}  SL={by_exit.get('sl',0)}  EOD={by_exit.get('end_of_data',0)}")
    if rb:
        print(f"  --- Per Regime ---")
        for regime, s in sorted(rb.items(), key=lambda x: -x[1]["expectancy_r"]):
            print(f"    {regime:<15} N={s['trades']:3d}  WR={s['winrate_pct']:.0f}%  "
                  f"E={s['expectancy_r']:+.3f}R  P&L=${s['total_pnl']:+,.2f}")


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main():
    candles = load_or_download_candles(SYMBOL, DAYS)
    if not candles:
        logger.error("No candle data — aborting.")
        sys.exit(1)

    first = datetime.fromtimestamp(candles[0]["timestamp_ms"] / 1000, tz=timezone.utc)
    last  = datetime.fromtimestamp(candles[-1]["timestamp_ms"] / 1000, tz=timezone.utc)
    p0, p1 = candles[0]["close"], candles[-1]["close"]

    print(f"\n{'='*65}")
    print(f"  REAL BACKTEST — {SYMBOL}  ({len(candles):,} x 1m candles)")
    print(f"  Period  : {first.strftime('%Y-%m-%d')} -> {last.strftime('%Y-%m-%d')}")
    print(f"  BTC/USD : ${p0:,.2f} -> ${p1:,.2f}  ({(p1/p0-1)*100:+.1f}%)")
    print(f"  Capital : ${INITIAL_EQUITY:,.2f} | Slip: {SLIPPAGE_PCT*100:.2f}% | Fee: {TAKER_FEE*100:.2f}%")
    print(f"  Proxies : OBI=trade_flow | absorption=OHLCV | vacuum=range | liq=directional_vol")
    print(f"{'='*65}")

    from src.strategies.volume_breakout import VolumeBreakoutStrategy
    from src.strategies.mean_reversion import MeanReversionStrategy
    from src.strategies.liq_squeeze import LiquidationSqueezeStrategy
    from src.strategies.imbalance_scalp import ImbalanceScalpStrategy
    from config import (
        VolumeBreakoutConfig, MeanReversionConfig,
        LiqSqueezeConfig, ImbalanceScalpConfig,
    )

    strategies = [
        (VolumeBreakoutStrategy,     VolumeBreakoutConfig(name="Volume Breakout")),
        (MeanReversionStrategy,      MeanReversionConfig(name="Mean Reversion")),
        (LiquidationSqueezeStrategy, LiqSqueezeConfig(name="Liq Squeeze")),
        (ImbalanceScalpStrategy,     ImbalanceScalpConfig(name="Imbalance Scalp")),
    ]

    all_results = []
    for strategy_class, config in strategies:
        logger.info(f"Running: {config.name} ...")
        t0     = time.time()
        trades = run_strategy_backtest(strategy_class, config, candles, SYMBOL)
        elapsed = time.time() - t0
        m  = full_report(trades)
        rb = regime_breakdown(trades) if trades else {}
        all_results.append((config.name, trades, m, rb))
        print_report(config.name, m, rb)
        if "error" not in m:
            logger.info(f"  -> {len(trades)} trades in {elapsed:.1f}s")

    # Tabella comparativa
    print(f"\n{'='*75}")
    print("  STRATEGY COMPARISON")
    print(f"{'='*75}")
    print(f"  {'Strategy':<22} {'Trades':>6} {'WR%':>6} {'P&L':>10} {'Sharpe':>7} {'Calmar':>7} {'MaxDD%':>7}")
    print("  " + "-" * 71)
    for name, trades, m, _ in all_results:
        if "error" in m:
            print(f"  {name:<22}  --- {m['error']}")
        else:
            pnl = m.get("total_pnl", 0)
            print(
                f"  {name:<22} "
                f"{m.get('total_trades',0):>6d} "
                f"{m.get('winrate_pct',0):>5.1f}% "
                f"${pnl:>+9,.2f} "
                f"{m.get('sharpe',0):>7.3f} "
                f"{m.get('calmar',0):>7.3f} "
                f"{m.get('max_drawdown_pct',0):>6.2f}%"
            )
    print(f"{'='*75}\n")

    out = "backtest_results.json"
    export = [
        {"strategy": name, "metrics": m, "regime_breakdown": rb, "trade_count": len(trades)}
        for name, trades, m, rb in all_results
    ]
    with open(out, "w") as f:
        json.dump(export, f, indent=2, default=str)
    print(f"Results saved to: {out}\n")


if __name__ == "__main__":
    main()
