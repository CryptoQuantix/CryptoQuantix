#!/usr/bin/env python3
"""Test script to verify Deribit API connection and authentication"""

import os
import sys
from dotenv import load_dotenv
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.deribit_client import DeribitClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Test Deribit connection"""
    logger.info("=" * 60)
    logger.info("DERIBIT API CONNECTION TEST")
    logger.info("=" * 60)

    # Load environment
    load_dotenv()

    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")

    if not api_key or not api_secret:
        logger.error("Missing API credentials in .env file")
        return False

    logger.info(f"Environment: {env}")
    logger.info(f"API Key: {api_key[:8]}...")

    # Create client
    client = DeribitClient(api_key, api_secret, env)

    # Test authentication
    logger.info("\nTesting authentication...")
    if client.authenticate():
        logger.info("✓ Authentication successful")
    else:
        logger.error("✗ Authentication failed")
        return False

    # Test public endpoints
    logger.info("\nTesting public endpoints...")

    # Get BTC price
    btc_price = client.get_index_price("BTC")
    if btc_price:
        logger.info(f"✓ BTC Index Price: ${btc_price:,.2f}")
    else:
        logger.warning("✗ Could not fetch BTC price")

    # Get ETH price
    eth_price = client.get_index_price("ETH")
    if eth_price:
        logger.info(f"✓ ETH Index Price: ${eth_price:,.2f}")
    else:
        logger.warning("✗ Could not fetch ETH price")

    # Get instruments
    logger.info("\nTesting instruments retrieval...")
    btc_instruments = client.get_instruments("BTC", kind="option")
    logger.info(f"✓ Found {len(btc_instruments)} BTC options")

    # Test private endpoints
    logger.info("\nTesting private endpoints...")

    # Get account summary
    btc_account = client.get_account_summary("BTC")
    if btc_account:
        logger.info(f"✓ BTC Account Balance: {btc_account.get('balance', 0):.8f} BTC")
        logger.info(f"  Equity: {btc_account.get('equity', 0):.8f} BTC")
    else:
        logger.warning("✗ Could not fetch BTC account")

    eth_account = client.get_account_summary("ETH")
    if eth_account:
        logger.info(f"✓ ETH Account Balance: {eth_account.get('balance', 0):.8f} ETH")
        logger.info(f"  Equity: {eth_account.get('equity', 0):.8f} ETH")
    else:
        logger.warning("✗ Could not fetch ETH account")

    # Get positions
    btc_positions = client.get_positions("BTC")
    logger.info(f"✓ Open BTC positions: {len(btc_positions)}")

    eth_positions = client.get_positions("ETH")
    logger.info(f"✓ Open ETH positions: {len(eth_positions)}")

    logger.info("\n" + "=" * 60)
    logger.info("CONNECTION TEST COMPLETED SUCCESSFULLY")
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
