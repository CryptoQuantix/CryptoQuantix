#!/bin/bash
# Script to stop the Coinmaker bot

set -e

echo "=========================================="
echo "  Stopping Coinmaker Trading Bot"
echo "=========================================="

docker compose stop

echo ""
echo "✓ Bot stopped successfully!"
echo ""
echo "To start again: ./docker-start.sh"
echo "To remove container: docker compose down"
