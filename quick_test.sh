#!/bin/bash
# Quick test with shorter interval

echo "🚀 Starting bot with 10s interval for testing..."
echo ""

# Temporarily override interval
CHECK_INTERVAL_SECONDS=10 python3 -m src.app.main
