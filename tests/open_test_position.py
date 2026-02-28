
import sys
import os
import time
import logging
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.deribit_client import DeribitClient
from src.core.order_manager import OrderManager

# Setup Logging
logger = logging.getLogger() 
logger.setLevel(logging.INFO)

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)

def open_test_position():
    # Load Environment Variables
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    logger.info(f"Starting Open Test Position on {env.upper()} Environment")
    
    if not api_key or not api_secret:
        logger.error("API credentials missing in .env")
        return False

    # Initialize Client and Manager
    client = DeribitClient(api_key=api_key, api_secret=api_secret, env=env)
    if not client.authenticate():
        logger.error("Authentication Failed")
        return False
        
    manager = OrderManager(client)
    
    # Test Parameters
    instrument = "BTC-PERPETUAL"
    quantity = 100  # Minimum size
    direction = "buy"
    
    try:
        # Get Current Price for SL/TP
        index_price = client.get_index_price("BTC")
        if not index_price:
            logger.error("Could not fetch index price")
            return False
            
        logger.info(f"Current BTC Index Price: ${index_price}")
        
        # SL = 5% below, TP = 5% above (Wide enough to stay open)
        sl_price = round(index_price * 0.95)
        tp_price = round(index_price * 1.05)
        
        logger.info(f"Opening Position with:")
        logger.info(f"  Entry: Market Buy {quantity}")
        logger.info(f"  SL:    ${sl_price} (-5%)")
        logger.info(f"  TP:    ${tp_price} (+5%)")
        
        # 1. Execute Generic Trade (Market Buy + SL + TP)
        logger.info(f"\n--- Executing Trade ---")
        success, msg = manager.execute_generic_trade(
            instrument_name=instrument,
            direction=direction,
            quantity=quantity,
            entry_type="market",
            stop_loss=sl_price,
            take_profit=tp_price
        )
        
        if not success:
            logger.error(f"Trade Execution Failed: {msg}")
            return False
            
        logger.info(f"Trade Executed: {msg}")
        
        # Allow API propagation time
        time.sleep(2)
        
        # 2. Verify and Report
        logger.info("\n--- Current Status ---")
        positions = client.get_positions("BTC", kind="future")
        my_position = next((p for p in positions if p["instrument_name"] == instrument), None)
        
        if my_position and my_position["size"] > 0:
            logger.info(f"✅ Position IS OPEN: {my_position['size']} contracts @ ${my_position['average_price']}")
        else:
            logger.error("❌ Position NOT FOUND")
            
        open_orders = client.get_open_orders(currency="BTC", kind="future")
        sl_order = next((o for o in open_orders if o["order_type"] == "stop_market" and o["label"] == "strategy_sl"), None)
        tp_order = next((o for o in open_orders if o["order_type"] == "limit" and o["label"] == "strategy_tp"), None)
        
        if sl_order:
             logger.info(f"✅ Stop Loss IS ACTIVE: ID {sl_order['order_id']} Trigger=${sl_order['trigger_price']}")
        else:
             logger.error("❌ Stop Loss Order NOT FOUND")
             
        if tp_order:
             logger.info(f"✅ Take Profit IS ACTIVE: ID {tp_order['order_id']} Price=${tp_order['price']}")
        else:
             logger.error("❌ Take Profit Order NOT FOUND")

        logger.info("\n>>> Position left OPEN for user verification. <<<")
        return True

    except Exception as e:
        logger.error(f"Exception: {e}")
        return False

if __name__ == "__main__":
    open_test_position()
