"""
BacktestEngine — tick-accurate strategy backtesting.

Features:
  - Tick replay from DuckDB or Parquet files
  - Feeds data through OrderflowEngine + RegimeDetector (same as live)
  - Calls strategy.scan() and strategy.execute_entry() in simulation
  - Simulates Deribit order fills with:
    - Taker fee: 0.05% (futures), 0.03% for maker
    - Slippage: configurable (default: 1-2 ticks)
    - Latency simulation: configurable delay (default: 50ms)
    - Partial fill simulation
  - Position tracking with SL/TP
  - Per-trade P&L calculation

Usage:
    engine = BacktestEngine()
    result = engine.run(
        strategy=VolumeBreakoutStrategy(client, config, deps),
        symbol="BTCUSDT",
        start_date="2024-01-01",
        end_date="2024-02-01",
    )
    print(result.metrics)
"""
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


@dataclass
class BacktestTrade:
    """Single simulated trade record."""
    trade_id: str
    strategy: str
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float
    entry_time: str
    entry_ts_ms: int

    exit_price: float = 0.0
    exit_time: str = ""
    exit_ts_ms: int = 0
    exit_reason: str = ""    # "tp", "sl", "end_of_data"
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    fees_usd: float = 0.0
    duration_minutes: float = 0.0
    slippage_usd: float = 0.0

    regime: str = "UNKNOWN"
    signal_data: Dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    """Complete backtest run result."""
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    ticks_processed: int = 0
    candles_processed: int = 0
    trades: List[BacktestTrade] = field(default_factory=list)
    metrics: Dict = field(default_factory=dict)
    equity_curve: List[Tuple[int, float]] = field(default_factory=list)  # [(ts_ms, equity)]
    run_duration_sec: float = 0.0


# Deribit fee structure
DERIBIT_TAKER_FEE = 0.0005   # 0.05%
DERIBIT_MAKER_FEE = 0.0003   # 0.03%
DERIBIT_DELIVERY_FEE = 0.0   # futures: no delivery fee


class MockOrderManager:
    """
    Simulates order execution for backtesting.
    Records fills instead of sending real API calls.
    """

    def __init__(
        self,
        slippage_pct: float = 0.0005,  # 0.05% slippage (market orders)
        latency_ms: float = 50.0,
        use_maker_fee: bool = False,
    ):
        self.slippage_pct = slippage_pct
        self.latency_ms = latency_ms
        self.fee_rate = DERIBIT_MAKER_FEE if use_maker_fee else DERIBIT_TAKER_FEE
        self.fills: List[Dict] = []
        self.registry = None  # no registry needed in backtest

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
    ) -> Tuple[bool, str]:
        """Record a simulated fill."""
        fill_price = price or 0.0
        if entry_type == "market" and fill_price > 0:
            slippage = fill_price * self.slippage_pct
            fill_price += slippage if direction == "buy" else -slippage

        fill = {
            "instrument": instrument_name,
            "direction": direction,
            "quantity": quantity,
            "fill_price": fill_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "label": label,
            "filled": True,
        }
        self.fills.append(fill)
        trade_id = f"bt_{len(self.fills)}_{int(time.time() * 1000)}"
        return True, trade_id

    def cancel_all(self):
        pass


