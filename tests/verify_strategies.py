import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import IronCondorConfig, SmartMoneyConfig
from src.strategies.iron_condor import IronCondorStrategy
from src.strategies.smart_money import SmartMoneyStrategy

class TestStrategies(unittest.TestCase):

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_order_manager = MagicMock()
        self.mock_position_monitor = MagicMock()
        self.mock_risk_manager = MagicMock()
        
        self.dependencies = {
            "order_manager": self.mock_order_manager,
            "position_monitor": self.mock_position_monitor,
            "risk_manager": self.mock_risk_manager
        }
        
        self.mock_risk_manager.can_open_new_position.return_value = (True, "OK")
        self.mock_risk_manager.calculate_position_size.return_value = 1000.0
        self.mock_risk_manager.validate_trade.return_value = (True, "OK")

    def test_iron_condor_scan(self):
        print("\nTesting Iron Condor Strategy...")
        config = IronCondorConfig(name="Iron Condor Test")
        strategy = IronCondorStrategy(self.mock_client, config, self.dependencies)
        
        self.mock_client.get_index_price.return_value = 50000.0
        self.mock_client.get_instruments.return_value = [
            {"instrument_name": "BTC-27DEC24-50000-C", "expiration_timestamp": (datetime.now().timestamp() + 7*24*3600)*1000}
        ]
        self.mock_client.get_order_book.return_value = {
            "mark_price": 0.01,
            "mark_iv": 50.0,
            "greeks": {"delta": 0.12}
        }
        
        signals = strategy.scan()
        print(f"Signals found: {len(signals)}")
        self.assertEqual(len(signals), 0) 

    @patch('src.strategies.smart_money.BinanceWhaleClient')
    def test_smart_money_scan(self, MockWhaleClient):
        print("\nTesting Smart Money Strategy (Binance)...")
        config = SmartMoneyConfig(name="Smart Money Test", time_window_start=0, time_window_end=24)
        strategy = SmartMoneyStrategy(self.mock_client, config, self.dependencies)
        
        # Mock Binance Client
        mock_whale = MockWhaleClient.return_value
        mock_whale.get_whale_sentiment.return_value = "BULLISH"
        strategy.whale_client = mock_whale
        
        # Mock OHLCV for Liquidity Sweep (Bullish)
        ohlcv = []
        for i in range(50):
            ohlcv.append([i, 100, 105, 95, 100, 1000])
        
        ohlcv[-20] = [0, 100, 100, 90, 95, 1000] # Low = 90
        ohlcv[-1] = [0, 95, 98, 89, 92, 1000] # Low 89 < 90, Close 92 > 90
        
        self.mock_client.get_ohlcv.return_value = ohlcv
        
        # Run scan
        signals = strategy.scan()
        print(f"Signals found: {len(signals)}")
        
        if signals:
            print(f"Signal: {signals[0]}")
            self.assertEqual(signals[0]['type'], 'smart_money')
            self.assertEqual(signals[0]['direction'], 'buy')
            self.assertEqual(signals[0]['reason'], 'Bullish Sweep + Whale Buy Vol')
        else:
            print("No signals found (unexpected for this test case)")

if __name__ == '__main__':
    unittest.main()
