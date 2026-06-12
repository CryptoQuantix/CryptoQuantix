#!/bin/bash
# Script to view bot logs

echo "=========================================="
echo "  CryptoQuantix Bot Logs"
echo "=========================================="
echo "Press Ctrl+C to exit (bot keeps running)"
echo ""

docker compose logs -f cryptoquantix-bot