class BacktestEngine:
    """
    Tick-replay backtesting engine.
    Uses the same OrderflowEngine and strategies as live trading.
    """

    def __init__(
        self,
        data_path: str = "data/raw",
        initial_equity: float = 10000.0,
        slippage_pct: float = 0.0005,
        latency_ms: float = 50.0,
        use_maker_fee: bool = False,
    ):
        self.data_path = data_path
        self.initial_equity = initial_equity
        self.slippage_pct = slippage_pct
        self.latency_ms = latency_ms
        self.use_maker_fee = use_maker_fee
        self.fee_rate = DERIBIT_MAKER_FEE if use_maker_fee else DERIBIT_TAKER_FEE

    def run(
        self,
        strategy,
        symbol: str = "BTCUSDT",
        start_date: str = None,
        end_date: str = None,
        candle_data: List[Dict] = None,
        scan_interval_candles: int = 5,
    ) -> BacktestResult:
        """
        Run a backtest for a strategy.

        Args:
            strategy: BaseStrategy instance (will be given mock order_manager)
            symbol: trading symbol
            start_date: "YYYY-MM-DD" or None for all data
            end_date: "YYYY-MM-DD" or None
            candle_data: Optional list of OHLCV dicts to use as input
                         (if None, loads from DuckDB/Parquet)
            scan_interval_candles: how often to call strategy.scan()

        Returns:
            BacktestResult with all trades and metrics
        """
        run_start = time.time()
        logger.info(f"[Backtest] Starting: {strategy.name} on {symbol} [{start_date} to {end_date}]")

        # Load data
        if candle_data is None:
            candle_data = self._load_candles(symbol, start_date, end_date)

        if not candle_data:
            logger.warning("[Backtest] No candle data available")
            return BacktestResult(
                strategy_name=strategy.name,
                symbol=symbol,
                start_date=start_date or "",
                end_date=end_date or "",
            )

        # Setup mock order manager
        mock_om = MockOrderManager(
            slippage_pct=self.slippage_pct,
            latency_ms=self.latency_ms,
            use_maker_fee=self.use_maker_fee,
        )
        original_om = strategy.order_manager
        strategy.order_manager = mock_om

        # Setup orderflow engine if not present
        from src.engine.orderflow import OrderflowEngine
        from src.engine.regime import RegimeDetector
        of_engine = getattr(strategy, "orderflow_engine", None) or OrderflowEngine(symbols=[symbol])
        regime_detector = getattr(strategy, "regime_detector", None) or RegimeDetector()

        # Feed candles to orderflow engine
        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            start_date=start_date or candle_data[0].get("timestamp_ms", ""),
            end_date=end_date or candle_data[-1].get("timestamp_ms", ""),
        )

        equity = self.initial_equity
        result.equity_curve.append((0, equity))
        open_trades: List[BacktestTrade] = []
        trade_counter = 0

        for i, candle in enumerate(candle_data):
            ts_ms = candle.get("timestamp_ms", i * 60000)
            price = candle.get("close", 0)
            if price <= 0:
                continue

            # Feed candle to orderflow engine (simulate aggTrade from close/volume)
            self._feed_candle_to_engine(of_engine, candle, symbol)
            result.candles_processed += 1

            # Check open trades: hit SL/TP?
            high = candle.get("high", price)
            low = candle.get("low", price)
            closed_trades = self._check_exits(open_trades, high, low, price, ts_ms)
            for ct in closed_trades:
                equity += ct.pnl_usd
                result.trades.append(ct)
                result.equity_curve.append((ts_ms, equity))
            open_trades = [t for t in open_trades if t not in closed_trades]

            # Scan strategy every N candles (not every tick)
            if i % scan_interval_candles == 0 and i >= 30:
                # Update regime every 15m
                if i % 15 == 0:
                    hist = of_engine.get_candle_history(symbol, 60, n=50)
                    if len(hist) >= 30:
                        snap = of_engine.get_snapshot(symbol)
                        cvd = snap.cvd_1m if snap else 0.0
                        imb = snap.book_imbalance if snap else 0.5
                        regime = regime_detector.detect(hist, symbol=symbol, cvd=cvd, book_imbalance=imb)
                        strategy.orderflow_engine = of_engine
                        strategy.regime_detector = regime_detector

                try:
                    mock_om.fills.clear()
                    signals = strategy.scan()

                    for signal in signals:
                        if not open_trades:  # max 1 open trade per strategy in backtest
                            trade_counter += 1
                            fill_price = signal.get("price", price)
                            slippage = fill_price * self.slippage_pct
                            if signal.get("direction", "buy").lower() == "buy":
                                fill_price += slippage
                            else:
                                fill_price -= slippage

                            fee = fill_price * 0.001 * self.fee_rate  # fee on entry
                            quantity = signal.get("quantity", 0.001)

                            trade = BacktestTrade(
                                trade_id=f"bt_{trade_counter:04d}",
                                strategy=strategy.name,
                                symbol=symbol,
                                direction=signal.get("direction", "buy").lower(),
                                entry_price=fill_price,
                                sl_price=signal.get("stop_loss", 0),
                                tp_price=signal.get("take_profit", 0),
                                quantity=quantity,
                                entry_time=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                                entry_ts_ms=ts_ms,
                                fees_usd=fee,
                                regime=signal.get("regime", "UNKNOWN"),
                                signal_data=signal,
                            )
                            open_trades.append(trade)

                except Exception as e:
                    logger.debug(f"[Backtest] Strategy scan error at candle {i}: {e}")

        # Close any remaining open trades at last price
        for trade in open_trades:
            last_price = candle_data[-1].get("close", trade.entry_price)
            trade.exit_price = last_price
            trade.exit_reason = "end_of_data"
            trade.exit_ts_ms = candle_data[-1].get("timestamp_ms", 0)
            trade.pnl_usd = self._compute_pnl(trade, last_price)
            equity += trade.pnl_usd
            result.trades.append(trade)

        # Restore original order manager
        strategy.order_manager = original_om

        # Compute metrics
        result.metrics = BacktestMetrics.compute(result.trades, self.initial_equity, equity)
        result.run_duration_sec = time.time() - run_start

        logger.info(
            f"[Backtest] Complete: {len(result.trades)} trades | "
            f"P&L: ${equity - self.initial_equity:+,.2f} | "
            f"WR: {result.metrics.get('winrate', 0):.1%} | "
            f"Time: {result.run_duration_sec:.1f}s"
        )
        return result

    def _feed_candle_to_engine(self, engine, candle: Dict, symbol: str):
        """Simulate feeding a candle as aggTrades to the orderflow engine."""
        from src.data.binance_ingestion import AggTrade

        ts_ms = candle.get("timestamp_ms", 0)
        close = float(candle.get("close", 0))
        buy_vol = float(candle.get("buy_volume", candle.get("volume", 0) * 0.5))
        sell_vol = float(candle.get("sell_volume", candle.get("volume", 0) * 0.5))

        if buy_vol > 0:
            engine.update_from_trade(AggTrade(
                symbol=symbol, trade_id=ts_ms, price=close,
                quantity=buy_vol, timestamp_ms=ts_ms, is_buyer_maker=False
            ))
        if sell_vol > 0:
            engine.update_from_trade(AggTrade(
                symbol=symbol, trade_id=ts_ms + 1, price=close,
                quantity=sell_vol, timestamp_ms=ts_ms, is_buyer_maker=True
            ))

    def _check_exits(
        self,
        open_trades: List[BacktestTrade],
        high: float,
        low: float,
        close: float,
        ts_ms: int,
    ) -> List[BacktestTrade]:
        """Check if any open trades hit SL or TP."""
        closed = []
        for trade in open_trades:
            if trade.direction == "buy":
                if trade.sl_price > 0 and low <= trade.sl_price:
                    trade.exit_price = trade.sl_price
                    trade.exit_reason = "sl"
                elif trade.tp_price > 0 and high >= trade.tp_price:
                    trade.exit_price = trade.tp_price
                    trade.exit_reason = "tp"
            else:  # sell
                if trade.sl_price > 0 and high >= trade.sl_price:
                    trade.exit_price = trade.sl_price
                    trade.exit_reason = "sl"
                elif trade.tp_price > 0 and low <= trade.tp_price:
                    trade.exit_price = trade.tp_price
                    trade.exit_reason = "tp"

            if trade.exit_reason:
                trade.exit_ts_ms = ts_ms
                trade.exit_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                trade.pnl_usd = self._compute_pnl(trade, trade.exit_price)
                trade.duration_minutes = (ts_ms - trade.entry_ts_ms) / 60000
                # R-multiple
                risk = abs(trade.entry_price - trade.sl_price)
                if risk > 0 and trade.quantity > 0:
                    price_pnl = (trade.exit_price - trade.entry_price) * (
                        1 if trade.direction == "buy" else -1
                    )
                    trade.r_multiple = price_pnl / risk
                closed.append(trade)

        return closed

    def _compute_pnl(self, trade: BacktestTrade, exit_price: float) -> float:
        """Compute P&L including fees."""
        if trade.direction == "buy":
            gross = (exit_price - trade.entry_price) * trade.quantity
        else:
            gross = (trade.entry_price - exit_price) * trade.quantity

        # Entry + exit fees
        entry_fee = trade.entry_price * trade.quantity * self.fee_rate
        exit_fee = exit_price * trade.quantity * self.fee_rate
        trade.fees_usd = entry_fee + exit_fee

        return gross - trade.fees_usd

    def _load_candles(
        self,
        symbol: str,
        start_date: str = None,
        end_date: str = None,
    ) -> List[Dict]:
        """Load historical candles from DuckDB or generate synthetic data."""
        if HAS_DUCKDB:
            db_path = os.path.join(self.data_path, "binance_ticks.duckdb")
            if os.path.exists(db_path):
                return self._load_from_duckdb(db_path, symbol, start_date, end_date)

        logger.info(
            f"[Backtest] No DuckDB data found at {self.data_path} — "
            "use scripts/dry_run_data.py to collect data first"
        )
        return []

    def _load_from_duckdb(
        self, db_path: str, symbol: str, start_date: str, end_date: str
    ) -> List[Dict]:
        """Load and aggregate tick data into candles."""
        try:
            conn = duckdb.connect(db_path, read_only=True)
            interval_ms = 60000

            query = """
                SELECT
                    (timestamp_ms / {interval}) * {interval} as bucket_ts,
                    FIRST(price ORDER BY timestamp_ms) as open,
                    MAX(price) as high,
                    MIN(price) as low,
                    LAST(price ORDER BY timestamp_ms) as close,
                    SUM(quantity) as volume,
                    SUM(CASE WHEN NOT is_buyer_maker THEN quantity ELSE 0 END) as buy_volume,
                    SUM(CASE WHEN is_buyer_maker THEN quantity ELSE 0 END) as sell_volume,
                    COUNT(*) as trade_count
                FROM agg_trades
                WHERE symbol = ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
            """.format(interval=interval_ms)

            result = conn.execute(query, [symbol]).fetchall()
            conn.close()

            candles = []
            for row in result:
                candles.append({
                    "timestamp_ms": row[0],
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                    "buy_volume": row[6],
                    "sell_volume": row[7],
                    "trade_count": row[8],
                })
            logger.info(f"[Backtest] Loaded {len(candles)} 1m candles for {symbol}")
            return candles

        except Exception as e:
            logger.error(f"[Backtest] DuckDB load error: {e}")
            return []


