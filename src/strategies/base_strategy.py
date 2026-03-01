from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies"""

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        """
        Initialize the strategy

        Args:
            client: The exchange client (e.g., DeribitClient)
            config: Strategy-specific configuration object
            dependencies: Dictionary of shared services (order_manager, etc.)
        """
        self.client = client
        self.config = config
        self.name = config.name
        self.logger = logging.getLogger(f"strategy.{self.name.lower().replace(' ', '_')}")

        self.order_manager = dependencies.get('order_manager')
        self.position_monitor = dependencies.get('position_monitor')
        self.risk_manager = dependencies.get('risk_manager')
        self.signal_log = dependencies.get('signal_log')

    def _log_blocked(
        self,
        reason: str,
        direction: str,
        price: float,
        sl: float,
        tp: float,
        regime: str = "UNKNOWN",
    ):
        """Registra un segnale bloccato nel SignalLog per analisi post-hoc."""
        if self.signal_log and price > 0 and sl > 0 and tp > 0:
            self.signal_log.log_signal(
                strategy=self.name,
                direction=direction,
                price=price,
                sl=sl,
                tp=tp,
                regime=regime,
                executed=False,
                block_reason=reason,
            )

    def _log_executed(
        self,
        direction: str,
        price: float,
        sl: float,
        tp: float,
        regime: str = "UNKNOWN",
    ):
        """Registra un segnale eseguito nel SignalLog."""
        if self.signal_log and price > 0 and sl > 0 and tp > 0:
            self.signal_log.log_signal(
                strategy=self.name,
                direction=direction,
                price=price,
                sl=sl,
                tp=tp,
                regime=regime,
                executed=True,
                block_reason=None,
            )

    @abstractmethod
    def scan(self) -> List[Dict[str, Any]]:
        """
        Scan the market for entry signals.
        
        Returns:
            List of signal dictionaries (or empty list if no signals)
        """
        pass

    @abstractmethod
    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        """
        Execute an entry based on a signal.
        
        Args:
            signal: The signal dictionary returned by scan()
            
        Returns:
            True if execution was successful, False otherwise
        """
        pass

    @abstractmethod
    def manage_positions(self) -> Dict[str, Any]:
        """
        Monitor and manage open positions (TP/SL/Expiry).
        
        Returns:
            Dictionary with management statistics (e.g., closed_tp, closed_sl)
        """
        pass
