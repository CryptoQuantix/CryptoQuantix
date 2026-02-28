
from src.core.deribit_client import DeribitClient
# from config import IDConfig # Not needed
import logging
import datetime
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Inspector")

def inspect():
    # Load Config (Need keys)
    # Assuming keys are in env or config file. 
    # Since I don't have the .env loaded in env vars here usually, 
    # I might need to rely on the user having them set or the client loading them.
    # Looking at DeribitClient, it takes keys in __init__.
    # Looking at config.py (not shown but referenced), usually it loads from env.
    
    # Try to load credentials from .env manually to be safe
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("DERIBIT_API_KEY")
    api_secret = os.getenv("DERIBIT_API_SECRET")
    env = os.getenv("DERIBIT_ENV", "test").split('#')[0].strip() # Fix comment issue
    
    print(f"Loaded Keys: {api_key[:4]}... / {api_secret[:4]}...")
    print(f"Env: {repr(env)}")
    
    if not api_key:
        print("ERROR: Could not load API credentials from .env")
        return

    client = DeribitClient(api_key, api_secret, env=env)
    
    if not client.authenticate():
        print("ERROR: Authentication failed")
        return

    print(f"\n--- Checking Account Info ({env}) ---")
    account = None
    try:
        # Try getting account summary with BTC first
        account = client.get_account_summary("BTC")
    except:
        pass
        
    if not account:
        try:
             account = client.get_account_summary("ETH")
        except:
             pass

    if account:
        print(f"Account ID: {account.get('id')}")
        print(f"Username: {account.get('username')}")
        print(f"Type: {account.get('type')}")
        print(f"Email: {account.get('email')}")
        print(f"System Name: {account.get('system_name')}")
    else:
        print("Could not retrieve account info (Auth OK, but get_account_summary failed).")

    currencies = ["BTC", "ETH", "USDT", "USDC", "SOL", "MATIC", "XRP", "LTC", "EUR"]
    
    print(f"\n--- Checking Balances & Positions ---")
    for currency in currencies:
        try:
            # Check Position (Iterate Kinds)
            for kind in ["future", "option", "spot"]:
                try:
                    positions = client.get_positions(currency, kind=kind)
                    if positions:
                        for pos in positions:
                            print(f"\n[!!! POSITION FOUND ({kind}) !!!] {pos['instrument_name']}")
                            print(f"  Currency: {currency}")
                            print(f"  Size: {pos['size']}")
                            print(f"  Direction: {pos['direction']}")
                            print(f"  Entry Price: {pos['average_price']}")
                            print(f"  P&L: {pos['floating_profit_loss']}")
                except:
                    pass
            
            # Check Balance
            summary = client.get_account_summary(currency)
            if summary:
                equity = summary.get('equity', 0)
                balance = summary.get('balance', 0)
                if equity > 0 or balance > 0:
                    print(f"[{currency}] Equity: {equity} | Balance: {balance} | Open Positions: {len(positions) if positions else 0}")
                    
        except Exception as e:
            # print(f"Error checking {currency}: {e}")
            pass

    print("\n--- Checking Open Orders (All Currencies) ---")
    for currency in currencies:
        try:
            orders = client.get_open_orders(currency)
            for o in orders:
                 ts = o['creation_timestamp']
                 dt = datetime.datetime.fromtimestamp(ts/1000)
                 print(f"[OPEN ORDER] {o['instrument_name']} {o['direction']} {o['amount']} @ {o.get('price', 'MKT')} (Type: {o['order_type']}) Date: {dt}")
        except:
            pass

if __name__ == "__main__":
    inspect()
