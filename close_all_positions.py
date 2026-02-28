
from src.core.deribit_client import DeribitClient
import os
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Cleaner")

def close_all():
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    if not api_key:
        logger.error("Could not load API credentials from .env")
        return

    logger.info(f"Connecting to Deribit {env.upper()}...")
    client = DeribitClient(api_key, api_secret, env=env)
    
    if not client.authenticate():
        logger.error("Authentication failed")
        return

    # Check and Close Positions
    currencies = ["BTC", "ETH", "USDC"]
    positions_closed = 0
    
    for currency in currencies:
        try:
            for kind in ["future", "option", "spot"]:
                positions = client.get_positions(currency, kind=kind)
                
                for pos in positions:
                    instrument = pos['instrument_name']
                    size = pos['size']
                    direction = pos['direction']
                    
                    logger.info(f"Found Position ({kind}): {instrument} | {direction} | Size: {size}")
                    
                    logger.info(f"Closing {instrument}...")
                    result = client.close_position(instrument)
                    
                    if result:
                        logger.info(f"SUCCESS: Closed {instrument}")
                        positions_closed += 1
                    elif result is None:
                        logger.error(f"FAILED to close {instrument}")
                    elif "error" in result:
                        logger.error(f"FAILED to close {instrument}: {result['error']}")
                    
        except Exception as e:
            logger.error(f"Error checking {currency} positions: {e}")

    # Cancel All Orders
    logger.info("Cancelling all open orders...")
    if client.cancel_all():
        logger.info("All open orders cancelled.")
    else:
        logger.error("Failed to cancel open orders.")

    if positions_closed == 0:
        logger.info("No open positions found to close.")
    else:
        logger.info(f"Operation Complete. Closed {positions_closed} positions.")

if __name__ == "__main__":
    close_all()
