
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
# Get Root Logger to capture logs from all modules
logger = logging.getLogger() 
logger.setLevel(logging.INFO)

# Clear existing handlers
if logger.hasHandlers():
    logger.handlers.clear()
    
# File Handler
fh = logging.FileHandler('verification.log', mode='w', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)

def verify_live_execution():
    # Load Environment Variables
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    logger.info(f"Starting Live Verification on {env.upper()} Environment")
    
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
    quantity = 100  # Minimum size (USD) for BTC-PERPETUAL on Deribit
    direction = "buy"
    
    try:
        # Get Current Price for SL/TP
        index_price = client.get_index_price("BTC")
        if not index_price:
            logger.error("Could not fetch index price")
            return False
            
        logger.info(f"Current BTC Index Price: ${index_price}")
        
        # SL = 1% below, TP = 1% above
        sl_price = round(index_price * 0.99)
        tp_price = round(index_price * 1.01)
        
        # 1. Execute Generic Trade (Market Buy + SL + TP)
        logger.info(f"\n--- STEP 1: Executing Trade (Buy {quantity} {instrument}) ---")
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
        
        # 2. Verify Position Open
        logger.info("\n--- STEP 2: Verifying Open Position ---")
        positions = client.get_positions("BTC", kind="future")
        logger.info(f"RAW POSITIONS: {positions}")
        
        my_position = next((p for p in positions if p["instrument_name"] == instrument), None)
        
        if my_position and my_position["size"] > 0:
            logger.info(f"✅ Position CONFIRMED: {my_position['size']} contracts @ ${my_position['average_price']}")
        else:
            logger.error("❌ Position NOT FOUND or Size is 0")
            return False
            
        # 3. Verify Stop Loss and Take Profit Orders
        logger.info("\n--- STEP 3: Verifying SL/TP Orders ---")
        open_orders = client.get_open_orders(currency="BTC", kind="future")
        
        sl_order = next((o for o in open_orders if o["order_type"] == "stop_market" and o["label"] == "strategy_sl"), None)
        tp_order = next((o for o in open_orders if o["order_type"] == "limit" and o["label"] == "strategy_tp"), None)
        
        if sl_order:
             logger.info(f"✅ Stop Loss Found: ID {sl_order['order_id']} Trigger=${sl_order['trigger_price']}")
        else:
             logger.error("❌ Stop Loss Order NOT FOUND")
             
        if tp_order:
             logger.info(f"✅ Take Profit Found: ID {tp_order['order_id']} Price=${tp_order['price']}")
        else:
             logger.error("❌ Take Profit Order NOT FOUND")
             
        if not sl_order or not tp_order:
            return False
            
        # 4. Cleanup (Close Position Safely - ONLY verify amount)
        logger.info("\n--- STEP 4: Cleaning Up (Closing Test Position) ---")
        # Do NOT use client.close_position() as it closes the user's entire position!
        # Instead, sell back the quantity we bought.
        manager.execute_generic_trade(instrument, "sell", quantity, entry_type="market")
        client.cancel_all()
        
        # Final Verification of Cleanup
        time.sleep(1)
        positions = client.get_positions("BTC", kind="future")
        open_orders = client.get_open_orders("BTC", kind="future")
        
        # Check if size decreased (or we are just verifying orders are gone)
        orders_cleared = len(open_orders) == 0
        
        if orders_cleared:
            logger.info("✅ Cleanup Successful")
            return True
        else:
            logger.warning("⚠️ Cleanup incomplete (check manually)")
            return True # The test passed, just cleanup was messy

    except Exception as e:
        logger.error(f"Exception during verification: {e}")
        return False

if __name__ == "__main__":
    if verify_live_execution():
        print("\n>>> LIVE VERIFICATION PASSED <<<")
        sys.exit(0)
    else:
        print("\n>>> LIVE VERIFICATION FAILED <<<")
        sys.exit(1)
