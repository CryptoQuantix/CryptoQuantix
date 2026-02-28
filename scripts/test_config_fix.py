import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import WMFormationConfig

def test_from_env():
    print("Testing WMFormationConfig.from_env()...")
    try:
        # Mock environment variables if needed, but defaults should work
        config = WMFormationConfig.from_env()
        print("Successfully created config from env:")
        print(f"  Name: {config.name}")
        print(f"  Enabled: {config.enabled}")
        print(f"  Deribit Symbol: {config.deribit_symbol}")
        print("Test PASSED")
    except AttributeError as e:
        print(f"Test FAILED: {e}")
    except Exception as e:
        print(f"Test FAILED with unexpected error: {e}")

if __name__ == "__main__":
    test_from_env()
