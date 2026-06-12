#!/usr/bin/env python3
"""
dry_run_strategies.py -- Tests all strategies in paper trading mode.

What it tests:
  1. All strategy imports and initialization
  2. Strategy.scan() with mock orderflow data -> signals generated
  3. Strategy.execute_entry() -> mock order placed (no real API calls)
  4. Strategy.manage_positions() -> returns stats
  5. Backtest engine with synthetic data -> complete P&L computation
  6. Monte Carlo on backtest results

Requires: DERIBIT_API_KEY and DERIBIT_API_SECRET in .env (for client init only)
No real orders are placed -- uses mock order_manager.

Run:
    python scripts/dry_run_strategies.py
    python scripts/dry_run_strategies.py --strategy volume_breakout
    python scripts/dry_run_strategies.py --backtest
"""
import argparse
import logging
import sys
import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dry_run_strategies")


def build_mock_dependencies(with_orderflow=True):
    """Build mock dependencies for strategy testing."""
    mock_client = MagicMock()
    mock_client.get_index_price.return_value = 50000.0
    mock_client.get_order_book.return_value = {
        "mark_price": 0.05, "best_bid": 49990, "best_ask": 50010
    }

    mock_order_manager = MagicMock()
    mock_order_manager.execute_generic_trade.return_value = (True, "MOCK-FILL-001")

    mock_position_monitor = MagicMock()
    mock_position_monitor.get_open_futures_positions.return_value = []

    mock_risk_manager = MagicMock()
    mock_risk_manager.can_open_new_position.return_value = (True, "OK")
    mock_risk_manager.get_risk_summary.return_value = {
        "equity": 10000.0, "risk_utilization_pct": 20.0
    }
    mock_risk_manager.calculate_dynamic_size.return_value = {
        "quantity": 0.01,
        "adj_risk_usd": 100.0,
        "base_risk_usd": 100.0,
    }

    deps = {
        "order_manager": mock_order_manager,
        "position_monitor": mock_position_monitor,
        "risk_manager": mock_risk_manager,
        "kline_provider": FakeKlineProvider(),
    }

    if with_orderflow:
        try:
            from src.engine.orderflow import OrderflowEngine, MarketSnapshot, CandleFeatures
            from src.engine.regime import RegimeDetector, Regime
            from src.engine.scoring import ScoringEngine

            # Build synthetic MarketSnapshot with favorable conditions
            snap = MarketSnapshot(
                symbol="BTCUSDT",
                timestamp_ms=int(time.time() * 1000),
                price=50000.0,
            )

            # Volume breakout conditions
            snap.volume_zscore = 2.5
            snap.book_imbalance = 0.65
            snap.cvd_1m = 150.0
            snap.cvd_5m = 500.0
            snap.oi_change_pct = 1.2
            snap.aggression_ratio = 0.65
            snap.micro_vwap = 49800.0
            snap.vwap_z = -2.3  # price at extreme for mean reversion
            snap.is_absorption = True
            snap.is_liq_vacuum = True
            snap.liq_buy_volume_10m = 75.0  # liquidation squeeze
            snap.liq_sell_volume_10m = 5.0
            snap.kyle_lambda = 0.0001

            # Build a 5m candle with strong delta
            candle = CandleFeatures(
                timestamp_ms=int(time.time() * 1000),
                interval_seconds=300,
                open=49500.0, high=50200.0, low=49400.0, close=50000.0,
                buy_volume=150.0, sell_volume=50.0, total_volume=200.0,
                delta=100.0, delta_pct=0.5,
                aggression_ratio=0.75,
            )
            snap.current_1m = candle
            snap.current_5m = candle

            mock_engine = MagicMock()
            mock_engine.get_snapshot.return_value = snap
            mock_engine.get_candle_history.return_value = _build_synthetic_candles(50)
            mock_engine.flush_snapshot.return_value = None

            mock_regime = MagicMock()
            from src.engine.regime import MarketRegime
            mock_regime_obj = MarketRegime(
                regime=Regime.EXPANSION,
                confidence=0.85,
                symbol="BTCUSDT",
                atr_pct=1.2,
                adx_proxy=28.0,
            )
            mock_regime.get_last_regime.return_value = mock_regime_obj
            mock_regime.detect.return_value = mock_regime_obj

            mock_scoring = MagicMock()
            mock_scoring.should_trade.return_value = (True, "score=0.75 regime=EXPANSION")
            mock_scoring.get_score.return_value = MagicMock(active=True, score=0.75, regime_multiplier=1.2)

            deps["orderflow_engine"] = mock_engine
            deps["regime_detector"] = mock_regime
            deps["scoring_engine"] = mock_scoring

        except ImportError as e:
            logger.warning(f"Orderflow not available: {e}")

    return mock_client, deps


