#!/bin/bash
# Quick test runner

echo "🧪 Running Trading Bot Tests"
echo "=============================="
echo ""

echo "1️⃣  Testing Indicators..."
python tests/test_indicators.py
echo ""

echo "2️⃣  Testing Strategy..."
python tests/test_strategy.py
echo ""

echo "3️⃣  Testing Risk Management..."
python tests/test_risk.py
echo ""

echo "=============================="
echo "✅ All tests completed!"
