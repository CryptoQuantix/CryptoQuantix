import sys
import os

# Ensure root directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from src.trading_bot import main
except ImportError as e:
    print(f"Error importing bot: {e}")
    print("Make sure you are running this script from the project root.")
    sys.exit(1)

if __name__ == "__main__":
    main()
