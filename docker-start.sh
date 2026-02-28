#!/bin/bash
# Script to start the Coinmaker bot with Docker Compose

set -e

echo "=========================================="
echo "  Starting Coinmaker Trading Bot"
echo "=========================================="

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create .env from .env.example and configure your API keys"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running!"
    echo "Please start Docker Desktop and try again"
    exit 1
fi

# Create directories if they don't exist
mkdir -p logs data

# Pull latest changes and rebuild if needed
echo ""
echo "Building Docker image..."
docker compose build

# Start the bot
echo ""
echo "Starting bot container..."
docker compose up -d

# Show status
echo ""
docker compose ps

# Show logs
echo ""
echo "=========================================="
echo "Bot started successfully!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  View logs:     docker compose logs -f"
echo "  Stop bot:      docker compose stop"
echo "  Restart bot:   docker compose restart"
echo "  View status:   docker compose ps"
echo ""
echo "Following logs (Ctrl+C to exit, bot keeps running)..."
echo ""

docker compose logs -f
