"""
Metrics tracking system for trading strategies
"""
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


class StrategyMetrics:
    """Track strategy performance and diagnostic metrics"""
    
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.scans = 0
        self.time_window_active = 0
        self.time_window_inactive = 0
        self.sweeps_detected = 0
        self.flow_analyzed = 0
        self.signals_generated = 0
        self.entries_executed = 0
        self.entries_failed = 0
        self.last_reset = datetime.now()
        
    def increment(self, metric: str):
        """Increment a metric counter"""
        if hasattr(self, metric):
            setattr(self, metric, getattr(self, metric) + 1)
        else:
            logger.warning(f"Unknown metric: {metric}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get current metrics summary"""
        return {
            "strategy": self.strategy_name,
            "scans": self.scans,
            "time_window_active": self.time_window_active,
            "time_window_inactive": self.time_window_inactive,
            "sweeps_detected": self.sweeps_detected,
            "flow_analyzed": self.flow_analyzed,
            "signals_generated": self.signals_generated,
            "entries_executed": self.entries_executed,
            "entries_failed": self.entries_failed,
            "uptime_hours": (datetime.now() - self.last_reset).total_seconds() / 3600
        }
    
    def log_summary(self):
        """Log metrics summary"""
        summary = self.get_summary()
        logger.info("=" * 60)
        logger.info(f"METRICS SUMMARY - {self.strategy_name}")
        logger.info("=" * 60)
        logger.info(f"Uptime: {summary['uptime_hours']:.2f} hours")
        logger.info(f"Total Scans: {summary['scans']}")
        logger.info(f"  - Time Window Active: {summary['time_window_active']}")
        logger.info(f"  - Time Window Inactive: {summary['time_window_inactive']}")
        logger.info(f"Sweeps Detected: {summary['sweeps_detected']}")
        logger.info(f"Flow Analyzed: {summary['flow_analyzed']}")
        logger.info(f"Signals Generated: {summary['signals_generated']}")
        logger.info(f"Entries Executed: {summary['entries_executed']}")
        logger.info(f"Entries Failed: {summary['entries_failed']}")
        logger.info("=" * 60)
        
        # Calculate conversion rates
        if summary['scans'] > 0:
            signal_rate = (summary['signals_generated'] / summary['scans']) * 100
            logger.info(f"Signal Rate: {signal_rate:.2f}%")
        
        if summary['signals_generated'] > 0:
            execution_rate = (summary['entries_executed'] / summary['signals_generated']) * 100
            logger.info(f"Execution Rate: {execution_rate:.2f}%")
    
    def reset(self):
        """Reset all counters"""
        self.scans = 0
        self.time_window_active = 0
        self.time_window_inactive = 0
        self.sweeps_detected = 0
        self.flow_analyzed = 0
        self.signals_generated = 0
        self.entries_executed = 0
        self.entries_failed = 0
        self.last_reset = datetime.now()
        logger.info(f"Metrics reset for {self.strategy_name}")
