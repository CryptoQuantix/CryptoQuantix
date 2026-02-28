#!/usr/bin/env python3
"""Script to check current trading opportunities without opening positions"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.deribit_client import DeribitClient
from src.strategies.iron_condor import IronCondorBuilder
from src.utils.volatility import VolatilityAnalyzer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_currency(client: DeribitClient, currency: str, builder: IronCondorBuilder,
                   vol_analyzer: VolatilityAnalyzer):
    """Check opportunities for a specific currency"""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"CHECKING {currency}")
    logger.info(f"{'=' * 60}")

    # Get spot price
    spot_price = client.get_index_price(currency)
    if not spot_price:
        logger.error(f"Could not get spot price for {currency}")
        return

    logger.info(f"Spot Price: ${spot_price:,.2f}")

    # Get instruments
    instruments = client.get_instruments(currency, kind="option")
    logger.info(f"Available instruments: {len(instruments)}")

    # Find expirations
    expirations = {}
    for inst in instruments:
        exp_timestamp = inst.get("expiration_timestamp")
        if exp_timestamp:
            exp_dt = datetime.fromtimestamp(exp_timestamp / 1000)
            days = (exp_dt - datetime.now()).days
            if 7 <= days <= 10:
                exp_str = exp_dt.strftime("%d%b%y").upper()
                if exp_str not in expirations:
                    expirations[exp_str] = days

    logger.info(f"\nSuitable expirations (7-10 DTE):")
    for exp, days in sorted(expirations.items(), key=lambda x: x[1]):
        logger.info(f"  {exp}: {days} days")

    if not expirations:
        logger.warning("No suitable expirations found")
        return

    # Use closest to 7 DTE
    best_exp = min(expirations.items(), key=lambda x: abs(x[1] - 7))
    expiration = best_exp[0]
    logger.info(f"\nSelected expiration: {expiration} ({best_exp[1]} DTE)")

    # Get options for this expiration
    options = []
    for inst in instruments:
        exp_timestamp = inst.get("expiration_timestamp")
        if exp_timestamp:
            exp_dt = datetime.fromtimestamp(exp_timestamp / 1000)
            exp_str = exp_dt.strftime("%d%b%y").upper()

            if exp_str == expiration:
                # Get mark price and greeks
                book = client.get_order_book(inst["instrument_name"])
                if book:
                    inst["mark_price"] = book.get("mark_price", 0)
                    inst["mark_iv"] = book.get("mark_iv", 0)
                    inst["greeks"] = book.get("greeks", {})
                    options.append(inst)

    logger.info(f"Options for {expiration}: {len(options)}")

    # Calculate ATM IV
    atm_iv = vol_analyzer.get_atm_iv(options, spot_price)
    if atm_iv:
        logger.info(f"\nATM Implied Volatility: {atm_iv:.2%}")

        # Update history
        vol_analyzer.update_iv_history(currency, atm_iv)
        iv_history = vol_analyzer.get_iv_history(currency)

        if len(iv_history) > 1:
            iv_rank = vol_analyzer.calculate_iv_rank(currency, atm_iv, iv_history)
            iv_percentile = vol_analyzer.calculate_iv_percentile(atm_iv, iv_history)
            logger.info(f"IV Rank: {iv_rank:.1f}%")
            logger.info(f"IV Percentile: {iv_percentile:.1f}%")

            should_enter, reason = vol_analyzer.should_enter_position(
                currency, atm_iv, min_iv_percentile=30
            )
            logger.info(f"Should Enter: {'✓ YES' if should_enter else '✗ NO'} - {reason}")
        else:
            logger.info("Not enough IV history for rank calculation")
    else:
        logger.warning("Could not calculate ATM IV")

    # Try to build a sample condor
    logger.info(f"\nAttempting to build sample Iron Condor...")
    condor = builder.build_condor(
        currency=currency,
        options_chain=options,
        spot_price=spot_price,
        expiration_date=expiration,
        risk_per_condor=100,  # $100 sample
        tp_ratio=0.55,
        sl_mult=1.2
    )

    if condor:
        logger.info(f"\n✓ Iron Condor Structure:")
        logger.info(f"  Put Spread: {condor.long_put.strike:.0f} / {condor.short_put.strike:.0f}")
        logger.info(f"  Call Spread: {condor.short_call.strike:.0f} / {condor.long_call.strike:.0f}")
        logger.info(f"  Credit: ${condor.credit_received:.2f}")
        logger.info(f"  Max Loss: ${condor.max_loss:.2f}")
        logger.info(f"  Max Profit: ${condor.max_profit:.2f}")
        logger.info(f"  Size: {condor.size:.3f} contracts")
        logger.info(f"  Take Profit Target: ${condor.take_profit_target:.2f}")
        logger.info(f"  Stop Loss Target: ${condor.stop_loss_target:.2f}")
    else:
        logger.warning("✗ Could not build Iron Condor")


def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("IRON CONDOR OPPORTUNITY CHECKER")
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

    # Create components
    builder = IronCondorBuilder(
        short_delta_target=0.12,
        wing_width_percent=0.05
    )
    vol_analyzer = VolatilityAnalyzer(lookback_days=30)

    # Check each currency
    for currency in ["BTC", "ETH"]:
        try:
            check_currency(client, currency, builder, vol_analyzer)
        except Exception as e:
            logger.error(f"Error checking {currency}: {e}", exc_info=True)

    logger.info("\n" + "=" * 60)
    logger.info("OPPORTUNITY CHECK COMPLETED")
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
