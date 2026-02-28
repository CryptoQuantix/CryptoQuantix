import sys
import os
import logging
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.risk_manager import RiskManager
from src.core.deribit_client import DeribitClient

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("SizingDemo")

def test_sizing_scenario(scenario_name, equity_usd, risk_pct, leverage_max, entry_price, sl_price, instrument="BTC-PERPETUAL"):
    logger.info(f"\n--- {scenario_name} ---")
    logger.info(f"INPUTS: Equity=${equity_usd:,.2f}, Risk={risk_pct:.1%}, LevMax={leverage_max}x")
    logger.info(f"TRADE: {instrument} Entry=${entry_price}, SL=${sl_price}")
    
    # Mock Client and Risk Manager
    mock_client = MagicMock(spec=DeribitClient)
    mock_client.env = 'test' # Simulate Testnet to trigger the $50k cap logic check
    # Mock Account Summary to return specific Equity
    # Note: RiskManager calls get_account_summary("BTC") -> returns {'equity': BTC_AMT}
    # Then multiplies by Index Price.
    # To simplify, we'll mock RiskManager.get_total_equity directly.
    
    rm = RiskManager(mock_client, MagicMock(), initial_equity=equity_usd)
    # Use real get_total_equity but mock the underlying calls
    rm.get_current_equity = MagicMock(return_value=equity_usd/2) # BTC + ETH split
    
    # 1. Calculate using Centralized Logic (RiskManager)
    # This is exactly what the Strategies call now.
    sizing = rm.calculate_futures_quantity(
        entry_price=entry_price,
        sl_price=sl_price,
        risk_pct=risk_pct,
        leverage_max=leverage_max
    )
    
    if "error" in sizing:
        logger.error(f"RESULT: Error - {sizing['error']}")
        return

    # 2. Simulate Strategy Conversion (The "Standardized Pattern")
    qty_btc = sizing['quantity_btc']
    
    is_inverse = "PERPETUAL" in instrument and "USDC" not in instrument
    contract_val = 10.0 if "BTC" in instrument else 1.0
    
    if is_inverse:
        qty_usd_raw = qty_btc * entry_price
        final_contracts = int(qty_usd_raw / contract_val)
        display_size = f"{final_contracts} Contracts"
    else:
        final_contracts = round(qty_btc, 4)
        display_size = f"{final_contracts} BTC"

    # 3. Analyze Results (The "Philosophy Check")
    risk_dollars = sizing['max_loss_usd']
    actual_risk_pct = risk_dollars / equity_usd
    effective_leverage = sizing['effective_leverage']
    
    logger.info(f"OUTPUT (RiskManager):")
    logger.info(f"  > Position Size: {display_size} ({sizing['quantity_btc']:.4f} BTC)")
    logger.info(f"  > Value USD:     ${sizing['quantity_usd']:,.2f}")
    logger.info(f"  > Risk Amount:   ${risk_dollars:,.2f} ({actual_risk_pct:.2%})")
    logger.info(f"  > Leverage Used: {effective_leverage:.2f}x")
    
    # Validation
    if abs(actual_risk_pct - risk_pct) < 1e-4:
        logger.info("✅ PHILOSOPHY PASS: Risk % is EXACTLY preserved.")
    elif effective_leverage >= leverage_max:
        logger.info("⚠️ SAFETY CAP: Risk reduced to respect Max Leverage.")
    else:
        logger.error("❌ PHILOSOPHY FAIL: Risk mismatch!")

def main():
    logger.info("DEMONSTRATING SIZING PHILOSOPHY ALIGNMENT")
    logger.info("Philosophy: 'Read Equity -> Scale Position -> Respect Safety'")
    
    # Scenario A: Real User ($10k Account)
    # Normal trade, 1% risk
    test_sizing_scenario(
        "Scenario A: Normal User ($10k)", 
        equity_usd=10000.0, 
        risk_pct=0.01, 
        leverage_max=5,
        entry_price=87000, 
        sl_price=86000 # ~1.1% distance
    )
    
    # Scenario B: Simulated Testnet Whale ($8.7M Account)
    # Demonstrates why size was 883k checks
    test_sizing_scenario(
        "Scenario B: Testnet Whale ($8.7M)", 
        equity_usd=8700000.0, 
        risk_pct=0.01, 
        leverage_max=5,
        entry_price=87000, 
        sl_price=86000
    )
    
    # Scenario C: Tight Stop (Requires High Leverage -> Capped)
    # Demonstrates Safety First philosophy
    test_sizing_scenario(
        "Scenario C: High Leverage Attempt ($10k, Tight Stop)", 
        equity_usd=10000.0, 
        risk_pct=0.01, 
        leverage_max=5,
        entry_price=87000, 
        sl_price=86900 # Tiny stop (0.1%) -> Would require huge size to risk 1%
    )
    
    logger.info("\nCONCLUSION: The code adapts to ANY equity consistently.")

if __name__ == "__main__":
    main()
