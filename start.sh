#!/bin/bash
# Entrypoint script for Telegram IPTV Bot Ultra Pro
# Starts the keep-alive server and the bot with retry logic

set -euo pipefail

# Function to start the keep-alive server in background
start_keepalive() {
    echo "Starting keep-alive server on ${HOST}:${PORT}..."
    python -m keepalive.server &
    KEEPALIVE_PID=$!
    echo "Keep-alive server started with PID $KEEPALIVE_PID"
}

# Function to start the bot with retry logic
start_bot_with_retry() {
    local max_attempts=${MAX_RESTART_ATTEMPTS:-5}
    local delay=${RESTART_DELAY:-5}
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Starting bot (attempt $attempt/$max_attempts)..."
        python main.py
        local exit_code=$?

        if [ $exit_code -eq 0 ]; then
            echo "Bot exited normally."
            break
        else
            echo "Bot exited with code $exit_code. Retrying in $delay seconds..."
            sleep $delay
            attempt=$((attempt + 1))
        fi
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "Max restart attempts reached. Exiting."
        exit 1
    fi
}

# Trap to handle termination signals
trap 'echo "Received termination signal. Shutting down..."; kill $KEEPALIVE_PID 2>/dev/null; exit 0' SIGINT SIGTERM

# Start keep-alive server
start_keepalive

# Start bot with retry logic
start_bot_with_retry