#!/bin/bash
# Helper to run dry run scripts

MODE=${1:-"help"}
shift

case "$MODE" in
    data)
        echo "Running: Data layer dry run..."
        python scripts/dry_run_data.py "$@"
        ;;
    orderflow)
        echo "Running: Orderflow engine dry run..."
        python scripts/dry_run_orderflow.py "$@"
        ;;
    strategies)
        echo "Running: Strategy dry run..."
        python scripts/dry_run_strategies.py "$@"
        ;;
    full)
        echo "Running: Full system dry run..."
        python scripts/dry_run_full.py "$@"
        ;;
    *)
        echo "Usage: ./scripts/run_dry_run.sh [data|orderflow|strategies|full] [options]"
        echo ""
        echo "Examples:"
        echo "  ./scripts/run_dry_run.sh data --duration 30"
        echo "  ./scripts/run_dry_run.sh orderflow --duration 60"
        echo "  ./scripts/run_dry_run.sh strategies --backtest"
        echo "  ./scripts/run_dry_run.sh full --duration 120"
        ;;
esac
