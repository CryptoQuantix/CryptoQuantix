#!/bin/bash
# Script to open a shell inside the bot container

echo "=========================================="
echo "  Opening shell in bot container"
echo "=========================================="
echo ""

if ! docker compose ps | grep -q "coinmaker-bot.*Up"; then
    echo "❌ Bot container is not running!"
    echo "Start it first with: ./docker-start.sh"
    exit 1
fi

docker compose exec coinmaker-bot /bin/bash
