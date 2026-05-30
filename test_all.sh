#!/usr/bin/env bash
# Run all test suites sequentially, report summary at the end.
#
# Usage: bash test_all.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASSED=()
FAILED=()

run_suite() {
    local name="$1"; shift
    echo ""
    echo "========================================="
    echo "  $name"
    echo "========================================="
    if "$@"; then
        PASSED+=("$name")
    else
        FAILED+=("$name")
    fi
}

run_suite "Unit tests (test_plan.py)"          python3 -m unittest "$SCRIPT_DIR/test_plan.py"
run_suite "Merge engine tests (test_merge.py)" python3 -m unittest "$SCRIPT_DIR/test_merge.py"
run_suite "Merge report tests (test_merge_report.py)" python3 -m unittest "$SCRIPT_DIR/test_merge_report.py"
run_suite "Merge git tests (test_merge_git.py)" python3 -m unittest "$SCRIPT_DIR/test_merge_git.py"
run_suite "Merge CLI tests (test_merge_cli.py)" python3 -m unittest "$SCRIPT_DIR/test_merge_cli.py"
run_suite "Merge sources tests (test_merge_sources.py)" python3 -m unittest "$SCRIPT_DIR/test_merge_sources.py"
run_suite "Merge driver tests (test_merge_driver.py)" python3 -m unittest "$SCRIPT_DIR/test_merge_driver.py"
run_suite "Resolve tests (test_resolve.py)"    python3 -m unittest "$SCRIPT_DIR/test_resolve.py"
run_suite "Scenario tests (test_scenarios.py)" python3 "$SCRIPT_DIR/test_scenarios.py"
run_suite "Scenario tests (test_scenarios.sh)" bash "$SCRIPT_DIR/test_scenarios.sh"
run_suite "Bulk tests (test_bulk.sh)"          bash "$SCRIPT_DIR/test_bulk.sh"
run_suite "UI tests (test_plan-ui.sh)"            bash "$SCRIPT_DIR/test_plan-ui.sh"
run_suite "TUI tests (test_plan-tui.sh)"          bash "$SCRIPT_DIR/test_plan-tui.sh"

run_suite "Stress test (seed=42, 200 ops)" bash -c "python3 '$SCRIPT_DIR/stress_test.py' 42 200 | bash"

echo ""
echo "========================================="
echo "  Summary: ${#PASSED[@]} passed, ${#FAILED[@]} failed"
echo "========================================="
for s in ${PASSED[@]+"${PASSED[@]}"}; do
    echo "  PASS  $s"
done
for s in ${FAILED[@]+"${FAILED[@]}"}; do
    echo "  FAIL  $s"
done

[ ${#FAILED[@]} -eq 0 ]
