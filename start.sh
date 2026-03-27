#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  My Assistant - Startup"
echo "============================================"
echo

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed or not in PATH."
    echo "        Install Python 3.11+ from https://www.python.org/downloads/"
    echo "        On macOS: brew install python@3.12"
    exit 1
fi

PYVER=$(python3 --version 2>&1)
echo "[OK] $PYVER found"

# Create venv if missing
if [ ! -f ".venv/bin/python" ]; then
    echo "[..] Creating virtual environment..."
    python3 -m venv .venv
    echo "[OK] Virtual environment created"
fi

# Install / update dependencies
echo "[..] Installing dependencies..."
.venv/bin/pip install -q -e . 2>&1 | grep -v "already satisfied" || true
echo "[OK] Dependencies ready"

# Check .env
if [ ! -f ".env" ]; then
    echo
    echo "[WARNING] No .env file found."
    if [ -f ".env.example" ]; then
        echo "         Copying .env.example to .env -- edit it with your tokens."
        cp .env.example .env
    else
        echo "         Create a .env file with your DISCORD_TOKEN and other settings."
    fi
    echo
fi

# Check Ollama
if ! command -v ollama &>/dev/null; then
    echo "[WARNING] Ollama not found in PATH. The assistant needs Ollama running locally."
    echo "         Install from https://ollama.com"
fi

# Parse argument (default: discord)
TRANSPORT="${1:-discord}"

echo
echo "[>>] Starting assistant (transport: $TRANSPORT)..."
echo "    Press Ctrl+C to stop."
echo

.venv/bin/python -m src.app --transport "$TRANSPORT"