class FakeKlineProvider:
    """Offline 1h/1d kline + funding provider engineered to trigger:
    - TrendBreakdown SHORT: macro bear + close below 48h low + sellers
    - FundingSqueeze SHORT: funding above threshold + price below SMA(48)"""

    def __init__(self):
        # Align the fake clock to 10 min after a funding settlement so the
        # FundingSqueeze entry window check passes deterministically.
        real_ms = int(time.time() * 1000)
        window_ms = 8 * 3600 * 1000
        self._now_ms = (real_ms // window_ms) * window_ms + 10 * 60_000
        self.candles_1h = []
        price = 60000.0
        for i in range(200):
            price -= 80.0  # steady downtrend
            close = price
            if i == 199:
                close = price - 500.0  # breakdown below the 48h low
            ts = self._now_ms - (200 - i) * 3_600_000
            self.candles_1h.append({
                "ts_ms": ts,
                "open": price + 80.0, "high": price + 120.0,
                "low": close - 60.0, "close": close,
                "volume": 1000.0, "buy_volume": 350.0,
                "buy_ratio": 0.35,  # sellers in control
                "close_ts_ms": ts + 3_600_000,
            })
        # 240 daily candles declining -> close < SMA200 and SMA200 falling
        # (macro BEAR accelerating: covers the 200+30 slope-gate requirement)
        self.candles_1d = []
        dprice = 100000.0
        for i in range(240):
            dprice -= 150.0
            ts = self._now_ms - (240 - i) * 86_400_000
            self.candles_1d.append({
                "ts_ms": ts,
                "open": dprice + 150.0, "high": dprice + 300.0,
                "low": dprice - 300.0, "close": dprice,
                "volume": 50000.0, "buy_volume": 22000.0,
                "buy_ratio": 0.44,
                "close_ts_ms": ts + 86_400_000,
            })

    def get_klines(self, symbol, interval="1h", limit=60):
        frame = self.candles_1d if interval == "1d" else self.candles_1h
        return frame[-limit:]

    def get_funding_rate(self, symbol):
        return 0.0001  # 0.01% per 8h — above the 0.005% threshold

    def now_ms(self):
        return self._now_ms


class FakeBullKlineProvider(FakeKlineProvider):
    """Macro-BULL variant: rising daily closes (close > SMA200) so the
    MacroCore entry fires in the dry run."""

    def __init__(self):
        super().__init__()
        self.candles_1d = []
        dprice = 40000.0
        for i in range(240):
            dprice += 120.0
            ts = self._now_ms - (240 - i) * 86_400_000
            self.candles_1d.append({
                "ts_ms": ts,
                "open": dprice - 120.0, "high": dprice + 250.0,
                "low": dprice - 250.0, "close": dprice,
                "volume": 50000.0, "buy_volume": 28000.0,
                "buy_ratio": 0.56,
                "close_ts_ms": ts + 86_400_000,
            })


def _build_synthetic_candles(n: int = 50):
    """Build synthetic candle features for testing."""
    try:
        from src.engine.orderflow import CandleFeatures
        import numpy as np
        candles = []
        price = 50000.0
        np.random.seed(42)
        for i in range(n):
            change = np.random.normal(0, 100)
            price += change
            buy_vol = abs(np.random.normal(100, 30))
            sell_vol = abs(np.random.normal(80, 20))
            candles.append(CandleFeatures(
                timestamp_ms=int(time.time() * 1000) - (n - i) * 300000,
                interval_seconds=300,
                open=price - abs(change),
                high=price + abs(np.random.normal(0, 50)),
                low=price - abs(np.random.normal(0, 50)),
                close=price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                total_volume=buy_vol + sell_vol,
                delta=buy_vol - sell_vol,
                delta_pct=(buy_vol - sell_vol) / (buy_vol + sell_vol),
                volume_zscore=np.random.normal(0, 1),
                aggression_ratio=buy_vol / (buy_vol + sell_vol),
            ))
        return candles
    except Exception:
        return []


def test_strategy(name: str, strategy_class, config_class, config_kwargs: dict, mock_client, deps):
    """Test a single strategy."""
    print(f"\n  [{name}]")

    try:
        config = config_class(**config_kwargs)
        strategy = strategy_class(mock_client, config, deps)
        print(f"    [OK] Initialized: {strategy.name}")

        # Test scan()
        signals = strategy.scan()
        print(f"    [OK] scan() returned {len(signals)} signals")
        for sig in signals:
            print(f"      Signal: {sig.get('type')} {sig.get('direction')} "
                  f"@ ${sig.get('price', 0):,.2f} "
                  f"SL=${sig.get('stop_loss', 0):,.2f} "
                  f"TP=${sig.get('take_profit', 0):,.2f}")

        # Test execute_entry() if signals found
        executed = 0
        for sig in signals[:1]:  # only test first signal
            success = strategy.execute_entry(sig)
            print(f"    [OK] execute_entry() -> success={success}")
            if success:
                executed += 1

        # Test manage_positions()
        stats = strategy.manage_positions()
        print(f"    [OK] manage_positions() -> {stats}")

        return {"name": name, "signals": len(signals), "executed": executed, "ok": True}

    except Exception as e:
        print(f"    [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"name": name, "signals": 0, "executed": 0, "ok": False, "error": str(e)}


def run_backtest_test():
    """Run a quick backtest with synthetic data."""
    print("\n" + "=" * 60)
    print("BACKTEST TEST (Synthetic Data)")
    print("=" * 60)

    try:
        from src.backtest.backtest_engine import BacktestEngine, BacktestMetrics
        from src.backtest.monte_carlo import MonteCarloSimulator

        # Build synthetic candles
        import numpy as np
        np.random.seed(42)

        n_candles = 500
        price = 50000.0
        candles = []
        for i in range(n_candles):
            change = np.random.normal(0, 200)
            open_p = price
            price += change
            high_p = max(open_p, price) + abs(np.random.normal(0, 100))
            low_p = min(open_p, price) - abs(np.random.normal(0, 100))
            buy_pct = 0.5 + np.random.normal(0, 0.1)
            vol = abs(np.random.normal(100, 30))
            candles.append({
                "timestamp_ms": i * 60000,
                "open": open_p, "high": high_p,
                "low": low_p, "close": price,
                "volume": vol,
                "buy_volume": vol * max(0.1, min(0.9, buy_pct)),
                "sell_volume": vol * (1 - max(0.1, min(0.9, buy_pct))),
            })

        print(f"  Synthetic data: {n_candles} 1m candles")
        print(f"  Price range: ${min(c['low'] for c in candles):,.0f} - ${max(c['high'] for c in candles):,.0f}")

        # Build a mock strategy that generates signals
        from src.strategies.volume_breakout import VolumeBreakoutStrategy
        from config import VolumeBreakoutConfig

        mock_client, deps = build_mock_dependencies(with_orderflow=True)
        config = VolumeBreakoutConfig(name="VolumeBreakout BT Test", enabled=True)
        strategy = VolumeBreakoutStrategy(mock_client, config, deps)

        # Run backtest
        engine = BacktestEngine(initial_equity=10000.0, slippage_pct=0.0005)

        print("\n  Running backtest...")
        t0 = time.time()
        result = engine.run(
            strategy=strategy,
            symbol="BTCUSDT",
            candle_data=candles,
            scan_interval_candles=5,
        )
        print(f"  Completed in {time.time() - t0:.2f}s")
        print(f"  Trades:   {len(result.trades)}")
        print(f"  Candles:  {result.candles_processed}")

        if result.trades:
            BacktestMetrics.print_report(result.metrics)

            # Monte Carlo
            print("\n  Running Monte Carlo (500 simulations)...")
            mc = MonteCarloSimulator(n_simulations=500, ruin_threshold_pct=0.5, random_seed=42)
            mc_results = mc.run(result.trades, initial_equity=10000.0)
            mc.print_summary(mc_results)
        else:
            print("  No trades generated (not enough data for signals with synthetic candles)")

        print("\n  [OK] Backtest test PASSED")
        return True

    except ImportError as e:
        print(f"  [FAIL] Import error: {e}")
        return False
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Strategy dry run")
    parser.add_argument("--strategy", default="all", help="Strategy to test (all|volume_breakout|mean_reversion|liq_squeeze|imbalance_scalp|trend_breakdown|funding_squeeze)")
    parser.add_argument("--backtest", action="store_true", help="Run backtest test")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("DRY RUN: STRATEGY PAPER TRADING")
    print("=" * 60)

    # Build mock client + deps
    mock_client, deps = build_mock_dependencies(with_orderflow=True)

    results = []

    # Test new volumetric strategies
    strategies_to_test = []

    if args.strategy in ("all", "volume_breakout"):
        try:
            from src.strategies.volume_breakout import VolumeBreakoutStrategy
            from config import VolumeBreakoutConfig
            strategies_to_test.append((
                "VolumeBreakout",
                VolumeBreakoutStrategy,
                VolumeBreakoutConfig,
                {"name": "VolumeBreakout Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] VolumeBreakout import: {e}")

    if args.strategy in ("all", "mean_reversion"):
        try:
            from src.strategies.mean_reversion import MeanReversionStrategy
            from config import MeanReversionConfig
            strategies_to_test.append((
                "MeanReversion",
                MeanReversionStrategy,
                MeanReversionConfig,
                {"name": "MeanReversion Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] MeanReversion import: {e}")

    if args.strategy in ("all", "liq_squeeze"):
        try:
            from src.strategies.liq_squeeze import LiquidationSqueezeStrategy
            from config import LiqSqueezeConfig
            strategies_to_test.append((
                "LiqSqueeze",
                LiquidationSqueezeStrategy,
                LiqSqueezeConfig,
                {"name": "LiqSqueeze Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] LiqSqueeze import: {e}")

    if args.strategy in ("all", "imbalance_scalp"):
        try:
            from src.strategies.imbalance_scalp import ImbalanceScalpStrategy
            from config import ImbalanceScalpConfig
            strategies_to_test.append((
                "ImbalanceScalp",
                ImbalanceScalpStrategy,
                ImbalanceScalpConfig,
                {"name": "ImbalanceScalp Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] ImbalanceScalp import: {e}")

    if args.strategy in ("all", "trend_breakdown"):
        try:
            from src.strategies.trend_breakdown import TrendBreakdownStrategy
            from config import TrendBreakdownConfig
            strategies_to_test.append((
                "TrendBreakdown",
                TrendBreakdownStrategy,
                TrendBreakdownConfig,
                {"name": "TrendBreakdown Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] TrendBreakdown import: {e}")

    if args.strategy in ("all", "funding_squeeze"):
        try:
            from src.strategies.funding_squeeze import FundingSqueezeStrategy
            from config import FundingSqueezeConfig
            strategies_to_test.append((
                "FundingSqueeze",
                FundingSqueezeStrategy,
                FundingSqueezeConfig,
                {"name": "FundingSqueeze Test", "enabled": True},
            ))
        except ImportError as e:
            print(f"  [FAIL] FundingSqueeze import: {e}")

    if args.strategy in ("all", "macro_core"):
        try:
            from src.strategies.macro_core import MacroCoreStrategy
            from config import MacroCoreConfig
            # MacroCore needs a macro-BULL provider (rising dailies) to fire;
            # persist_state=False keeps the dry run from writing state files
            deps_bull = dict(deps)
            deps_bull["kline_provider"] = FakeBullKlineProvider()
            strategies_to_test.append((
                "MacroCore",
                MacroCoreStrategy,
                MacroCoreConfig,
                {"name": "MacroCore Test", "enabled": True, "persist_state": False},
                deps_bull,
            ))
        except ImportError as e:
            print(f"  [FAIL] MacroCore import: {e}")

    if not strategies_to_test:
        print("No strategies available to test")
        sys.exit(1)

    print(f"\nTesting {len(strategies_to_test)} strategies...")
    for entry in strategies_to_test:
        name, cls, cfg_cls, cfg_kwargs = entry[:4]
        strategy_deps = entry[4] if len(entry) > 4 else deps
        result = test_strategy(name, cls, cfg_cls, cfg_kwargs, mock_client, strategy_deps)
        results.append(result)

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    all_ok = True
    for r in results:
        status = "[OK]" if r["ok"] else "[FAIL]"
        print(f"  {status} {r['name']:<25} signals={r['signals']} executed={r['executed']}")
        if not r["ok"]:
            all_ok = False
            print(f"     Error: {r.get('error', 'unknown')}")

    # Backtest test
    if args.backtest:
        bt_ok = run_backtest_test()
        all_ok = all_ok and bt_ok
    else:
        print("\n  (Run with --backtest to also test the backtest engine)")

    print("\n[OK] All strategy tests PASSED" if all_ok else "\n[FAIL] Some tests FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
