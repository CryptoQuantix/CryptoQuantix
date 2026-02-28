import sys
import os
import logging
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.strategies.smart_money import AdvancedFlowAnalyzer

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("=" * 60)
    logger.info("BINANCE & ORDER FLOW TEST")
    logger.info("=" * 60)
    
    load_dotenv()
    
    symbol = os.getenv("SM_BINANCE_SYMBOL", "BTC/USDT")
    logger.info(f"Testing connection for symbol: {symbol}")
    
    try:
        analyzer = AdvancedFlowAnalyzer(symbol=symbol)
        
        logger.info("Fetching recent trades and analyzing flow...")
        analysis = analyzer.analyze_market_structure(limit=100) # Small limit for test
        
        if analysis:
            logger.info("✓ Connection Successful!")
            logger.info(f"  Price: {analysis['price_end']}")
            logger.info(f"  Delta: {analysis['delta']:.4f}")
            logger.info(f"  Signal: {analysis['signal']}")
            return True
        else:
            logger.error("✗ Failed to fetch data")
            return False
            
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
