
import sys
import os
import logging
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.deribit_client import DeribitClient

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def force_close_all():
    # Load Environment Variables
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    logger.info(f"Starting Force Close on {env.upper()} Environment")
    
    client = DeribitClient(api_key=api_key, api_secret=api_secret, env=env)
    if not client.authenticate():
        logger.error("Authentication Failed")
        return False
        
    instrument = "BTC-PERPETUAL"
    
    try:
        # Check Position
        positions = client.get_positions("BTC", kind="future")
        my_position = next((p for p in positions if p["instrument_name"] == instrument), None)
        
        if my_position and my_position["size"] != 0:
            logger.info(f"Found Open Position: {my_position['size']} contracts")
            
            # Close Position
            logger.info("Executed Close Position...")
            result = client.close_position(instrument)
            
            if result:
                 logger.info(f"Close Result: {result}")
            else:
                 logger.error("Close Command Returned None")
            
            # Verify Closure
            positions = client.get_positions("BTC", kind="future")
            my_position = next((p for p in positions if p["instrument_name"] == instrument), None)
            
            if not my_position or my_position["size"] == 0:
                logger.info("✅ Position Successfully Closed")
            else:
                logger.error(f"❌ Position Failed to Close. Current Size: {my_position['size']}")
                return False
        else:
            logger.info("No Open Position Found. Account is already flat.")

        # Cancel All Orders
        logger.info("Canceling All Orders...")
        client.cancel_all()
        open_orders = client.get_open_orders("BTC", kind="future")
        
        if len(open_orders) == 0:
             logger.info("✅ All Orders Cancelled")
        else:
             logger.error(f"❌ {len(open_orders)} Orders still open!")
             return False
             
        return True

    except Exception as e:
        logger.error(f"Exception: {e}")
        return False

if __name__ == "__main__":
    if force_close_all():
        print("\n>>> FORCE CLOSE SUCCESSFUL <<<")
        sys.exit(0)
    else:
        print("\n>>> FORCE CLOSE FAILED <<<")
        sys.exit(1)
