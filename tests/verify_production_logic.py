
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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("test_edit.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

def test_trailing_stop_logic():
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    logger.info(f"Starting Production Logic Verification on {env.upper()}")
    
    client = DeribitClient(api_key=api_key, api_secret=api_secret, env=env)
    if not client.authenticate():
        logger.error("Authentication Failed")
        return False
        
    instrument = "BTC-PERPETUAL"
    quantity = 100
    
    try:
        # 1. Clean Slate
        logger.info("[1/5] Cleaning up existing orders...")
        client.cancel_all()
        
        # 2. Open Position with SL
        current_price = client.get_index_price("BTC")
        sl_price = round(current_price * 0.95)
        
        logger.info(f"[2/5] Opening Position with SL @ ${sl_price}")
        
        # Use simple client calls to replicate Strategy behavior
        entry_order = client.buy(instrument, quantity, type="market", label="prod_test_entry")
        if not entry_order:
             logger.error("Entry failed")
             return False
             
        # Place Initial SL
        sl_order_resp = client.sell(instrument, quantity, type="stop_market", trigger="mark_price", 
                               trigger_price=sl_price, label="prod_test_sl", reduce_only=True)
        
        if not sl_order_resp:
            logger.error("Initial SL placement failed")
            return False
            
        sl_order_id = sl_order_resp["order_id"]
        logger.info(f"Initial SL placed: {sl_order_id}")
        
        time.sleep(2)
        
        # 3. TEST EDIT (The Critical Fix)
        new_sl_price = round(current_price * 0.96) # move it up slightly
        logger.info(f"[3/5] Testing EDIT method - Moving SL to ${new_sl_price}")
        
        edit_resp = client.edit(
            order_id=sl_order_id,
            amount=quantity,
            trigger_price=new_sl_price
        )
        
        if edit_resp:
            logger.info(f"✅ EDIT Successful! Response: {edit_resp['order_id']}")
            
            # Verify on exchange
            updated_order = client.get_order_state(sl_order_id)
            if updated_order and float(updated_order['trigger_price']) == float(new_sl_price):
                 logger.info(f"✅ Verified on Exchange: Trigger Price is now {updated_order['trigger_price']}")
            else:
                 logger.error(f"❌ Verification Failed. Price is {updated_order['trigger_price'] if updated_order else 'None'}")
                 return False
        else:
            logger.error("❌ EDIT Method Failed (returned None)")
            return False
            
        # 4. Cleanup
        logger.info("[4/5] Cleaning up...")
        client.close_position(instrument, type_="market")
        client.cancel_all()
        logger.info("✅ Cleanup Complete")
        
        return True

    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if test_trailing_stop_logic():
        print("\n>>> PRODUCTION LOGIC VERIFIED <<<")
    else:
        print("\n>>> VERIFICATION FAILED <<<")
