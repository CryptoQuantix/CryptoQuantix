#!/bin/bash
# Script to restart the bot

set -e

echo "=========================================="
echo "  Restarting CryptoQuantix Trading Bot"
echo "=========================================="

docker compose restart

echo ""
echo "✓ Bot restarted successfully!"
echo ""
echo "View logs: ./docker-logs.sh"
