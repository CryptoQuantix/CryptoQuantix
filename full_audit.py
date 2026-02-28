
from src.core.deribit_client import DeribitClient
import os
import json
from dotenv import load_dotenv

# Suppress client logs for clean output
import logging
logging.basicConfig(level=logging.CRITICAL)

load_dotenv()

api_key = os.getenv("DERIBIT_API_KEY")
api_secret = os.getenv("DERIBIT_API_SECRET")
env = os.getenv("DERIBIT_ENV", "test").split('#')[0].strip()

print(f"Connecting to {env.upper()} [Key: {api_key[:4]}...]")
client = DeribitClient(api_key, api_secret, env=env)
if not client.authenticate():
    print("Authentication FAILED!")
    exit(1)

print("Authentication SUCCESS.")

currencies = ["BTC", "ETH", "USDT", "USDC"]
kinds = ["future", "option", "spot"]

for curr in currencies:
    # Check Balance
    try:
        acc = client.get_account_summary(curr)
        if acc:
            bal = acc.get('balance', 0)
            equity = acc.get('equity', 0)
            if bal > 0 or equity > 0:
                print(f"\n[{curr}] Balance: {bal} | Equity: {equity}")
                print(f"       Account ID: {acc.get('id')} | Email: {acc.get('email')}")
            else:
                pass # print(f"[{curr}] Empty")
        else:
            pass # print(f"[{curr}] No Account Summary")
    except Exception as e:
        print(f"[{curr}] Account Check Error: {e}")

    # Check Positions (All Kinds)
    for kind in kinds:
        try:
            positions = client.get_positions(curr, kind=kind)
            if positions:
                for p in positions:
                    print(f"\n>>> FOUND POSITION ({kind}) <<<")
                    print(f"    Instrument: {p['instrument_name']}")
                    print(f"    Size: {p['size']}")
                    print(f"    Direction: {p['direction']}")
                    print(f"    Entry: {p['average_price']}")
                    print(f"    Current Price: {p['mark_price']}")
                    print(f"    P&L: {p['floating_profit_loss']}")
        except Exception as e:
            # print(f"[{curr}/{kind}] Pos Check Error: {e}")
            pass

print("\n--- TARGETED CHECK: BTC-PERPETUAL ---")
try:
    # Direct check for the specific instrument user mentioned
    spec_pos = client._request("GET", "/private/get_position", {"instrument_name": "BTC-PERPETUAL"}, private=True)
    if spec_pos and "result" in spec_pos:
        p = spec_pos["result"]
        print(f"Direct Query Found: {p['instrument_name']} | Size: {p['size']} | Dir: {p['direction']} | P&L: {p['floating_profit_loss']}")
    else:
        print("Direct Query: NO POSITION returned for BTC-PERPETUAL")
except Exception as e:
    print(f"Direct Query Error: {e}")

print("\n(Audit Complete)")
