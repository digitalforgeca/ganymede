#!/bin/bash
# Helper script for locally restarting the Ganymede gateway during development

echo "Restarting Ganymede Development Server..."

# Find all running ganymede gateway instances
PIDS=$(pgrep -f "ganymede.cli run")

if [ -n "$PIDS" ]; then
    echo "Terminating existing instances: $PIDS"
    # Send SIGTERM to allow graceful shutdown (flush DB/sockets)
    for PID in $PIDS; do
        kill $PID 2>/dev/null
    done
    
    sleep 2
    
    # Check if any are still stubbornly running
    PIDS_LEFT=$(pgrep -f "ganymede.cli run")
    if [ -n "$PIDS_LEFT" ]; then
        echo "Force killing remaining instances: $PIDS_LEFT"
        for PID in $PIDS_LEFT; do
            kill -9 $PID 2>/dev/null
        done
    fi
fi

# Start fresh
echo "Starting Ganymede..."
# Ensure we run from project root
cd "$(dirname "$0")/.."
.venv/bin/python3 -m ganymede.cli run
