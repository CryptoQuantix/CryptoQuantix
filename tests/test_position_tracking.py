"""Unit tests for position tracking fixes (venue flat detection, close fills)."""
import time
import unittest
from unittest.mock import MagicMock, patch

from src.core.order_manager import OrderManager


class FakeDeribitClient:
    def __init__(self):
        self.positions = []
        self.trades = []
        self.order_states = {}

    def get_positions(self, currency, kind="option"):
        return [p for p in self.positions if p.get("currency", currency) == currency]

    def get_user_trades_by_instrument(self, instrument_name, count=20, sorting="desc"):
        trades = [t for t in self.trades if t["instrument_name"] == instrument_name]
        trades.sort(key=lambda t: t["timestamp"], reverse=(sorting == "desc"))
        return trades[:count]

    def get_order_state(self, order_id):
        return self.order_states.get(order_id)


class OrderManagerTrackingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeDeribitClient()
        self.manager = OrderManager(self.client)

    def test_is_instrument_flat_when_no_perp_position(self):
        flat = self.manager.is_instrument_flat("BTC-PERPETUAL")
        self.assertTrue(flat)

    def test_is_instrument_flat_when_perp_open(self):
        self.client.positions = [{
            "currency": "BTC",
            "instrument_name": "BTC-PERPETUAL",
            "size": 7390,
        }]
        flat = self.manager.is_instrument_flat("BTC-PERPETUAL")
        self.assertFalse(flat)

    def test_get_position_details_uses_future_kind_for_perpetual(self):
        self.client.positions = [{
            "currency": "BTC",
            "instrument_name": "BTC-PERPETUAL",
            "size": 100,
        }]
        with patch.object(self.client, "get_positions", wraps=self.client.get_positions) as mock_gp:
            pos = self.manager.get_position_details("BTC-PERPETUAL", "BTC")
            self.assertIsNotNone(pos)
            mock_gp.assert_called_with("BTC", kind="future")

    def test_get_closing_fill_price_finds_reduce_only_after_entry(self):
        entry_ts = int(time.time() * 1000) - 60_000
        self.client.trades = [
            {
                "instrument_name": "BTC-PERPETUAL",
                "timestamp": entry_ts + 30_000,
                "price": 65568.0,
                "direction": "buy",
                "reduce_only": True,
            },
            {
                "instrument_name": "BTC-PERPETUAL",
                "timestamp": entry_ts,
                "price": 64929.0,
                "direction": "sell",
                "reduce_only": False,
            },
        ]
        price = self.manager.get_closing_fill_price(
            "BTC-PERPETUAL", entry_ts, "sell"
        )
        self.assertEqual(price, 65568.0)

    def test_get_closing_fill_price_ignores_entry_trade(self):
        entry_ts = int(time.time() * 1000)
        self.client.trades = [
            {
                "instrument_name": "BTC-PERPETUAL",
                "timestamp": entry_ts,
                "price": 64929.0,
                "direction": "sell",
                "reduce_only": False,
            },
        ]
        price = self.manager.get_closing_fill_price(
            "BTC-PERPETUAL", entry_ts, "sell"
        )
        self.assertIsNone(price)


class AsyncBotCloseDetectionTests(unittest.TestCase):
    def test_check_closed_positions_waits_for_closing_fill(self):
        from src.async_trading_bot import AsyncTradingBot

        bot = object.__new__(AsyncTradingBot)
        bot.trade_logger = MagicMock()
        bot.order_manager = MagicMock()
        bot.client = MagicMock()
        bot._active_trades = {
            "tb_1": {
                "instrument": "BTC-PERPETUAL",
                "direction": "sell",
                "entry_price": 64929.0,
                "stop_loss": 65548.0,
                "take_profit": 63573.0,
                "qty_btc": 0.1138,
                "entry_ts_ms": 1,
                "_seen_open": True,
                "_missing_count": 1,
            }
        }

        bot.client.get_futures_positions.return_value = []
        bot.order_manager.is_instrument_flat.return_value = True
        bot.order_manager.get_closing_fill_price.return_value = None

        bot._check_closed_positions()

        bot.trade_logger.log_exit.assert_not_called()
        self.assertIn("tb_1", bot._active_trades)

    def test_check_closed_positions_logs_real_close(self):
        from src.async_trading_bot import AsyncTradingBot

        bot = object.__new__(AsyncTradingBot)
        bot.trade_logger = MagicMock()
        bot.order_manager = MagicMock()
        bot.client = MagicMock()
        bot._active_trades = {
            "tb_1": {
                "instrument": "BTC-PERPETUAL",
                "direction": "sell",
                "entry_price": 64929.0,
                "stop_loss": 65548.0,
                "take_profit": 63573.0,
                "qty_btc": 0.1138,
                "entry_ts_ms": 1,
                "_seen_open": True,
                "_missing_count": 1,
            }
        }

        bot.client.get_futures_positions.return_value = []
        bot.order_manager.is_instrument_flat.return_value = True
        bot.order_manager.get_closing_fill_price.return_value = 65568.0

        bot._check_closed_positions()

        bot.trade_logger.log_exit.assert_called_once()
        kwargs = bot.trade_logger.log_exit.call_args.kwargs
        self.assertAlmostEqual(kwargs["exit_price"], 65568.0)
        self.assertAlmostEqual(kwargs["pnl_usd"], -72.7, delta=1.0)
        self.assertEqual(kwargs["exit_reason"], "sl")
        self.assertNotIn("tb_1", bot._active_trades)

    def test_check_closed_positions_does_not_false_close_on_list_miss(self):
        from src.async_trading_bot import AsyncTradingBot

        bot = object.__new__(AsyncTradingBot)
        bot.trade_logger = MagicMock()
        bot.order_manager = MagicMock()
        bot.client = MagicMock()
        bot._active_trades = {
            "tb_1": {
                "instrument": "BTC-PERPETUAL",
                "direction": "sell",
                "entry_price": 64929.0,
                "stop_loss": 65548.0,
                "take_profit": 63573.0,
                "qty_btc": 0.1138,
                "entry_ts_ms": 1,
                "_seen_open": True,
                "_missing_count": 0,
            }
        }

        bot.client.get_futures_positions.return_value = []
        bot.order_manager.is_instrument_flat.return_value = False

        bot._check_closed_positions()

        bot.trade_logger.log_exit.assert_not_called()
        self.assertEqual(bot._active_trades["tb_1"]["_missing_count"], 0)


if __name__ == "__main__":
    unittest.main()
