#!/bin/bash

# RALPH - Autonomous Agent Loop for ROMULUS Build
# Usage: ./ralph.sh <max_iterations>

if [ -z "$1" ]; then
  echo "Usage: $0 <max_iterations>"
  echo "Example: $0 25"
  exit 1
fi

MAX_ITERATIONS=$1

echo "========================================="
echo "RALPH - ROMULUS Build Agent"
echo "========================================="
echo "Max iterations: $MAX_ITERATIONS"
echo "Started: $(date)"
echo ""

for ((i=1; i<=MAX_ITERATIONS; i++)); do
  echo "========================================="
  echo "Iteration $i / $MAX_ITERATIONS"
  echo "========================================="
  echo ""
  
  # Run Claude Code with PROMPT.md content
  # Each iteration gets a fresh context window
  result=$(claude -p "$(cat PROMPT.md)" --output-format text 2>&1) || true

  echo "$result"
  echo ""
  
  # Check for completion promise
  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "========================================="
    echo "✅ BUILD COMPLETE!"
    echo "========================================="
    echo "All tasks completed after $i iterations."
    echo "Finished: $(date)"
    echo ""
    echo "Next steps:"
    echo "  1. Review outputs: cat activity.md"
    echo "  2. Run tests: pytest tests/ -v"
    echo "  3. Run backtest: python -m romulus.cli.main run --config configs/etf_equal_weight.yaml"
    echo ""
    exit 0
  fi
  
  # Check if iteration made progress
  if [[ "$result" == *"error"* ]] || [[ "$result" == *"Error"* ]] || [[ "$result" == *"ERROR"* ]]; then
    echo "⚠️  Warning: Iteration $i encountered errors"
    echo "Check activity.md for details"
  fi
  
  echo ""
  echo "--- End of iteration $i ---"
  echo ""
  
  # Brief pause between iterations
  sleep 2
done

echo "========================================="
echo "⚠️  REACHED MAX ITERATIONS"
echo "========================================="
echo "Completed $MAX_ITERATIONS iterations"
echo "Finished: $(date)"
echo ""
echo "Build may not be complete. Check progress:"
echo "  - Review: cat activity.md"
echo "  - Check remaining tasks: grep '\"passes\": false' plan.md"
echo ""
echo "To continue, run: ./ralph.sh 10"
echo ""

exit 1
