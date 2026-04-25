#!/bin/bash

set -euo pipefail

SESSION_NAME="propbackend"
PROJECT_DIR="/home/martin/propbackend"
START_SCRIPT="$PROJECT_DIR/start"

if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is not installed" >&2
    exit 1
fi

# Replace stale session so restart behavior is deterministic.
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
fi

exec tmux new-session -d -s "$SESSION_NAME" "cd '$PROJECT_DIR' && bash '$START_SCRIPT'"