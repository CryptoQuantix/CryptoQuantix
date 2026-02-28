#!/usr/bin/env python3
"""Script to view current open positions on Deribit"""

import os
import sys
from dotenv import load_dotenv
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.deribit_client import DeribitClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def view_positions(client: DeribitClient, currency: str):
    """View positions for a currency"""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"{currency} POSITIONS")
    logger.info(f"{'=' * 60}")

    # Get account summary
    account = client.get_account_summary(currency)
    if account:
        spot_price = client.get_index_price(currency)
        equity_usd = account.get("equity", 0) * spot_price if spot_price else 0

        logger.info(f"Balance: {account.get('balance', 0):.8f} {currency}")
        logger.info(f"Equity: {account.get('equity', 0):.8f} {currency} (${equity_usd:,.2f})")
        logger.info(f"Available Funds: {account.get('available_funds', 0):.8f} {currency}")
        logger.info(f"Margin Balance: {account.get('margin_balance', 0):.8f} {currency}")

    # Get positions
    positions = client.get_positions(currency, kind="option")

    if not positions:
        logger.info("\nNo open positions")
        return

    logger.info(f"\nOpen Positions: {len(positions)}")
    logger.info("")

    total_pnl = 0

    for i, pos in enumerate(positions, 1):
        logger.info(f"{i}. {pos.get('instrument_name')}")
        logger.info(f"   Direction: {pos.get('direction')}")
        logger.info(f"   Size: {pos.get('size', 0):.4f}")
        logger.info(f"   Average Price: {pos.get('average_price', 0):.6f}")
        logger.info(f"   Mark Price: {pos.get('mark_price', 0):.6f}")
        logger.info(f"   P&L: ${pos.get('total_profit_loss', 0):,.2f}")

        greeks = pos.get("greeks", {})
        if greeks:
            logger.info(f"   Delta: {greeks.get('delta', 0):.4f}")
            logger.info(f"   Gamma: {greeks.get('gamma', 0):.6f}")
            logger.info(f"   Theta: {greeks.get('theta', 0):.4f}")
            logger.info(f"   Vega: {greeks.get('vega', 0):.4f}")

        total_pnl += pos.get('total_profit_loss', 0)
        logger.info("")

    logger.info(f"Total P&L: ${total_pnl:,.2f}")


def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("DERIBIT POSITIONS VIEWER")
    logger.info("=" * 60)

    # Load environment
    load_dotenv()

    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")

    # Create client
    client = DeribitClient(api_key, api_secret, env)

    # Authenticate
    if not client.authenticate():
        logger.error("Authentication failed")
        return False

    logger.info(f"Environment: {env}\n")

    # View positions for each currency
    for currency in ["BTC", "ETH"]:
        try:
            view_positions(client, currency)
        except Exception as e:
            logger.error(f"Error viewing {currency} positions: {e}")

    logger.info("\n" + "=" * 60)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
