#!/usr/bin/env python3
"""
dry_run_data.py -- Tests Binance data ingestion pipeline.

What it tests:
  1. WebSocket connection to Binance Futures
  2. aggTrade stream: volume classification (buy vs sell)
  3. Depth stream: L2 book updates
  4. Liquidation stream
  5. OI REST polling
  6. OrderBookEngine: snapshot generation, imbalance calculation
  7. DataQualityLayer: candle validation
  8. DuckDB storage (if available)

Run:
    python scripts/dry_run_data.py
    python scripts/dry_run_data.py --symbol ETHUSDT --duration 60
"""
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("dry_run_data")


async def run_data_dry_run(symbol: str = "BTCUSDT", duration_sec: int = 30):
    """Run data layer dry run for N seconds."""

    print("\n" + "=" * 60)
    print("DRY RUN: DATA LAYER")
    print(f"Symbol: {symbol} | Duration: {duration_sec}s")
    print("=" * 60)

    # 1. Import check
    print("\n[1/7] Checking imports...")
    try:
        from src.data.binance_ingestion import BinanceDataIngestion, AggTrade, DepthUpdate
        from src.data.orderbook_engine import OrderBookEngine
        from src.data.data_quality import DataQualityLayer
        print("  [OK] All data modules imported successfully")
    except ImportError as e:
        print(f"  [FAIL] Import error: {e}")
        print("  Run: pip install websockets aiohttp duckdb")
        return False

    # 2. Check websockets
    print("\n[2/7] Checking WebSocket library...")
    try:
        import websockets
        print(f"  [OK] websockets {websockets.__version__}")
    except ImportError:
        print("  [FAIL] websockets not installed -- run: pip install websockets>=12.0")
        return False

    # 3. Initialize components
    print("\n[3/7] Initializing components...")
    received_trades = []
    received_depths = []
    received_liqs = []

    def on_trade(trade):
        received_trades.append(trade)
        if len(received_trades) % 50 == 0:
            logger.info(
                f"  Trade #{len(received_trades)}: {trade.symbol} {trade.side} "
                f"{trade.quantity:.4f} @ ${trade.price:,.2f}"
            )

    def on_depth(depth):
        received_depths.append(depth)

    def on_liq(liq):
        received_liqs.append(liq)
        logger.warning(
            f"  LIQUIDATION: {liq.symbol} {liq.side} "
            f"{liq.quantity:.4f} @ ${liq.price:,.2f}"
        )

    ingestion = BinanceDataIngestion(
        symbols=[symbol],
        storage_path="data/raw",
        on_trade=on_trade,
        on_depth=on_depth,
        on_liquidation=on_liq,
        oi_poll_interval_sec=15,
        persist_to_db=True,
    )

    orderbook = OrderBookEngine(symbols=[symbol])
    data_quality = DataQualityLayer()

    print("  [OK] Components initialized")

    # 4. Start ingestion
    print(f"\n[4/7] Starting WebSocket streams (will run {duration_sec}s)...")
    await ingestion.start()
    print("  [OK] Streams started")

    # 5. Route depth updates to orderbook
    async def route_depth():
        while True:
            try:
                depth = await asyncio.wait_for(ingestion.depth_queue.get(), timeout=2.0)
                orderbook.apply_update(depth)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    route_task = asyncio.create_task(route_depth())

    # 6. Wait and collect data
    print(f"\n[5/7] Collecting data for {duration_sec}s...")
    start = time.time()
    last_report = 0

    while time.time() - start < duration_sec:
        elapsed = time.time() - start

        if int(elapsed) - last_report >= 5:
            last_report = int(elapsed)
            stats = ingestion.get_stats()
            snap = orderbook.get_snapshot(symbol)
            oi = ingestion.get_open_interest(symbol)

            print(f"\n  t={elapsed:.0f}s:")
            print(f"    Trades:       {stats['trades_received']}")
            print(f"    Depth updates:{stats['depth_updates_received']}")
            print(f"    Liquidations: {stats['liquidations_received']}")
            print(f"    WS reconnects:{stats['ws_reconnects']}")

            if snap:
                print(f"    Book snapshot: bid={snap.best_bid:.2f} ask={snap.best_ask:.2f} "
                      f"imbalance={snap.book_imbalance:.3f} spread_bps={snap.spread_bps:.2f}")
            else:
                print(f"    Book snapshot: (building...)")

            if oi:
                print(f"    OI: {oi.oi_contracts:,.2f} contracts = ${oi.oi_value_usd:,.0f}")

        await asyncio.sleep(1)

    route_task.cancel()
    await ingestion.stop()

    # 7. Data quality validation
    print("\n[6/7] Running data quality checks...")
    recent_trades = ingestion.get_recent_trades(symbol, n=500)

    if recent_trades:
        clean_trades, report = data_quality.validate_trades(recent_trades, symbol)
        print(f"  Validated {report.total_records} trades:")
        print(f"    Outliers removed: {report.outliers_removed}")
        print(f"    Stale records: {report.stale_records}")
        if report.issues:
            for issue in report.issues:
                print(f"    Warning: {issue}")

        # Build candles from trades
        candles = data_quality.build_candles_from_trades(recent_trades, interval_seconds=60)
        print(f"  Built {len(candles)} 1m candles from {len(recent_trades)} trades")

        if candles:
            clean_candles, candle_report = data_quality.validate_candles(candles, symbol)
            print(f"  Candle quality: {len(clean_candles)}/{len(candles)} clean | "
                  f"gaps={candle_report.gaps_found} bad={candle_report.bad_candles_removed}")
    else:
        print("  No trades collected (WebSocket may not have connected)")

    # 8. Final summary
    stats = ingestion.get_stats()
    print("\n[7/7] Final Summary:")
    print(f"  Total trades received:   {stats['trades_received']}")
    print(f"  Total depth updates:     {stats['depth_updates_received']}")
    print(f"  Total liquidations:      {stats['liquidations_received']}")
    print(f"  OI polls:                {stats['oi_polls']}")
    print(f"  Errors:                  {stats['errors']}")

    # Buy/sell split
    recent = ingestion.get_recent_trades(symbol, n=1000)
    if recent:
        buy_vol = sum(t.buy_volume for t in recent)
        sell_vol = sum(t.sell_volume for t in recent)
        total_vol = buy_vol + sell_vol
        if total_vol > 0:
            print(f"\n  Volume split (last {len(recent)} trades):")
            print(f"    Buy:  {buy_vol:.4f} ({buy_vol/total_vol:.1%})")
            print(f"    Sell: {sell_vol:.4f} ({sell_vol/total_vol:.1%})")
            delta = buy_vol - sell_vol
            print(f"    Delta:{delta:+.4f}")

    print("\n[OK] Data layer dry run PASSED" if stats['trades_received'] > 0 else "\n[FAIL] No data received -- check connection")
    return stats['trades_received'] > 0


def main():
    parser = argparse.ArgumentParser(description="Data layer dry run")
    parser.add_argument("--symbol", default="BTCUSDT", help="Binance symbol")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds")
    args = parser.parse_args()

    success = asyncio.run(run_data_dry_run(args.symbol, args.duration))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
