#!/bin/bash
# Script to update .env file with missing Smart Money parameters

echo "Updating .env file..."

# Backup current .env
cp .env .env.backup 2>/dev/null

# Update LOG_LEVEL to DEBUG
sed -i 's/LOG_LEVEL=INFO/LOG_LEVEL=DEBUG/' .env

# Add missing parameters if not present
if ! grep -q "SM_ABSORPTION_MIN_VOL" .env; then
    cat >> .env << 'EOF'

# Smart Money - Order Flow Parameters
SM_ABSORPTION_MIN_VOL=10.0  # Minimum volume threshold
SM_ABSORPTION_DELTA_RATIO=0.15  # Delta ratio threshold (15% of total vol)
SM_ABSORPTION_PRICE_THRESHOLD=0.01  # Price change threshold (1%)
EOF
fi

if ! grep -q "RISK_PER_TRADE_PCT" .env; then
    cat >> .env << 'EOF'

# Smart Money - Risk Parameters
RISK_PER_TRADE_PCT=0.015  # 1.5% risk per trade
RISK_REWARD_RATIO=2.5  # Target 2.5:1 risk/reward
LEVERAGE_MAX=5  # Maximum leverage
EOF
fi

if ! grep -q "MONITORING_INTERVAL_MINUTES" .env; then
    cat >> .env << 'EOF'

# Monitoring
MONITORING_INTERVAL_MINUTES=5  # Scan interval in minutes
EOF
fi

echo ""
echo "✓ .env file updated successfully!"
echo "✓ Backup saved as .env.backup"
echo ""
echo "Changes made:"
echo "  - LOG_LEVEL set to DEBUG"
echo "  - Added Smart Money absorption parameters"
echo "  - Added risk management parameters"
echo "  - Added monitoring interval"
echo ""
