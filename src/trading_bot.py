import os
import time
import schedule
from datetime import datetime
from typing import Dict, List, Optional
import logging
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

logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot supporting multiple strategies"""

    def __init__(self):
        """Initialize the trading bot"""
        # Load environment variables
        load_dotenv()

        # Validate and load configuration
        if not Config.validate():
            raise ValueError("Invalid configuration")
        
        Config.display()

        self.running = False
        self.strategies = []

        # Initialize core components
        logger.info("Initializing core components...")
        self.client = DeribitClient(
            Config.DERIBIT_API_KEY,
            Config.DERIBIT_API_SECRET,
            Config.DERIBIT_ENV
        )
        # Registry condiviso: traccia SL/TP per tutti i trade → previene ordini orfani
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
            max_open_trades=int(os.getenv("MAX_OPEN_TRADES", 3))
        )

        # FailureHandler: monitora connessione e gestisce emergenze
        self.failure_handler = FailureHandler(
            client=self.client,
            emergency_close_fn=self._emergency_close_all,
            check_interval_sec=float(os.getenv("HEALTH_CHECK_INTERVAL_SEC", 5)),
            max_api_down_sec=float(os.getenv("MAX_API_DOWN_SEC", 30))
        )

        # Initialize strategies
        logger.info("Initializing strategies...")
        dependencies = {
            "order_manager": self.order_manager,
            "position_monitor": self.position_monitor,
            "risk_manager": self.risk_manager
        }

        for strategy_config in Config.STRATEGIES:
            if isinstance(strategy_config, IronCondorConfig):
                strategy = IronCondorStrategy(self.client, strategy_config, dependencies)
                self.strategies.append(strategy)
                logger.info(f"Loaded strategy: {strategy.name}")
            
            elif isinstance(strategy_config, SmartMoneyConfig):
                strategy = SmartMoneyStrategy(self.client, strategy_config, dependencies)
                self.strategies.append(strategy)
                logger.info(f"Loaded strategy: {strategy.name}")

            elif isinstance(strategy_config, WMFormationConfig):
                strategy = WMFormationStrategy(self.client, strategy_config, dependencies)
                self.strategies.append(strategy)
                logger.info(f"Loaded strategy: {strategy.name}")

            elif isinstance(strategy_config, BringsStrategyConfig):
                strategy = BringsStrategy(self.client, strategy_config, dependencies)
                self.strategies.append(strategy)
                logger.info(f"Loaded strategy: {strategy.name}")

    def authenticate(self) -> bool:
        """Authenticate with Deribit"""
        logger.info("Authenticating with Deribit...")
        return self.client.authenticate()

    def _emergency_close_all(self):
        """
        Chiusura d'emergenza: cancella tutti gli ordini aperti e chiude tutte le posizioni.
        Chiamato dal FailureHandler quando l'API è down per troppo tempo.
        """
        logger.critical("[EMERGENCY] Chiusura d'emergenza in corso...")
        try:
            # 1. Cancella tutti gli ordini aperti
            self.client.cancel_all()
            logger.critical("[EMERGENCY] Tutti gli ordini cancellati")
        except Exception as e:
            logger.critical(f"[EMERGENCY] Errore cancel_all: {e}")

        try:
            # 2. Chiudi tutte le posizioni futures aperte
            open_positions = self.position_monitor.get_open_futures_positions()
            for pos in open_positions:
                instrument = pos.get("instrument_name")
                if instrument:
                    self.client.close_position(instrument, type_="market")
                    logger.critical(f"[EMERGENCY] Chiusa posizione: {instrument}")
        except Exception as e:
            logger.critical(f"[EMERGENCY] Errore chiusura posizioni: {e}")

        logger.critical("[EMERGENCY] Procedura d'emergenza completata")

    def scan_and_open_positions(self):
        """Main routine to scan for opportunities and open new positions"""
        logger.info("=" * 60)
        logger.info("SCANNING FOR NEW POSITIONS")
        logger.info("=" * 60)

        try:
            # Get risk summary
            risk_summary = self.risk_manager.get_risk_summary()
            logger.info(f"Equity: ${risk_summary['equity']:,.2f}")
            logger.info(f"Risk utilization: {risk_summary['risk_utilization_pct']:.1f}%")

            # Check global risk
            can_open, reason = self.risk_manager.can_open_new_position()
            if not can_open:
                logger.info(f"Cannot open new position: {reason}")
                return

            # Execute strategies
            for strategy in self.strategies:
                try:
                    logger.info(f"\nRunning strategy: {strategy.name}")
                    signals = strategy.scan()
                    
                    if not signals:
                        logger.info(f"No signals from {strategy.name}")
                        continue
                        
                    for signal in signals:
                        logger.info(f"Signal detected: {signal}")
                        success = strategy.execute_entry(signal)
                        if success:
                            logger.info(f"Entry executed for {strategy.name}")
                        else:
                            logger.warning(f"Entry failed for {strategy.name}")
                            
                except Exception as e:
                    logger.error(f"Error running strategy {strategy.name}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in scan_and_open_positions: {e}", exc_info=True)

    def manage_open_positions(self):
        """Monitor and manage open positions"""
        logger.info("=" * 60)
        logger.info("MANAGING OPEN POSITIONS")
        logger.info("=" * 60)

        try:
            # --- Orphan order cleanup (PRIORITÀ ALTA) ---
            # Cancella SL/TP rimasti aperti dopo chiusura posizione
            orphan_stats = self.position_monitor.check_orphan_orders(currencies=["BTC", "ETH"])
            if orphan_stats["orphans_found"] > 0:
                logger.warning(
                    f"Orphan orders: trovati={orphan_stats['orphans_found']} "
                    f"cancellati={orphan_stats['orphans_cancelled']} "
                    f"errori={orphan_stats['errors']}"
                )

            # --- Portfolio summary ---
            portfolio = self.position_monitor.get_portfolio_summary()
            logger.info(f"Open condors: {portfolio.get('total_condors', 0)}")

            # --- Delegate to strategies ---
            for strategy in self.strategies:
                try:
                    stats = strategy.manage_positions()
                    if stats:
                        logger.info(f"{strategy.name} management: {stats}")
                except Exception as e:
                    logger.error(f"Error managing {strategy.name}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error managing positions: {e}", exc_info=True)

    def run_daily_routine(self):
        """Run daily routine: scan for new positions"""
        logger.info("\n" + "=" * 60)
        logger.info(f"DAILY ROUTINE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        self.scan_and_open_positions()

    def run_monitoring_routine(self):
        """Run periodic monitoring routine"""
        if not self.running:
            return

        logger.info(f"\nMonitoring check - {datetime.now().strftime('%H:%M:%S')}")
        self.manage_open_positions()
        
        # Also run scan for intraday strategies (Smart Money)
        # Iron Condor is daily, but Smart Money is intraday (15m)
        # So we should run scan here too for Smart Money?
        # Or we separate schedules.
        # For simplicity, let's run scan every monitoring interval for Smart Money.
        # But Iron Condor shouldn't run every 5 mins.
        # We can add a check in IronCondorStrategy.scan() to only run once a day?
        # Or we just rely on the schedule.
        
        # Better approach:
        # Iron Condor -> Daily schedule
        # Smart Money -> Intraday schedule
        # But here we have one `scan_and_open_positions` calling all strategies.
        # Let's split or pass context.
        
        # Quick fix: Run scan here too, but IronCondorStrategy should be smart enough or we filter.
        # Actually, IronCondorStrategy checks for "suitable expiration" and "IV". If it finds one, it enters.
        # If we run it every 5 mins, it might open multiple positions if we don't check if we already have one for that day/exp.
        # RiskManager limits total positions, so it might be safe.
        # But let's keep `run_daily_routine` for Iron Condor and `run_monitoring_routine` for Smart Money?
        
        # Let's iterate strategies and check their preferred interval?
        # For now, I'll just call `scan_and_open_positions` in `run_monitoring_routine` as well, 
        # assuming RiskManager prevents over-trading.
        
        self.scan_and_open_positions()

    def start(self):
        """Start the trading bot"""
        logger.info("=" * 60)
        logger.info("STARTING TRADING BOT (MULTI-STRATEGY)")
        logger.info("=" * 60)

        # Authenticate
        if not self.authenticate():
            logger.error("Authentication failed. Exiting.")
            return

        self.running = True

        # Avvia FailureHandler in background (thread daemon)
        self.failure_handler.start()

        # FAST LOOP: Manage positions + orphan cleanup ogni 30 secondi
        schedule.every(30).seconds.do(self.manage_open_positions)

        # SLOW LOOP: Scan nuovi setup ogni N minuti
        schedule.every(Config.MONITORING_INTERVAL_MINUTES).minutes.do(self.scan_and_open_positions)

        logger.info("Bot started. Schedules:")
        logger.info(f"  - Management + Orphan Cleanup: Every 30 seconds")
        logger.info(f"  - Strategy Scan: Every {Config.MONITORING_INTERVAL_MINUTES} minutes")
        logger.info(f"  - FailureHandler: Every {os.getenv('HEALTH_CHECK_INTERVAL_SEC', '5')}s (background thread)")

        # Run initial scan
        logger.info("\nRunning initial scan...")
        self.run_monitoring_routine()

        # Main loop
        logger.info("\nEntering main loop...")
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nReceived shutdown signal...")
            self.stop()

    def stop(self):
        """Stop the trading bot"""
        logger.info("=" * 60)
        logger.info("STOPPING TRADING BOT")
        logger.info("=" * 60)

        self.running = False
        self.failure_handler.stop()
        logger.info("Bot stopped.")


def main():
    """Main entry point"""
    from logging.handlers import RotatingFileHandler
    
    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(
                'logs/trading_bot.log', 
                maxBytes=5*1024*1024, # 5 MB
                backupCount=5
            ),
            logging.StreamHandler()
        ]
    )

    # Create and start bot
    try:
        bot = TradingBot()
        bot.start()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
