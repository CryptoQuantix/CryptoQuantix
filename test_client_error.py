
from src.core.deribit_client import DeribitClient
import logging

# Configure logging to stdout
logging.basicConfig(level=logging.INFO)

def test_error_propagation():
    print("Testing Error Propagation...")
    
    # Use dummy credentials to force error
    client = DeribitClient("dummy_key", "dummy_secret", env="test")
    
    # Try to buy (requires auth)
    # This should fail Auth internally, send request without token, and get Unauthorized error
    result = client.buy("BTC-PERPETUAL", 10, type="market")
    
    print(f"Result Type: {type(result)}")
    print(f"Result: {result}")
    
    if result and "error" in result:
        print("SUCCESS: Error was propagated!")
    elif result is None:
        print("FAILURE: Result is None (old behavior)")
    else:
        print(f"FAILURE: Unexpected result: {result}")

if __name__ == "__main__":
    test_error_propagation()
