"""
AsyncTradingBot — asyncio-based trading bot with full volumetric pipeline.

Replaces the schedule-based TradingBot with proper async architecture:

  Tasks running concurrently:
    1. binance_data_task    — WebSocket streams (aggTrade, depth, liquidations, OI)
    2. orderbook_task       — routes depth updates to OrderBookEngine
    3. orderflow_task       — routes trades to OrderflowEngine
    4. management_task      — position management + orphan cleanup (every 30s)
    5. scan_task            — strategy scan (every N minutes)
    6. regime_task          — regime classification (every 1 minute)
    7. scoring_task         — scoring engine update (every 5 minutes)
    8. monitoring_task      — dashboard update + alerts (every 60s)
    9. failure_handler      — background thread (not async, uses daemon thread)

Entry point: AsyncTradingBot.start() — runs until KeyboardInterrupt or error.

Backward compatible: all existing strategies (SmartMoney, WM, Brings) still work.
New strategies (VolumeBreakout, MeanReversion, etc.) get orderflow context automatically.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from config import Config, IronCondorConfig, SmartMoneyConfig, WMFormationConfig, BringsStrategyConfig
from src.core.deribit_client import DeribitClient
from src.core.order_manager import OrderManager
from src.core.order_registry import OrderRegistry
from src.core.position_monitor import PositionMonitor
from src.core.risk_manager import RiskManager
from src.core.failure_handler import FailureHandler
from src.strategies.iron_condor import IronCondorStrategy
from src.strategies.smart_money import SmartMoneyStrategy
from src.strategies.wm_formation import WMFormationStrategy
from src.strategies.brings_strategy import BringsStrategy

# New modules (soft imports — graceful degradation if missing)
try:
    from src.data.binance_ingestion import BinanceDataIngestion
    from src.data.orderbook_engine import OrderBookEngine
    from src.data.data_quality import DataQualityLayer
    HAS_DATA_LAYER = True
except ImportError as e:
    HAS_DATA_LAYER = False
    logging.warning(f"Data layer not available: {e}")

try:
    from src.engine.orderflow import OrderflowEngine
    from src.engine.regime import RegimeDetector, Regime
    from src.engine.scoring import ScoringEngine
    HAS_ENGINE = True
except ImportError as e:
    HAS_ENGINE = False
    logging.warning(f"Engine layer not available: {e}")

try:
    from src.strategies.volume_breakout import VolumeBreakoutStrategy
    from src.strategies.mean_reversion import MeanReversionStrategy
    from src.strategies.liq_squeeze import LiquidationSqueezeStrategy
    from src.strategies.imbalance_scalp import ImbalanceScalpStrategy
    HAS_NEW_STRATEGIES = True
except ImportError as e:
    HAS_NEW_STRATEGIES = False
    logging.warning(f"New strategies not available: {e}")

# Quant-validated strategies (TrendBreakdown, FundingSqueeze, MacroCore)
try:
    from src.strategies.trend_breakdown import TrendBreakdownStrategy
    from src.strategies.funding_squeeze import FundingSqueezeStrategy
    from src.strategies.macro_core import MacroCoreStrategy
    from src.data.kline_provider import BinanceKlineProvider
    HAS_QUANT_STRATEGIES = True
except ImportError as e:
    HAS_QUANT_STRATEGIES = False
    logging.warning(f"Quant strategies not available: {e}")

try:
    from src.monitoring.alerts import TelegramAlerts
    HAS_ALERTS = True
except ImportError:
    HAS_ALERTS = False

try:
    from src.journal.trade_logger import TradeLogger
    HAS_JOURNAL = True
except ImportError:
    HAS_JOURNAL = False

try:
    from src.journal.signal_log import SignalLog
    HAS_SIGNAL_LOG = True
except ImportError:
    HAS_SIGNAL_LOG = False

# New strategy config dataclasses — added dynamically
try:
    from config import VolumeBreakoutConfig, MeanReversionConfig, LiqSqueezeConfig, ImbalanceScalpConfig
    HAS_NEW_CONFIGS = True
except ImportError:
    HAS_NEW_CONFIGS = False

try:
    from config import TrendBreakdownConfig, FundingSqueezeConfig, MacroCoreConfig
    HAS_QUANT_CONFIGS = True
except ImportError:
    HAS_QUANT_CONFIGS = False

logger = logging.getLogger(__name__)


class AsyncTradingBot:
    """
    Full-featured async trading bot with volumetric pipeline.

    Usage:
        bot = AsyncTradingBot()
        asyncio.run(bot.start())
    """

    def __init__(self):
        load_dotenv()

        if not Config.validate():
            raise ValueError("Invalid configuration")
        Config.display()

        self.running = False
        self.strategies: List[Any] = []

        # Symbols to track on Binance (for data layer)
        self.symbols = os.getenv("BINANCE_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")

        # --- Core components (same as sync bot) ---
        logger.info("Initializing core components...")
        self.client = DeribitClient(
            Config.DERIBIT_API_KEY,
            Config.DERIBIT_API_SECRET,
            Config.DERIBIT_ENV,
        )
        self.registry = OrderRegistry()
        self.order_manager = OrderManager(self.client, registry=self.registry)
        self.position_monitor = PositionMonitor(self.client, self.order_manager, registry=self.registry)
        self.risk_manager = RiskManager(
            self.client,
            self.position_monitor,
            initial_equity=float(os.getenv("INITIAL_EQUITY", 10000)),
            risk_per_condor=float(os.getenv("RISK_PER_CONDOR", 0.01)),
            max_portfolio_risk=float(os.getenv("MAX_PORTFOLIO_RISK", 0.03)),
            base_risk_pct=float(os.getenv("BASE_RISK_PCT", 0.01)),
            max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT", 0.03)),
            max_open_trades=int(os.getenv("MAX_OPEN_TRADES", 3)),
        )
        self.failure_handler = FailureHandler(
            client=self.client,
            emergency_close_fn=self._emergency_close_all,
            check_interval_sec=float(os.getenv("HEALTH_CHECK_INTERVAL_SEC", 5)),
            max_api_down_sec=float(os.getenv("MAX_API_DOWN_SEC", 30)),
        )

        # --- Volumetric pipeline ---
        self.data_ingestion: Optional[Any] = None
        self.orderbook_engine: Optional[Any] = None
        self.orderflow_engine: Optional[Any] = None
        self.regime_detector: Optional[Any] = None
        self.scoring_engine: Optional[Any] = None
        self.data_quality: Optional[Any] = None
        self.alerts: Optional[Any] = None
        self.trade_logger: Optional[Any] = None
        self._active_trades: Dict[str, Dict] = {}  # trade_id -> open trade info

        if HAS_DATA_LAYER:
            self.data_ingestion = BinanceDataIngestion(
                symbols=self.symbols,
                storage_path=os.getenv("DATA_STORAGE_PATH", "data/raw"),
                oi_poll_interval_sec=float(os.getenv("OI_POLL_INTERVAL_SEC", 30)),
                persist_to_db=os.getenv("PERSIST_TICKS", "true").lower() == "true",
            )
            self.orderbook_engine = OrderBookEngine(symbols=self.symbols)
            self.data_quality = DataQualityLayer()
            logger.info("Data layer initialized")

        if HAS_ENGINE:
            self.orderflow_engine = OrderflowEngine(symbols=self.symbols)
            self.regime_detector = RegimeDetector()
            self.scoring_engine = ScoringEngine(
                persistence_path=os.getenv("SCORING_STATE_PATH", "data/scoring_state.json")
            )
            logger.info("Engine layer initialized")

        if HAS_ALERTS:
            self.alerts = TelegramAlerts(
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
                chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            )

        if HAS_JOURNAL:
            self.trade_logger = TradeLogger(
                db_path=os.getenv("JOURNAL_DB_PATH", "data/journal.db")
            )

        self.signal_log = None
        if HAS_SIGNAL_LOG:
            self.signal_log = SignalLog(
                db_path=os.getenv("SIGNAL_LOG_DB_PATH", "data/signal_log.db")
            )

        # Shared REST kline/funding provider (1h candles for trend strategies)
        self.kline_provider = BinanceKlineProvider() if HAS_QUANT_STRATEGIES else None

        # --- Build dependencies dict for strategies ---
        self.dependencies = {
            "order_manager": self.order_manager,
            "position_monitor": self.position_monitor,
            "risk_manager": self.risk_manager,
            "orderflow_engine": self.orderflow_engine,
            "regime_detector": self.regime_detector,
            "scoring_engine": self.scoring_engine,
            "data_ingestion": self.data_ingestion,
            "trade_logger": self.trade_logger,
            "signal_log": self.signal_log,
            "kline_provider": self.kline_provider,
        }

        # --- Load strategies ---
        self._load_strategies()

        # --- Tracking ---
        self._last_regime: Dict[str, Any] = {}
        self._scan_interval_sec = Config.MONITORING_INTERVAL_MINUTES * 60
        self._regime_update_interval_sec = 60
        self._management_interval_sec = 30
        self._scoring_update_interval_sec = 300

    # ------------------------------------------------------------------
    # Strategy loading
    # ------------------------------------------------------------------

    def _load_strategies(self):
        """Load all configured strategies."""
        logger.info("Loading strategies...")

        for strategy_config in Config.STRATEGIES:
            strategy = None

            if isinstance(strategy_config, IronCondorConfig):
                strategy = IronCondorStrategy(self.client, strategy_config, self.dependencies)
            elif isinstance(strategy_config, SmartMoneyConfig):
                strategy = SmartMoneyStrategy(self.client, strategy_config, self.dependencies)
            elif isinstance(strategy_config, WMFormationConfig):
                strategy = WMFormationStrategy(self.client, strategy_config, self.dependencies)
            elif isinstance(strategy_config, BringsStrategyConfig):
                strategy = BringsStrategy(self.client, strategy_config, self.dependencies)
            elif HAS_NEW_CONFIGS and HAS_NEW_STRATEGIES:
                if isinstance(strategy_config, VolumeBreakoutConfig):
                    strategy = VolumeBreakoutStrategy(self.client, strategy_config, self.dependencies)
                elif isinstance(strategy_config, MeanReversionConfig):
                    strategy = MeanReversionStrategy(self.client, strategy_config, self.dependencies)
                elif isinstance(strategy_config, LiqSqueezeConfig):
                    strategy = LiquidationSqueezeStrategy(self.client, strategy_config, self.dependencies)
                elif isinstance(strategy_config, ImbalanceScalpConfig):
                    strategy = ImbalanceScalpStrategy(self.client, strategy_config, self.dependencies)

            if strategy is None and HAS_QUANT_CONFIGS and HAS_QUANT_STRATEGIES:
                if isinstance(strategy_config, TrendBreakdownConfig):
                    strategy = TrendBreakdownStrategy(self.client, strategy_config, self.dependencies)
                elif isinstance(strategy_config, FundingSqueezeConfig):
                    strategy = FundingSqueezeStrategy(self.client, strategy_config, self.dependencies)
                elif isinstance(strategy_config, MacroCoreConfig):
                    strategy = MacroCoreStrategy(self.client, strategy_config, self.dependencies)

            if strategy:
                self.strategies.append(strategy)
                logger.info(f"  Loaded: {strategy.name}")

        logger.info(f"Total strategies loaded: {len(self.strategies)}")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def start(self):
        """Start the async trading bot."""
        logger.info("=" * 60)
        logger.info("STARTING ASYNC TRADING BOT (MULTI-STRATEGY + VOLUMETRIC)")
        logger.info("=" * 60)

        # Authenticate with Deribit
        if not self.client.authenticate():
            logger.error("Authentication failed. Exiting.")
            return

        self.running = True

        # Start FailureHandler (background thread)
        self.failure_handler.start()

        # Create all async tasks
        tasks = [
            asyncio.create_task(self._management_loop(), name="management"),
            asyncio.create_task(self._scan_loop(), name="scan"),
            asyncio.create_task(self._regime_loop(), name="regime"),
            asyncio.create_task(self._monitoring_loop(), name="monitoring"),
        ]

        # Add data layer tasks if available
        if self.data_ingestion:
            await self.data_ingestion.start()
            tasks.append(asyncio.create_task(self._orderbook_loop(), name="orderbook"))
            tasks.append(asyncio.create_task(self._orderflow_loop(), name="orderflow"))
            logger.info("Binance data streams started")

        # Signal outcome tracker
        if self.signal_log:
            tasks.append(asyncio.create_task(self._outcome_tracker_loop(), name="outcome_tracker"))

        logger.info("Bot running. Tasks:")
        for t in tasks:
            logger.info(f"  - {t.get_name()}")

        # Run initial scan immediately
        await self._scan_once()

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt")
        finally:
            await self.stop()

    async def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping bot...")
        self.running = False
        self.failure_handler.stop()
        if self.data_ingestion:
            await self.data_ingestion.stop()
        if self.trade_logger:
            self.trade_logger.close()
        logger.info("Bot stopped.")

    # ------------------------------------------------------------------
    # Async task loops
    # ------------------------------------------------------------------

    async def _management_loop(self):
        """Position management + orphan cleanup every 30s."""
        while self.running:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._manage_positions_sync
                )
            except Exception as e:
                logger.error(f"[Management] Error: {e}", exc_info=True)
            await asyncio.sleep(self._management_interval_sec)

    async def _scan_loop(self):
        """Strategy scanning every N minutes."""
        await asyncio.sleep(self._scan_interval_sec)  # skip first immediate (handled manually)
        while self.running:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._scan_once_sync
                )
            except Exception as e:
                logger.error(f"[Scan] Error: {e}", exc_info=True)
            await asyncio.sleep(self._scan_interval_sec)

    async def _regime_loop(self):
        """Regime detection update every minute."""
        while self.running:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._update_regimes
                )
            except Exception as e:
                logger.debug(f"[Regime] Error: {e}")
            await asyncio.sleep(self._regime_update_interval_sec)

    async def _orderbook_loop(self):
        """Route depth updates from BinanceDataIngestion to OrderBookEngine."""
        if not self.data_ingestion or not self.orderbook_engine:
            return

        # --- Binance protocol: fetch REST snapshot BEFORE processing WS updates ---
        logger.info("[OrderBook] Fetching REST depth snapshots...")
        snapshots = await self.data_ingestion.fetch_depth_snapshots()
        for sym, snap in snapshots.items():
            self.orderbook_engine.apply_snapshot(
                sym, snap["bids"], snap["asks"],
                last_update_id=snap["lastUpdateId"],
            )
        if not snapshots:
            logger.warning("[OrderBook] No depth snapshots received — book may have gaps")

        while self.running:
            try:
                depth = await asyncio.wait_for(
                    self.data_ingestion.depth_queue.get(),
                    timeout=5.0,
                )
                self.orderbook_engine.apply_update(depth)

                # Route book snapshot to orderflow engine
                if self.orderflow_engine:
                    snap = self.orderbook_engine.get_snapshot(depth.symbol)
                    if snap:
                        self.orderflow_engine.update_from_book(snap)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"[OrderBook] Error: {e}")

    async def _orderflow_loop(self):
        """Route aggTrades and liquidations to OrderflowEngine."""
        if not self.data_ingestion or not self.orderflow_engine:
            return
        while self.running:
            try:
                # Process trades (higher priority)
                try:
                    trade = self.data_ingestion.trade_queue.get_nowait()
                    self.orderflow_engine.update_from_trade(trade)
                except asyncio.QueueEmpty:
                    pass

                # Process liquidations
                try:
                    liq = self.data_ingestion.liquidation_queue.get_nowait()
                    self.orderflow_engine.update_from_liquidation(liq)

                    # Alert on large liquidations
                    if self.alerts and liq.quantity > 10.0:
                        self.alerts.send_custom(
                            f"🔥 Large liquidation: {liq.symbol} {liq.side} "
                            f"{liq.quantity:.2f} @ ${liq.price:,.2f}"
                        )
                except asyncio.QueueEmpty:
                    pass

                # OI updates (every 30s)
                for sym in self.symbols:
                    oi = self.data_ingestion.get_open_interest(sym)
                    if oi:
                        self.orderflow_engine.update_from_oi(oi)

                await asyncio.sleep(0.01)  # 10ms yield

            except Exception as e:
                logger.debug(f"[Orderflow] Error: {e}")
                await asyncio.sleep(0.1)

    async def _outcome_tracker_loop(self):
        """
        Ogni 30 minuti controlla i segnali bloccati e verifica se
        avrebbero colpito TP o SL al prezzo corrente.
        Permette di analizzare le opportunita' perse.
        """
        await asyncio.sleep(1800)  # primo check dopo 30 min
        while self.running:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._check_pending_outcomes
                )
            except Exception as e:
                logger.debug(f"[OutcomeTracker] Error: {e}")
            await asyncio.sleep(1800)  # ogni 30 min

    def _check_pending_outcomes(self):
        """Risolve i segnali bloccati che hanno raggiunto TP o SL."""
        if not self.signal_log or not self.orderflow_engine:
            return
        try:
            pending = self.signal_log.get_pending(max_age_hours=24)
            if not pending:
                return
            resolved = 0
            for sig in pending:
                symbol = self.symbols[0] if self.symbols else "BTCUSDT"
                snap = self.orderflow_engine.get_snapshot(symbol)
                if not snap or snap.price <= 0:
                    continue
                current_price = snap.price
                sl = sig["sl"]
                tp = sig["tp"]
                direction = sig["direction"]
                entry = sig["price"]
                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                outcome = None
                exit_price = current_price
                if direction == "BUY":
                    if current_price >= tp:
                        outcome, exit_price = "WIN", tp
                    elif current_price <= sl:
                        outcome, exit_price = "LOSS", sl
                else:  # SELL
                    if current_price <= tp:
                        outcome, exit_price = "WIN", tp
                    elif current_price >= sl:
                        outcome, exit_price = "LOSS", sl
                if outcome:
                    pnl_r = abs(exit_price - entry) / risk
                    if outcome == "LOSS":
                        pnl_r = -1.0
                    self.signal_log.update_outcome(sig["id"], outcome, exit_price, pnl_r)
                    resolved += 1
            if resolved > 0:
                logger.info(f"[OutcomeTracker] Risolti {resolved} segnali bloccati")
        except Exception as e:
            logger.debug(f"[OutcomeTracker] check error: {e}")

    async def _monitoring_loop(self):
        """Periodic monitoring: log stats, send daily summary."""
        last_daily_report = time.time()
        while self.running:
            try:
                await asyncio.sleep(60)
                if not self.running:
                    break

                # Log status every minute
                self._log_status()

                # Daily P&L report
                if time.time() - last_daily_report > 86400:
                    self._send_daily_report()
                    last_daily_report = time.time()

            except Exception as e:
                logger.debug(f"[Monitoring] Error: {e}")

    # ------------------------------------------------------------------
    # Sync implementations (run in executor)
    # ------------------------------------------------------------------

    def _manage_positions_sync(self):
        """Synchronous position management (runs in thread executor)."""
        try:
            # 0. Detect and log closed positions
            self._check_closed_positions()

            # 1. Orphan cleanup (highest priority)
            orphan_stats = self.position_monitor.check_orphan_orders(currencies=["BTC", "ETH"])
            if orphan_stats.get("orphans_found", 0) > 0:
                logger.warning(f"Orphan orders: {orphan_stats}")

            # 2. Portfolio summary
            portfolio = self.position_monitor.get_portfolio_summary()

            # 3. Each strategy manages its own positions
            for strategy in self.strategies:
                try:
                    stats = strategy.manage_positions()
                    if stats and stats.get("status") != "managed_by_monitor":
                        logger.info(f"{strategy.name} management: {stats}")
                except Exception as e:
                    logger.error(f"[{strategy.name}] manage error: {e}")

        except Exception as e:
            logger.error(f"[Management] Error: {e}", exc_info=True)

    def _scan_once_sync(self):
        """Synchronous strategy scan (runs in thread executor)."""
        try:
            risk_summary = self.risk_manager.get_risk_summary()
            logger.info(
                f"SCAN — Equity: ${risk_summary.get('equity', 0):,.2f} | "
                f"Risk: {risk_summary.get('risk_utilization_pct', 0):.1f}%"
            )

            can_open, reason = self.risk_manager.can_open_new_position()
            if not can_open:
                logger.info(f"Risk gate: {reason}")
                return

            current_regime = self._get_primary_regime()

            for strategy in self.strategies:
                try:
                    # Scoring gate (new strategies only)
                    if self.scoring_engine and hasattr(strategy, "orderflow_engine"):
                        allowed, score_reason = self.scoring_engine.should_trade(
                            strategy.__class__.__name__, current_regime
                        )
                        if not allowed:
                            logger.debug(f"[{strategy.name}] Scoring blocked: {score_reason}")
                            continue

                    signals = strategy.scan()
                    for signal in signals:
                        logger.info(f"Signal from {strategy.name}: {signal.get('type')} {signal.get('direction')}")
                        success = strategy.execute_entry(signal)
                        if success:
                            self._on_trade_open(signal, strategy.name, current_regime)
                            if self.alerts:
                                self.alerts.send_trade_open(
                                    instrument=signal.get("instrument", ""),
                                    direction=signal.get("direction", ""),
                                    entry_price=signal.get("price", 0),
                                    sl_price=signal.get("stop_loss", 0),
                                    tp_price=signal.get("take_profit", 0),
                                    strategy=strategy.name,
                                    regime=signal.get("regime", current_regime),
                                )

                except Exception as e:
                    logger.error(f"[{strategy.name}] scan error: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[Scan] Error: {e}", exc_info=True)

    def _on_trade_open(self, signal: Dict, strategy_name: str, regime: str):
        """Called after execute_entry() succeeds — logs to positions.log and tracks for close."""
        if not self.trade_logger:
            return
        try:
            trade_id = f"{strategy_name}_{int(time.time())}"
            qty_usd = signal.get("_qty_usd", 0.0)
            price = signal.get("price", 0.0)
            qty_btc = qty_usd / price if price > 0 else 0.0
            equity = self.risk_manager.get_risk_summary().get("equity", 0.0) if self.risk_manager else 0.0

            self.trade_logger.log_entry_from_signal(
                trade_id=trade_id,
                signal=signal,
                quantity=qty_btc,
                regime=regime,
                equity=equity,
            )
            self._active_trades[trade_id] = {
                "instrument": signal.get("instrument", "BTC-PERPETUAL"),
                "direction": signal.get("direction", "buy"),
                "entry_price": price,
                "stop_loss": signal.get("stop_loss", 0.0),
                "take_profit": signal.get("take_profit", 0.0),
                "qty_btc": qty_btc,
                "equity_at_entry": equity,
                "strategy": strategy_name,
            }
            logger.info(f"[PositionLog] OPEN logged: {trade_id}")
        except Exception as e:
            logger.debug(f"[PositionLog] _on_trade_open error: {e}")

    def _check_closed_positions(self):
        """Detect positions closed since last check and log them.

        Safety: only logs a close if the position was previously seen as open on
        Deribit (_seen_open flag). This prevents false closes when a LIMIT entry
        order is placed but never filled (position never existed on Deribit).
        """
        if not self._active_trades or not self.trade_logger:
            return
        try:
            open_pos = self.client.get_futures_positions("BTC")
            open_instruments = {
                p.get("instrument_name") for p in open_pos
                if p.get("instrument_name") and abs(p.get("size", 0)) > 0
            }
            for trade_id, info in list(self._active_trades.items()):
                if info["instrument"] in open_instruments:
                    info["_seen_open"] = True  # confirmed position exists on Deribit
                elif info.get("_seen_open"):
                    # Was open, now gone -> position closed (TP or SL hit)
                    exit_price = self._get_last_fill_price(info["instrument"]) or info["entry_price"]
                    direction = info["direction"].lower()
                    pnl = (exit_price - info["entry_price"]) * info["qty_btc"] if direction == "buy" \
                        else (info["entry_price"] - exit_price) * info["qty_btc"]

                    tp = info.get("take_profit", 0)
                    sl = info.get("stop_loss", 0)
                    if tp and sl:
                        reason = "tp" if abs(exit_price - tp) < abs(exit_price - sl) else "sl"
                    else:
                        reason = "unknown"

                    self.trade_logger.log_exit(trade_id, exit_price=exit_price, pnl_usd=pnl, exit_reason=reason)
                    del self._active_trades[trade_id]
                    logger.info(f"[PositionLog] CLOSE logged: {trade_id} pnl=${pnl:+.2f} ({reason})")
                # else: entry limit not yet filled, wait
        except Exception as e:
            logger.debug(f"[PositionLog] _check_closed_positions error: {e}")

    def _get_last_fill_price(self, instrument: str) -> Optional[float]:
        """Get price of last trade fill for an instrument from Deribit."""
        try:
            result = self.client._request(
                "GET", "/private/get_user_trades_by_instrument",
                params={"instrument_name": instrument, "count": 1, "sorting": "desc"},
                private=True,
            )
            trades = result.get("result", {}).get("trades", [])
            return float(trades[0]["price"]) if trades else None
        except Exception:
            return None

    async def _scan_once(self):
        """Async wrapper for initial scan."""
        await asyncio.get_event_loop().run_in_executor(None, self._scan_once_sync)

    def _update_regimes(self):
        """Update regime detection for all symbols."""
        if not self.regime_detector or not self.orderflow_engine:
            return
        for sym in self.symbols:
            try:
                candles = self.orderflow_engine.get_candle_history(sym, 900, n=50)
                if len(candles) < 20:
                    continue
                snap = self.orderflow_engine.get_snapshot(sym)
                cvd = snap.cvd_15m if snap else 0.0
                imb = snap.book_imbalance if snap else 0.5

                old_regime = self._last_regime.get(sym)
                new_regime = self.regime_detector.detect(
                    candles, symbol=sym, timeframe_minutes=15,
                    cvd=cvd, book_imbalance=imb
                )
                self._last_regime[sym] = new_regime

                if (old_regime and old_regime.regime != new_regime.regime
                        and new_regime.confidence > 0.5):
                    logger.info(
                        f"[Regime] {sym}: {old_regime.regime.value} -> "
                        f"{new_regime.regime.value} ({new_regime.confidence:.0%})"
                    )
                    if self.alerts:
                        self.alerts.send_regime_change(
                            sym,
                            old_regime.regime.value,
                            new_regime.regime.value,
                            new_regime.confidence,
                        )

            except Exception as e:
                logger.debug(f"[Regime] {sym} error: {e}")

    # ------------------------------------------------------------------
    # Emergency + helpers
    # ------------------------------------------------------------------

    def _emergency_close_all(self):
        """Emergency: cancel all orders + close all positions."""
        logger.critical("[EMERGENCY] Closing all positions...")
        if self.alerts:
            self.alerts.send_emergency("API down > max threshold")
        try:
            self.client.cancel_all()
        except Exception as e:
            logger.critical(f"[EMERGENCY] cancel_all error: {e}")
        try:
            for pos in self.position_monitor.get_open_futures_positions():
                instrument = pos.get("instrument_name")
                if instrument:
                    self.client.close_position(instrument, type_="market")
        except Exception as e:
            logger.critical(f"[EMERGENCY] close positions error: {e}")

    def _get_primary_regime(self) -> str:
        """Get primary symbol regime string."""
        primary_sym = self.symbols[0] if self.symbols else "BTCUSDT"
        regime = self._last_regime.get(primary_sym)
        if regime:
            return regime.regime.value
        return "UNKNOWN"

    def _log_status(self):
        """Log current bot status."""
        try:
            risk = self.risk_manager.get_risk_summary()
            positions = self.position_monitor.get_open_futures_positions()
            regime_str = self._get_primary_regime()

            logger.info(
                f"STATUS — Equity: ${risk.get('equity', 0):,.2f} | "
                f"Positions: {len(positions)} | "
                f"Regime: {regime_str} | "
                f"Strategies: {len(self.strategies)}"
            )

            if self.orderflow_engine:
                for sym in self.symbols[:1]:  # first symbol only
                    snap = self.orderflow_engine.get_snapshot(sym)
                    if snap:
                        logger.info(
                            f"  {sym}: CVD1m={snap.cvd_1m:+.4f} "
                            f"Imb={snap.book_imbalance:.3f} "
                            f"VolZ={snap.volume_zscore:.2f} "
                            f"OI%={snap.oi_change_pct:+.2f}%"
                        )
        except Exception as e:
            logger.debug(f"[Status] Error: {e}")

    def _send_daily_report(self):
        """Send daily P&L summary."""
        try:
            if self.alerts:
                risk = self.risk_manager.get_risk_summary()
                daily_stats = self.risk_manager.get_daily_stats()
                self.alerts.send_daily_pnl(
                    daily_pnl=daily_stats.get("daily_pnl", 0),
                    total_trades=daily_stats.get("trade_count", 0),
                    winning_trades=0,
                    equity=risk.get("equity", 0),
                )
        except Exception as e:
            logger.debug(f"[DailyReport] Error: {e}")


def main():
    """Entry point for async bot."""
    from logging.handlers import RotatingFileHandler

    log_level = os.getenv("LOG_LEVEL", "INFO")
    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler("logs/async_bot.log", maxBytes=5 * 1024 * 1024, backupCount=5),
            logging.StreamHandler(),
        ],
    )

    try:
        bot = AsyncTradingBot()
        asyncio.run(bot.start())
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
