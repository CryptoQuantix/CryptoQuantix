#!/usr/bin/env python3
"""
dry_run_orderflow.py -- Tests the orderflow + regime pipeline with live Binance data.

What it tests:
  1. OrderflowEngine: delta, CVD, VWAP, aggression ratio, volume Z-score
  2. OrderBookEngine: imbalance, liquidity vacuum, Kyle's Lambda
  3. RegimeDetector: regime classification from real candles
  4. ScoringEngine: strategy scoring in different regimes
  5. MarketSnapshot generation and format

Run:
    python scripts/dry_run_orderflow.py
    python scripts/dry_run_orderflow.py --symbol ETHUSDT --duration 120
"""
import argparse
import asyncio
import logging
import sys
import time

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dry_run_orderflow")


async def run_orderflow_dry_run(symbol: str = "BTCUSDT", duration_sec: int = 60):
    print("\n" + "=" * 60)
    print("DRY RUN: ORDERFLOW + REGIME ENGINE")
    print(f"Symbol: {symbol} | Duration: {duration_sec}s")
    print("=" * 60)

    # 1. Import check
    print("\n[1/5] Checking imports...")
    try:
        from src.data.binance_ingestion import BinanceDataIngestion
        from src.data.orderbook_engine import OrderBookEngine
        from src.engine.orderflow import OrderflowEngine
        from src.engine.regime import RegimeDetector, Regime
        from src.engine.scoring import ScoringEngine, TradeResult
        from datetime import datetime, timezone
        print("  [OK] All engine modules imported")
    except ImportError as e:
        print(f"  [FAIL] Import error: {e}")
        return False

    # 2. Initialize
    print("\n[2/5] Initializing engines...")
    ingestion = BinanceDataIngestion(
        symbols=[symbol],
        persist_to_db=False,
        oi_poll_interval_sec=15,
    )
    orderbook = OrderBookEngine(symbols=[symbol])
    orderflow = OrderflowEngine(symbols=[symbol])
    regime_detector = RegimeDetector()
    scoring = ScoringEngine(persistence_path="data/test_scoring.json")

    # Seed scoring with some mock history
    for i in range(10):
        scoring.record_result(TradeResult(
            strategy_name="VolumeBreakoutStrategy",
            entry_time=datetime.now(timezone.utc).isoformat(),
            exit_time=datetime.now(timezone.utc).isoformat(),
            r_multiple=1.2 if i % 2 == 0 else -1.0,
            pnl_usd=100.0 if i % 2 == 0 else -80.0,
            regime="EXPANSION",
            win=i % 2 == 0,
        ))
    print("  [OK] Engines initialized with mock scoring data")

    # 3. Start data streams
    print(f"\n[3/5] Starting streams ({duration_sec}s)...")
    await ingestion.start()

    async def route_data():
        while True:
            try:
                depth = ingestion.depth_queue.get_nowait()
                orderbook.apply_update(depth)
                snap = orderbook.get_snapshot(depth.symbol)
                if snap:
                    orderflow.update_from_book(snap)
            except Exception:
                pass

            try:
                trade = ingestion.trade_queue.get_nowait()
                orderflow.update_from_trade(trade)
            except Exception:
                pass

            await asyncio.sleep(0.005)

    route_task = asyncio.create_task(route_data())

    start = time.time()
    last_report = 0

    print("\n[4/5] Collecting and processing...")
    while time.time() - start < duration_sec:
        elapsed = time.time() - start

        if int(elapsed) - last_report >= 10:
            last_report = int(elapsed)

            # Force finalize current candles
            orderflow.flush_snapshot(symbol)

            # Get snapshot
            snap = orderflow.get_snapshot(symbol)

            # Detect regime
            candles_15m = orderflow.get_candle_history(symbol, 900, n=50)
            candles_1m = orderflow.get_candle_history(symbol, 60, n=100)
            regime = None

            if len(candles_1m) >= 20:
                regime = regime_detector.detect(
                    candles_1m,
                    symbol=symbol,
                    timeframe_minutes=1,
                    cvd=snap.cvd_1m if snap else 0.0,
                    book_imbalance=snap.book_imbalance if snap else 0.5,
                )

            print(f"\n  t={elapsed:.0f}s -- {symbol}:")

            if snap:
                print(f"    Price:          ${snap.price:,.2f}")
                print(f"    CVD 1m/5m/15m:  {snap.cvd_1m:+.4f} / {snap.cvd_5m:+.4f} / {snap.cvd_15m:+.4f}")
                print(f"    Book Imbalance: {snap.book_imbalance:.3f} (0=asks, 1=bids, 0.5=neutral)")
                print(f"    Aggression:     {snap.aggression_ratio:.3f} (0=sellers, 1=buyers)")
                print(f"    Volume Z-Score: {snap.volume_zscore:.2f}")
                print(f"    Micro VWAP:     ${snap.micro_vwap:,.2f} (z={snap.vwap_z:.2f})")
                print(f"    OI Change:      {snap.oi_change_pct:+.3f}%")
                print(f"    Kyle Lambda:    {snap.kyle_lambda:.8f}")
                print(f"    Absorption:     {snap.is_absorption}")
                print(f"    Liq Vacuum:     {snap.is_liq_vacuum}")
                print(f"    Vol Spike:      {snap.is_volume_spike}")
                print(f"    Liq Buy 10m:    {snap.liq_buy_volume_10m:.4f}")
                print(f"    Liq Sell 10m:   {snap.liq_sell_volume_10m:.4f}")
            else:
                print(f"    (Snapshot building... need more data)")

            if regime:
                print(f"\n    Regime:         {regime.regime.value} ({regime.confidence:.0%} confidence)")
                print(f"    ATR%:           {regime.atr_pct:.3f}%")
                print(f"    ADX proxy:      {regime.adx_proxy:.1f}")
                print(f"    Range width%:   {regime.range_width_pct:.3f}%")
                print(f"    Vol contraction:{regime.vol_contraction}")

                # Strategy scoring in this regime
                print(f"\n    Strategy scores in {regime.regime.value}:")
                for strat_name in ["VolumeBreakoutStrategy", "MeanReversionStrategy",
                                   "LiquidationSqueezeStrategy", "ImbalanceScalpStrategy"]:
                    score = scoring.get_score(strat_name, regime.regime.value)
                    status = "[OK] ACTIVE" if score.active else "[FAIL] BLOCKED"
                    print(f"      {strat_name:<30} score={score.score:.3f} {status}")
            else:
                print(f"\n    Regime: (building... need {20} candles, have {len(candles_1m)})")

            if candles_1m:
                last = candles_1m[-1]
                print(f"\n    Last 1m candle: O={last.open:.2f} H={last.high:.2f} "
                      f"L={last.low:.2f} C={last.close:.2f} "
                      f"delta={last.delta_pct:+.3f} "
                      f"aggr={last.aggression_ratio:.3f}")

        await asyncio.sleep(1)

    route_task.cancel()
    await ingestion.stop()

    # 5. Final report
    print("\n[5/5] Final Report:")
    ing_stats = ingestion.get_stats()
    print(f"  Trades processed:    {ing_stats['trades_received']}")
    print(f"  Depth updates:       {ing_stats['depth_updates_received']}")
    print(f"  1m candles built:    {len(orderflow.get_candle_history(symbol, 60))}")
    print(f"  5m candles built:    {len(orderflow.get_candle_history(symbol, 300))}")
    print(f"  15m candles built:   {len(orderflow.get_candle_history(symbol, 900))}")

    snap = orderflow.get_snapshot(symbol)
    success = snap is not None and snap.price > 0
    print("\n[OK] Orderflow dry run PASSED" if success else "\n[FAIL] Insufficient data collected")
    return success


def main():
    parser = argparse.ArgumentParser(description="Orderflow engine dry run")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()

    success = asyncio.run(run_orderflow_dry_run(args.symbol, args.duration))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
