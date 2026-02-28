
import sys
import os
import time
import logging
import json
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
# Force add current directory (project root)
sys.path.append(os.getcwd())
# Also try adding via relative just in case
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.deribit_client import DeribitClient
from src.core.order_manager import OrderManager
from src.strategies.smart_money import SmartMoneyStrategy
from src.core.state_manager import StateManager
from config import SmartMoneyConfig

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

def verify_isolation():
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test")
    
    logger.info(f"Starting Isolation Verification on {env.upper()}")
    
    client = DeribitClient(api_key=api_key, api_secret=api_secret, env=env)
    if not client.authenticate():
        logger.error("Authentication Failed")
        return False
        
    instrument = "BTC-PERPETUAL"
    
    try:
        # 1. Clean Slate
        logger.info("[1/4] Cleaning up...")
        client.cancel_all()
        client.close_position(instrument)
        time.sleep(1)
        
        # 2. Simulate "Conflict" Scenario
        # We will open a position of 300 contracts.
        # 100 for Smart Money, 200 for 'Others' (Brings/WM)
        logger.info("[2/4] Creating Shared Position (300 Contracts)...")
        client.buy(instrument, 300, type="market", label="shared_entry")
        
        time.sleep(2)
        
        # 3. Setup Smart Money State (Virtual 100 contracts)
        # We manually inject state to simulate an active SM trade
        sm_config = SmartMoneyConfig("Smart Money")
        state_manager = StateManager()
        
        # Mock active position for Smart Money
        current_price = client.get_index_price("BTC")
        sm_state = {
            'instrument': instrument,
            'direction': 'buy',
            'quantity': 100, # Only owns 100 of the 300
            'entry_price': current_price,
            'sl_price': current_price * 0.95,
            'tp_price': current_price * 1.01, # Target close
            'risk_distance': 100,
            'start_time': datetime.now().isoformat()
        }
        state_file = "smart_money_state.json"
        state_manager.save_state(state_file, sm_state)
        
        # Initialize Strategy
        dependencies = {
            'order_manager': OrderManager(client, {}),
            'pvsra': None # Not needed for manage_positions
        }
        sm_strategy = SmartMoneyStrategy(client, sm_config, dependencies)
        sm_strategy.active_position = sm_state # Load manual state
        
        # 4. Trigger "Close" (Simulate Take Profit)
        # We force the price check to PASS by modifying the TP in state to be BELOW current price (for buy)
        # Actually easier: just manually call the logic that executes the close? 
        # Or better, update state so TP is hit.
        
        logger.info("[3/4] Triggering Smart Money Close (Targeted Reduce Only)...")
        # Hack: Set TP price to 0 to guarantee hit for Long
        sm_strategy.active_position['tp_price'] = 0 
        
        result = sm_strategy.manage_positions()
        logger.info(f"Manage Result: {result}")
        
        time.sleep(2)
        
        # 5. Verify Result
        logger.info("[4/4] Verifying Isolation...")
        positions = client.get_positions("BTC", kind="future")
        my_pos = next((p for p in positions if p['instrument_name'] == instrument), None)
        
        if not my_pos:
            logger.error("❌ Position completely closed! Isolation FAILED. (Should have 200 left)")
            return False
            
        remaining_size = float(my_pos['size'])
        logger.info(f"Remaining Size: {remaining_size}")
        
        if remaining_size == 200.0:
            logger.info("✅ SUCCESS: Smart Money closed ONLY its 100 contracts. 200 Remain.")
            
            # Cleanup
            client.close_position(instrument)
            return True
        else:
            logger.error(f"❌ FAILED: remaining size is {remaining_size}, expected 200.")
            client.close_position(instrument)
            return False

    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if verify_isolation():
        print("\n>>> ISOLATION VERIFIED <<<")
    else:
        print("\n>>> ISOLATION FAILED <<<")
