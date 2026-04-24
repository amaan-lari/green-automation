#!/usr/bin/env bash
# Cycles through counts [200, 250, 300], runs main.py --count N --resume,
# then waits 30 minutes after each run completes before starting the next.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/cycle.log"
COUNTS=(200 250 300)
WAIT_SECONDS=1800  # 30 minutes

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

cd "$SCRIPT_DIR"

# Track position across restarts via a state file
STATE_FILE="$SCRIPT_DIR/.cycle_state"
if [[ -f "$STATE_FILE" ]]; then
    INDEX=$(cat "$STATE_FILE")
else
    INDEX=0
fi

while true; do
    COUNT="${COUNTS[$INDEX]}"

    log "Starting run with --count $COUNT"
    START=$(date +%s)

    python main.py --count "$COUNT" --resume 2>&1 | tee -a "$LOG"
    EXIT_CODE=${PIPESTATUS[0]}

    END=$(date +%s)
    ELAPSED=$(( END - START ))
    log "Run with --count $COUNT finished (exit $EXIT_CODE) in ${ELAPSED}s"

    # Advance to next count, cycling back to 0 after 300
    INDEX=$(( (INDEX + 1) % ${#COUNTS[@]} ))
    echo "$INDEX" > "$STATE_FILE"

    log "Next count will be ${COUNTS[$INDEX]}. Waiting ${WAIT_SECONDS}s (30 min)..."
    sleep "$WAIT_SECONDS"
done
