#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment if it exists
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Set PYTHONPATH to project root so that:
# - "from opencrane.mcp..." imports work correctly
# - "from mcp import Tool" resolves to the pip mcp package, not opencrane/mcp/
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Check if --check-coverage flag is present
CHECK_COVERAGE=false
COVERAGE_THRESHOLD=100
HAS_MARKER=false
ARGS=()

for arg in "$@"; do
    if [ "$arg" = "--check-coverage" ]; then
        CHECK_COVERAGE=true
    elif [ "$arg" = "-m" ]; then
        HAS_MARKER=true
        ARGS+=("$arg")
    else
        ARGS+=("$arg")
    fi
done

# If no marker specified, run ALL tests (override pytest.ini default which skips integration)
if [ "$HAS_MARKER" = false ]; then
    ARGS+=("-m" "")
fi

# If checking coverage, ensure we have coverage args
if [ "$CHECK_COVERAGE" = true ]; then
    HAS_COV_ARG=false
    HAS_COV_REPORT=false
    for arg in "${ARGS[@]}"; do
        if [[ "$arg" == --cov=* ]]; then
            HAS_COV_ARG=true
        fi
        if [[ "$arg" == --cov-report=* ]]; then
            HAS_COV_REPORT=true
        fi
    done
    
    # Add default coverage target if not present
    if [ "$HAS_COV_ARG" = false ]; then
        ARGS+=(--cov=opencrane)
    fi
    
    # Add default report format if not present
    if [ "$HAS_COV_REPORT" = false ]; then
        ARGS+=(--cov-report=term)
    fi
fi

# Run pytest
if [ "$CHECK_COVERAGE" = true ]; then
    echo "Running tests with coverage check..."
    echo "This may take 20-30 seconds for full test suite. Please wait..."
    echo ""

    # Run pytest and capture output
    OUTPUT=$(pytest "${ARGS[@]}" 2>&1)
    EXIT_CODE=$?

    # Display the output
    echo "$OUTPUT"
    
    # Extract coverage percentage from output (handles both term and term-missing formats)
    # Look for TOTAL line and get the coverage percentage (4th or last column with %)
    COVERAGE=$(echo "$OUTPUT" | grep "TOTAL" | grep -oE '[0-9]+%' | tail -1 | tr -d '%')
    
    if [ -n "$COVERAGE" ]; then
        echo ""
        echo "=================================================="
        if [ "$COVERAGE" -ge "$COVERAGE_THRESHOLD" ]; then
            echo "✅ Coverage $COVERAGE% meets $COVERAGE_THRESHOLD% threshold"
            exit $EXIT_CODE
        else
            echo "❌ Coverage $COVERAGE% is below $COVERAGE_THRESHOLD% threshold"
            exit 1
        fi
    else
        echo "⚠️  Could not determine coverage percentage"
        exit $EXIT_CODE
    fi
else
    # Run pytest normally
    exec pytest "${ARGS[@]}"
fi