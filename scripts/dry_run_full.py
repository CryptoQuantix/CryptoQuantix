#!/usr/bin/env python3
"""
dry_run_full.py -- Full system dry run: LIVE data + paper trading.

Runs the complete async pipeline for N minutes:
  - Connects to Binance Futures (live data, read-only)
  - Computes orderflow features in real-time
  - Detects market regime every minute
  - Scans all enabled strategies for signals
  - Paper-executes entries (mock -- no real Deribit orders)
  - Logs everything to console + file

IMPORTANT: Does NOT send real orders. Uses mock order manager.
Useful for verifying the whole pipeline before going live.

Prerequisites:
  - No .env required (Deribit creds not needed for dry run)
  - WebSocket internet access required
  - Run: pip install -r requirements.txt first

Run:
    python scripts/dry_run_full.py
    python scripts/dry_run_full.py --duration 300 --symbol BTCUSDT
    python scripts/dry_run_full.py --strategies vb,mr,liq,is
"""
import argparse
import asyncio
import logging
import sys
import time
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, ".")

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/dry_run_full.log"),
    ],
)
logger = logging.getLogger("dry_run_full")


class PaperOrderManager:
    """Paper trading order manager -- logs instead of sending real orders."""

    def __init__(self):
        self.fills = []
        self.registry = None
        self._fill_counter = 0

    def execute_generic_trade(
        self,
        instrument_name: str,
        direction: str,
        quantity: float,
        entry_type: str = "market",
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None,
        label: str = "",
    ):
        self._fill_counter += 1
        trade_id = f"PAPER-{self._fill_counter:04d}"
        logger.info(
            f"[PAPER TRADE] #{trade_id} {instrument_name} {direction.upper()} "
            f"qty={quantity:.4f} @ ${price:,.2f} "
            f"SL=${stop_loss:,.2f} TP=${take_profit:,.2f} "
            f"label={label}"
        )
        self.fills.append({
            "id": trade_id,
            "instrument": instrument_name,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "label": label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return True, trade_id, price

    def cancel_all(self):
        logger.info("[PAPER] cancel_all() called")

    def get_fills(self):
        return list(self.fills)


class PaperRiskManager:
    """Paper trading risk manager."""

    def __init__(self, equity: float = 10000.0):
        self._equity = equity

    def can_open_new_position(self):
        return True, "paper mode -- always allowed"

    def get_risk_summary(self):
        return {"equity": self._equity, "risk_utilization_pct": 10.0, "daily_pnl": 0.0}

    def calculate_dynamic_size(self, instrument_name, entry_price, sl_price,
                                atr_percentile=50.0, regime="UNKNOWN", model_winrate=0.5):
        risk = abs(entry_price - sl_price)
        quantity = (self._equity * 0.01) / risk if risk > 0 else 0.001
        return {"quantity": max(0.001, round(quantity, 4)), "adj_risk_usd": self._equity * 0.01}

    def get_daily_stats(self):
        return {"daily_pnl": 0.0, "trade_count": 0}


async def run_full_dry_run(
    symbol: str = "BTCUSDT",
    duration_sec: int = 120,
    strategy_codes: list = None,
):
    print("\n" + "=" * 60)
    print("FULL SYSTEM DRY RUN (PAPER TRADING)")
    print(f"Symbol: {symbol} | Duration: {duration_sec}s")
    print("Mode: PAPER (no real orders)")
    print("=" * 60)

    # 1. Import checks
    print("\n[1/6] Checking imports...")
    missing = []

    modules = {
        "BinanceDataIngestion": "src.data.binance_ingestion",
        "OrderBookEngine": "src.data.orderbook_engine",
        "OrderflowEngine": "src.engine.orderflow",
        "RegimeDetector": "src.engine.regime",
        "ScoringEngine": "src.engine.scoring",
    }

    available = {}
    for name, module in modules.items():
        try:
            parts = module.split(".")
            mod = __import__(module, fromlist=[name])
            available[name] = getattr(mod, name)
            print(f"  [OK] {name}")
        except ImportError as e:
            print(f"  [FAIL] {name}: {e}")
            missing.append(name)

    if missing:
        print(f"\n  Warning: {len(missing)} modules missing -- install dependencies:")
        print("  pip install websockets aiohttp duckdb numpy")
        return False

    # 2. Initialize components
    print("\n[2/6] Initializing components...")
    from src.data.binance_ingestion import BinanceDataIngestion
    from src.data.orderbook_engine import OrderBookEngine
    from src.engine.orderflow import OrderflowEngine
    from src.engine.regime import RegimeDetector, Regime
    from src.engine.scoring import ScoringEngine

    ingestion = BinanceDataIngestion(
        symbols=[symbol], persist_to_db=False, oi_poll_interval_sec=30
    )
    orderbook = OrderBookEngine(symbols=[symbol])
    orderflow = OrderflowEngine(symbols=[symbol])
    regime_detector = RegimeDetector()
    scoring = ScoringEngine()

    paper_om = PaperOrderManager()
    paper_rm = PaperRiskManager(equity=10000.0)
    mock_position_monitor = MagicMock()
    mock_position_monitor.get_open_futures_positions.return_value = []

    deps = {
        "order_manager": paper_om,
        "position_monitor": mock_position_monitor,
        "risk_manager": paper_rm,
        "orderflow_engine": orderflow,
        "regime_detector": regime_detector,
        "scoring_engine": scoring,
    }
    print("  [OK] Components initialized")

    # 3. Load strategies
    print("\n[3/6] Loading strategies...")
    strategies = []
    strategy_codes = strategy_codes or ["vb", "mr", "liq", "is"]

    strategy_map = {
        "vb": ("VolumeBreakout", "src.strategies.volume_breakout",
               "VolumeBreakoutStrategy", "config", "VolumeBreakoutConfig",
               {"name": "VolumeBreakout", "enabled": True, "symbol": symbol}),
        "mr": ("MeanReversion", "src.strategies.mean_reversion",
               "MeanReversionStrategy", "config", "MeanReversionConfig",
               {"name": "MeanReversion", "enabled": True, "symbol": symbol}),
        "liq": ("LiqSqueeze", "src.strategies.liq_squeeze",
                "LiquidationSqueezeStrategy", "config", "LiqSqueezeConfig",
                {"name": "LiqSqueeze", "enabled": True, "symbol": symbol}),
        "is": ("ImbalanceScalp", "src.strategies.imbalance_scalp",
               "ImbalanceScalpStrategy", "config", "ImbalanceScalpConfig",
               {"name": "ImbalanceScalp", "enabled": True, "symbol": symbol}),
    }

    for code in strategy_codes:
        if code not in strategy_map:
            continue
        friendly_name, strat_module, strat_class, cfg_module, cfg_class, cfg_kwargs = strategy_map[code]
        try:
            mod = __import__(strat_module, fromlist=[strat_class])
            cfg_mod = __import__(cfg_module, fromlist=[cfg_class])
            strat_cls = getattr(mod, strat_class)
            cfg_cls = getattr(cfg_mod, cfg_class)
            config = cfg_cls(**cfg_kwargs)
            # Create mock client
            mock_client = MagicMock()
            mock_client.get_index_price.return_value = 50000.0
            strategy = strat_cls(mock_client, config, deps)
            strategies.append(strategy)
            print(f"  [OK] {strategy.name}")
        except (ImportError, AttributeError) as e:
            print(f"  [FAIL] {friendly_name}: {e}")

    if not strategies:
        print("  No strategies loaded")
        return False

    # 4. Start data streams
    print(f"\n[4/6] Starting Binance streams...")
    await ingestion.start()
    # Fetch REST depth snapshot (required before processing WS incremental updates)
    snapshots = await ingestion.fetch_depth_snapshots()
    for sym, snap in snapshots.items():
        orderbook.apply_snapshot(sym, snap["bids"], snap["asks"],
                                 last_update_id=snap["lastUpdateId"])
    print("  [OK] Streams started")

    # 5. Main loop
    print(f"\n[5/6] Running paper trading loop ({duration_sec}s)...")
    print("      Scanning strategies every 30s after data builds up...\n")

    scan_count = 0
    total_signals = 0
    regime_changes = []
    last_regime = None
    last_scan = 0

    start = time.time()

    async def route_data_loop():
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

    route_task = asyncio.create_task(route_data_loop())

    while time.time() - start < duration_sec:
        elapsed = time.time() - start
        now = time.time()

        # Update regime every 30s
        candles_1m = orderflow.get_candle_history(symbol, 60, n=50)
        if len(candles_1m) >= 20:
            snap = orderflow.get_snapshot(symbol)
            new_regime = regime_detector.detect(
                candles_1m, symbol=symbol, timeframe_minutes=1,
                cvd=snap.cvd_1m if snap else 0.0,
                book_imbalance=snap.book_imbalance if snap else 0.5,
            )
            if last_regime and last_regime.regime != new_regime.regime:
                logger.info(
                    f"[Regime Change] {last_regime.regime.value} -> "
                    f"{new_regime.regime.value} ({new_regime.confidence:.0%})"
                )
                regime_changes.append({
                    "at": elapsed,
                    "from": last_regime.regime.value,
                    "to": new_regime.regime.value,
                })
            last_regime = new_regime

        # Scan strategies every 30s (after 60s warmup)
        if elapsed > 60 and now - last_scan >= 30:
            last_scan = now
            scan_count += 1
            regime_str = last_regime.regime.value if last_regime else "UNKNOWN"
            logger.info(f"\n[Scan #{scan_count}] t={elapsed:.0f}s | Regime: {regime_str}")

            for strategy in strategies:
                try:
                    # Scoring gate
                    allowed, reason = scoring.should_trade(strategy.__class__.__name__, regime_str)
                    if not allowed:
                        logger.info(f"  {strategy.name}: BLOCKED ({reason})")
                        continue

                    signals = strategy.scan()
                    if signals:
                        total_signals += len(signals)
                        for sig in signals:
                            logger.info(
                                f"  [OK] SIGNAL: {strategy.name} "
                                f"{sig.get('type')} {sig.get('direction')} "
                                f"@ ${sig.get('price', 0):,.2f}"
                            )
                            strategy.execute_entry(sig)
                    else:
                        logger.info(f"  {strategy.name}: no signal")

                except Exception as e:
                    logger.error(f"  {strategy.name} scan error: {e}")

        # Status every 15s
        if int(elapsed) % 15 == 0 and int(elapsed) > 0:
            snap = orderflow.get_snapshot(symbol)
            ing_stats = ingestion.get_stats()
            regime_str = last_regime.regime.value if last_regime else "building..."
            if snap and snap.price > 0:
                print(
                    f"  t={elapsed:.0f}s | ${snap.price:,.0f} | "
                    f"regime={regime_str} | "
                    f"CVD={snap.cvd_1m:+.3f} | "
                    f"imb={snap.book_imbalance:.3f} | "
                    f"trades={ing_stats['trades_received']} | "
                    f"signals={total_signals}",
                    flush=True,
                )
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.5)

    route_task.cancel()
    await ingestion.stop()

    # 6. Final summary
    print("\n[6/6] Final Summary:")
    print(f"  Duration:          {time.time() - start:.0f}s")
    print(f"  Scan cycles:       {scan_count}")
    print(f"  Total signals:     {total_signals}")
    print(f"  Paper fills:       {len(paper_om.fills)}")
    print(f"  Regime changes:    {len(regime_changes)}")

    ing_stats = ingestion.get_stats()
    print(f"  Trades ingested:   {ing_stats['trades_received']}")
    print(f"  Depth updates:     {ing_stats['depth_updates_received']}")
    print(f"  Liquidations:      {ing_stats['liquidations_received']}")
    print(f"  WS reconnects:     {ing_stats['ws_reconnects']}")

    if paper_om.fills:
        print("\n  Paper Trades Executed:")
        for fill in paper_om.fills:
            print(
                f"    {fill['id']}: {fill['instrument']} {fill['direction'].upper()} "
                f"{fill['quantity']:.4f} @ ${fill['price']:,.2f}"
            )

    final_snap = orderflow.get_snapshot(symbol)
    success = final_snap is not None and final_snap.price > 0

    if success:
        print(f"\n  Final market state:")
        print(f"    Price:    ${final_snap.price:,.2f}")
        print(f"    CVD 1m:   {final_snap.cvd_1m:+.4f}")
        print(f"    CVD 5m:   {final_snap.cvd_5m:+.4f}")
        print(f"    Imbalance:{final_snap.book_imbalance:.3f}")
        if last_regime:
            print(f"    Regime:   {last_regime.regime.value} ({last_regime.confidence:.0%})")

    print("\n[OK] Full dry run PASSED" if success else "\n[FAIL] Insufficient data -- check connection")
    print("  Log saved to: logs/dry_run_full.log")
    return success


def main():
    parser = argparse.ArgumentParser(description="Full system dry run")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", type=int, default=120, help="Duration in seconds")
    parser.add_argument("--strategies", default="vb,mr,liq,is",
                        help="Strategy codes: vb,mr,liq,is")
    args = parser.parse_args()

    strategy_codes = [s.strip() for s in args.strategies.split(",")]
    success = asyncio.run(
        run_full_dry_run(args.symbol, args.duration, strategy_codes)
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
