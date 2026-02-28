"""
Test script for Smart Money strategy components
Run this to manually test the strategy without running the full bot
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategies.smart_money import AdvancedFlowAnalyzer
from src.core.deribit_client import DeribitClient

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_flow_analyzer():
    """Test the Binance order flow analyzer"""
    logger.info("=" * 60)
    logger.info("TESTING ORDER FLOW ANALYZER")
    logger.info("=" * 60)
    
    try:
        analyzer = AdvancedFlowAnalyzer("BTC/USDT")
        result = analyzer.analyze_market_structure(
            limit=1000,
            min_vol_threshold=10.0,
            delta_ratio_threshold=0.15,
            price_change_threshold=0.01
        )
        
        if result:
            logger.info("✓ Flow Analyzer Working")
            logger.info(f"  Price Start: ${result['price_start']:,.2f}")
            logger.info(f"  Price End: ${result['price_end']:,.2f}")
            logger.info(f"  Price Change: {result['price_change_pct']:.4f}%")
            logger.info(f"  Delta: {result['delta']:.2f}")
            logger.info(f"  Total Volume: {result['total_volume']:.2f}")
            logger.info(f"  Signal: {result['signal']}")
            if result['reason']:
                logger.info(f"  Reason: {result['reason']}")
        else:
            logger.error("✗ Flow Analyzer returned None")
            
    except Exception as e:
        logger.error(f"✗ Flow Analyzer Error: {e}", exc_info=True)

def test_deribit_ohlcv():
    """Test Deribit OHLCV data fetching"""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING DERIBIT OHLCV")
    logger.info("=" * 60)
    
    load_dotenv()
    
    try:
        client = DeribitClient(
            os.getenv("DERIBIT_API_KEY"),
            os.getenv("DERIBIT_API_SECRET"),
            os.getenv("DERIBIT_ENV", "test")
        )
        
        if client.authenticate():
            logger.info("✓ Deribit Authentication Successful")
            
            ohlcv = client.get_ohlcv("BTC-PERPETUAL", "15m", 50)
            
            if ohlcv:
                logger.info(f"✓ Fetched {len(ohlcv)} candles")
                latest = ohlcv[-1]
                logger.info(f"  Latest Candle:")
                logger.info(f"    Time: {latest[0]}")
                logger.info(f"    Open: ${latest[1]:,.2f}")
                logger.info(f"    High: ${latest[2]:,.2f}")
                logger.info(f"    Low: ${latest[3]:,.2f}")
                logger.info(f"    Close: ${latest[4]:,.2f}")
                logger.info(f"    Volume: {latest[5]:.2f}")
            else:
                logger.error("✗ No OHLCV data returned")
        else:
            logger.error("✗ Deribit Authentication Failed")
            
    except Exception as e:
        logger.error(f"✗ Deribit Error: {e}", exc_info=True)

def test_time_window():
    """Test time window logic"""
    from datetime import datetime
    
    logger.info("\n" + "=" * 60)
    logger.info("TESTING TIME WINDOW")
    logger.info("=" * 60)
    
    current_hour = datetime.now().hour
    window_start = int(os.getenv("SM_TIME_WINDOW_START", 14))
    window_end = int(os.getenv("SM_TIME_WINDOW_END", 17))
    
    is_active = window_start <= current_hour < window_end
    
    logger.info(f"Current Hour: {current_hour}")
    logger.info(f"Window: {window_start}:00 - {window_end}:00")
    logger.info(f"Status: {'✓ ACTIVE' if is_active else '✗ INACTIVE'}")

if __name__ == "__main__":
    logger.info("SMART MONEY STRATEGY - COMPONENT TEST")
    logger.info("=" * 60)
    
    # Run all tests
    test_time_window()
    test_flow_analyzer()
    test_deribit_ohlcv()
    
    logger.info("\n" + "=" * 60)
    logger.info("TEST COMPLETE")
    logger.info("=" * 60)
