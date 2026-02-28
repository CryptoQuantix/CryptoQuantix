
from src.core.deribit_client import DeribitClient
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("DERIBIT_API_KEY")
api_secret = os.getenv("DERIBIT_API_SECRET")
env = os.getenv("DERIBIT_ENV", "test").split('#')[0].strip()

print(f"Connecting to {env} with {api_key[:4]}...")
client = DeribitClient(api_key, api_secret, env=env)
client.authenticate()

print("Checking Account Summary 'BTC'...")
try:
    res = client.get_account_summary("BTC")
    print(f"Result: {res}")
except Exception as e:
    print(f"Error: {e}")