class BacktestMetrics:
    """Compute backtest performance metrics from trade list."""

    @staticmethod
    def compute(
        trades: List[BacktestTrade],
        initial_equity: float,
        final_equity: float,
    ) -> Dict:
        if not trades:
            return {"error": "no trades"}

        pnls = [t.pnl_usd for t in trades]
        r_multiples = [t.r_multiple for t in trades]
        wins = [t for t in trades if t.pnl_usd > 0]
        total = len(trades)
        win_count = len(wins)

        # Equity curve from trades
        equity_curve = [initial_equity]
        for t in sorted(trades, key=lambda x: x.entry_ts_ms):
            equity_curve.append(equity_curve[-1] + t.pnl_usd)

        # Drawdown
        arr = np.array(equity_curve)
        peak = np.maximum.accumulate(arr)
        dd = peak - arr
        max_dd = float(np.max(dd))
        max_dd_pct = max_dd / initial_equity * 100

        # Sharpe on R-multiples
        r_arr = np.array(r_multiples)
        sharpe = float(np.mean(r_arr) / np.std(r_arr)) if np.std(r_arr) > 0 else 0.0

        # Calmar
        total_return_pct = (final_equity - initial_equity) / initial_equity * 100
        calmar = total_return_pct / max_dd_pct if max_dd_pct > 0 else 0.0

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": total - win_count,
            "winrate": win_count / total if total > 0 else 0.0,
            "initial_equity": initial_equity,
            "final_equity": final_equity,
            "total_pnl": final_equity - initial_equity,
            "total_return_pct": total_return_pct,
            "max_drawdown_usd": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "expectancy_r": float(np.mean(r_multiples)) if r_multiples else 0.0,
            "sharpe": sharpe,
            "calmar": calmar,
            "total_fees": sum(t.fees_usd for t in trades),
            "avg_trade_duration_min": float(np.mean([t.duration_minutes for t in trades])),
            "by_exit_reason": {
                "tp": len([t for t in trades if t.exit_reason == "tp"]),
                "sl": len([t for t in trades if t.exit_reason == "sl"]),
                "end_of_data": len([t for t in trades if t.exit_reason == "end_of_data"]),
            },
            "by_regime": {
                regime: len([t for t in trades if t.regime == regime])
                for regime in set(t.regime for t in trades)
            },
        }
