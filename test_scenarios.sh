#!/usr/bin/env bash
# Scenario tests for plan.py — deterministic command sequences with
# output checks and file-content diffs.
#
# Usage: bash test_scenarios.sh
#
# Timestamps are normalized to "TIMESTAMP" before diffing so results
# are reproducible across runs.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAN_PY="$SCRIPT_DIR/plan.py"
TMPDIR_BASE=$(mktemp -d)
PLAN_FILE="$TMPDIR_BASE/plan.md"
PASS=0
FAIL=0
ERRORS=""

cleanup() { rm -rf "$TMPDIR_BASE"; }
trap cleanup EXIT

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

normalize() {
    # Replace timestamps (2026-03-04 21:39:30 UTC) with TIMESTAMP
    sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC/TIMESTAMP/g'
}

check_output() {
    # Usage: check_output "LABEL" "EXPECTED" "ACTUAL"
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        local diff_out
        diff_out=$(diff <(echo "$expected") <(echo "$actual") 2>&1)
        ERRORS="${ERRORS}FAIL: ${label}\n${diff_out}\n\n"
    fi
}

check_file() {
    # Usage: check_file "LABEL" "EXPECTED_CONTENT"
    # Normalizes timestamps in both expected and actual before diff.
    local label="$1" expected="$2"
    local actual
    actual=$(cat "$PLAN_FILE" | normalize)
    expected=$(echo "$expected" | normalize)
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        local diff_out
        diff_out=$(diff <(echo "$expected") <(echo "$actual") 2>&1)
        ERRORS="${ERRORS}FAIL: ${label}\n${diff_out}\n\n"
    fi
}

run_plan() {
    # Run plan.py, return stdout.  Fails test on non-zero exit.
    local label="$1"; shift
    local out
    out=$(python3 "$PLAN_PY" --file "$PLAN_FILE" "$@" 2>"$TMPDIR_BASE/stderr.tmp")
    local rc=$?
    if [ $rc -ne 0 ]; then
        FAIL=$((FAIL + 1))
        local err
        err=$(cat "$TMPDIR_BASE/stderr.tmp")
        ERRORS="${ERRORS}FAIL: ${label} — exit ${rc}\n  stderr: ${err}\n\n"
    fi
    echo "$out"
}

# ==========================================================================
# Scenario 1
# ==========================================================================

rm -f "$PLAN_FILE"

# --------------------------------------------------------------------------
# Step 1: Create first ticket
# --------------------------------------------------------------------------

out=$(run_plan "create #1" create 'title="Auth system"')
check_output "create #1 stdout" "1" "$out"

check_file "file after create #1" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 2

## Tickets {#tickets}

* ## Ticket: Task: Auth system {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP'

out=$(run_plan "list after #1" list)
check_output "list after #1" "#1 [open] Auth system" "$out"

out=$(run_plan "get #1" 1 get | normalize)
check_output "get #1" '## Task: Auth system {#1}

    updated: TIMESTAMP
    status: open
    created: TIMESTAMP' "$out"

# --------------------------------------------------------------------------
# Step 2: Create child of #1 with body text
# --------------------------------------------------------------------------

out=$(run_plan "create #2" create 1 'title="Login flow", text="Implement OAuth2 login."')
check_output "create #2 stdout" "2" "$out"

check_file "file after create #2" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 3

## Tickets {#tickets}

* ## Ticket: Task: Auth system {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: Login flow {#2}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

    Implement OAuth2 login.'

out=$(run_plan "list after #2" list)
check_output "list: all tickets" "#1 [open] Auth system
  #2 [open] Login flow" "$out"

# list with target: shows the ticket itself
out=$(run_plan "list #1" 1 list)
check_output "list #1" "#1 [open] Auth system" "$out"

# list with target + -r: shows ticket and descendants
out=$(run_plan "list #1 -r" 1 -r list)
check_output "list #1 -r" "#1 [open] Auth system
  #2 [open] Login flow" "$out"

out=$(run_plan "get #2" 2 get | normalize)
check_output "get #2 has body" '## Task: Login flow {#2}

    updated: TIMESTAMP
    status: open
    created: TIMESTAMP

Implement OAuth2 login.' "$out"

# --------------------------------------------------------------------------
# Step 3: Create child of #2 (grandchild of #1)
# --------------------------------------------------------------------------

out=$(run_plan "create #3" create 2 'title="Token refresh"')
check_output "create #3 stdout" "3" "$out"

check_file "file after create #3" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 4

## Tickets {#tickets}

* ## Ticket: Task: Auth system {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: Login flow {#2}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

    Implement OAuth2 login.

    * ## Ticket: Task: Token refresh {#3}

          updated: TIMESTAMP
          status: open
          created: TIMESTAMP'

# Bare list: all tickets
out=$(run_plan "list (all)" list)
check_output "list: all tickets" "#1 [open] Auth system
  #2 [open] Login flow
    #3 [open] Token refresh" "$out"

# list with target: shows the ticket
out=$(run_plan "list #1" 1 list)
check_output "list #1: self" "#1 [open] Auth system" "$out"

out=$(run_plan "list #2" 2 list)
check_output "list #2: self" "  #2 [open] Login flow" "$out"

out=$(run_plan "list #3" 3 list)
check_output "list #3: self" "    #3 [open] Token refresh" "$out"

# Target + -r: self and descendants
out=$(run_plan "list #1 -r" 1 -r list)
check_output "list #1 -r" "#1 [open] Auth system
  #2 [open] Login flow
    #3 [open] Token refresh" "$out"

out=$(run_plan "list #2 -r" 2 -r list)
check_output "list #2 -r" "  #2 [open] Login flow
    #3 [open] Token refresh" "$out"

out=$(run_plan "list #3 -r" 3 -r list)
check_output "list #3 -r: leaf" "    #3 [open] Token refresh" "$out"

# get with -r: shows subtree
out=$(run_plan "get #1 -r" 1 -r get | normalize)
check_output "get #1 -r shows subtree" '* ## Task: Auth system {#1}
  * ## Task: Login flow {#2}
    * ## Task: Token refresh {#3}

          updated: TIMESTAMP
          status: open
          created: TIMESTAMP' "$out"

out=$(run_plan "get #2 -r" 2 -r get | normalize)
check_output "get #2 -r" '* ## Task: Login flow {#2}
  * ## Task: Token refresh {#3}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP' "$out"

# get -r on leaf = just that ticket (flat, no bullet)
out=$(run_plan "get #3 -r" 3 -r get | normalize)
check_output "get #3 -r (leaf)" '## Task: Token refresh {#3}

    updated: TIMESTAMP
    status: open
    created: TIMESTAMP' "$out"

# --------------------------------------------------------------------------
# Step 4: Create second root with children at different levels
# --------------------------------------------------------------------------

run_plan "create #4" create 'title="API layer"' > /dev/null
run_plan "create #5" create 4 'title="REST endpoints"' > /dev/null
run_plan "create #6" create 4 'title="GraphQL endpoints"' > /dev/null
run_plan "create #7" create 5 'title="Pagination"' > /dev/null

check_file "file after 4 more tickets" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 8

## Tickets {#tickets}

* ## Ticket: Task: Auth system {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: Login flow {#2}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

    Implement OAuth2 login.

    * ## Ticket: Task: Token refresh {#3}

          updated: TIMESTAMP
          status: open
          created: TIMESTAMP

* ## Ticket: Task: API layer {#4}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: REST endpoints {#5}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

    * ## Ticket: Task: Pagination {#7}

          updated: TIMESTAMP
          status: open
          created: TIMESTAMP

  * ## Ticket: Task: GraphQL endpoints {#6}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP'

out=$(run_plan "list all" list)
check_output "full tree" "#1 [open] Auth system
  #2 [open] Login flow
    #3 [open] Token refresh
#4 [open] API layer
  #5 [open] REST endpoints
    #7 [open] Pagination
  #6 [open] GraphQL endpoints" "$out"

out=$(run_plan "list #4 -r" 4 -r list)
check_output "list #4 -r" "#4 [open] API layer
  #5 [open] REST endpoints
    #7 [open] Pagination
  #6 [open] GraphQL endpoints" "$out"

out=$(run_plan "list #5 -r" 5 -r list)
check_output "list #5 -r" "  #5 [open] REST endpoints
    #7 [open] Pagination" "$out"

# Subtree isolation: list -r on one branch must NOT contain the other branch.
out=$(run_plan "list #1 -r isolation" 1 -r list)
check_output "list #1 -r shows Auth subtree" "#1 [open] Auth system
  #2 [open] Login flow
    #3 [open] Token refresh" "$out"
if echo "$out" | grep -qE "API layer|REST endpoints|GraphQL|Pagination"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: list #1 -r leaks API branch\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

out=$(run_plan "list #4 -r isolation" 4 -r list)
check_output "list #4 -r shows API subtree" "#4 [open] API layer
  #5 [open] REST endpoints
    #7 [open] Pagination
  #6 [open] GraphQL endpoints" "$out"
if echo "$out" | grep -qE "Auth system|Login flow|Token refresh"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: list #4 -r leaks Auth branch\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

out=$(run_plan "list #5 -r isolation" 5 -r list)
check_output "list #5 -r shows REST subtree" "  #5 [open] REST endpoints
    #7 [open] Pagination" "$out"
if echo "$out" | grep -qE "GraphQL|Auth|Login|API layer"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: list #5 -r leaks sibling/parent\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

out=$(run_plan "list #2 -r isolation" 2 -r list)
check_output "list #2 -r shows Login subtree" "  #2 [open] Login flow
    #3 [open] Token refresh" "$out"
if echo "$out" | grep -qE "Auth system|API layer|REST|GraphQL|Pagination"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: list #2 -r leaks parent/other branch\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

# list -r on leaf: just the leaf
out=$(run_plan "list #6 -r isolation" 6 -r list)
check_output "list #6 -r (leaf)" "  #6 [open] GraphQL endpoints" "$out"
if echo "$out" | grep -qE "REST|Pagination|Auth|API layer"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: list #6 -r leaks other tickets\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

# --------------------------------------------------------------------------
# Step 4b: Recursive verbs on the tree
# --------------------------------------------------------------------------

# status -r: set all descendants of #4 to in-progress
run_plan "status -r #4" 4 -r status in-progress > /dev/null

out=$(run_plan "attr status get #4" 4 attr status get)
check_output "status -r: #4 is in-progress" "in-progress" "$out"

out=$(run_plan "attr status get #5" 5 attr status get)
check_output "status -r: #5 is in-progress" "in-progress" "$out"

out=$(run_plan "attr status get #6" 6 attr status get)
check_output "status -r: #6 is in-progress" "in-progress" "$out"

out=$(run_plan "attr status get #7" 7 attr status get)
check_output "status -r: #7 is in-progress" "in-progress" "$out"

# Auth subtree (#1,#2,#3) should still be open
out=$(run_plan "attr status get #1" 1 attr status get)
check_output "status -r: #1 still open" "open" "$out"

# mod -r -q: set estimate=9h on in-progress tickets under #4
run_plan "mod -r -q #4" 4 -r -q 'status == "in-progress"' mod 'set(estimate="9h")' > /dev/null

out=$(run_plan "attr estimate #5" 5 attr estimate get)
check_output "mod -r -q: #5 has estimate 9h" "9h" "$out"

out=$(run_plan "attr estimate #6" 6 attr estimate get)
check_output "mod -r -q: #6 has estimate 9h" "9h" "$out"

# close -r -q: close only in-progress tickets under #4
run_plan "close -r -q #4" 4 -r -q 'status == "in-progress"' close done > /dev/null

out=$(run_plan "attr status #4 after close" 4 attr status get)
check_output "close -r -q: #4 is done" "done" "$out"

out=$(run_plan "attr status #5 after close" 5 attr status get)
check_output "close -r -q: #5 is done" "done" "$out"

# get -r -q: show only open tickets under #1
out=$(run_plan "get -r -q #1 open" 1 -r -q 'status == "open"' get | normalize)
# Should show #1, #2, #3 content (all open) but not #4 branch
check_count=$(echo "$out" | grep -c "^## \|^\* ## \|^  \* ## " || true)
if [ "$check_count" -ge 1 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: get -r -q should show open tickets, got empty\n\n"
fi
if echo "$out" | grep -q "API layer"; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: get -r -q on #1 should not show API branch\n  got: ${out}\n\n"
else
    PASS=$((PASS + 1))
fi

# Reset statuses and estimates back for the remaining steps
run_plan "reset status #4" 4 -r status open > /dev/null
run_plan "reset estimate #4" 4 mod 'set(estimate="3h")' > /dev/null
run_plan "reset estimate #5" 5 attr estimate del > /dev/null
run_plan "reset estimate #6" 6 attr estimate del > /dev/null
run_plan "reset estimate #7" 7 attr estimate del > /dev/null

# --------------------------------------------------------------------------
# Step 5: Delete a leaf ticket (#7 Pagination)
# --------------------------------------------------------------------------

run_plan "del #7" 7 del > /dev/null

check_file "file after del #7" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 8

## Tickets {#tickets}

* ## Ticket: Task: Auth system {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: Login flow {#2}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

    Implement OAuth2 login.

    * ## Ticket: Task: Token refresh {#3}

          updated: TIMESTAMP
          status: open
          created: TIMESTAMP

* ## Ticket: Task: API layer {#4}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP
      estimate: 3h

  * ## Ticket: Task: REST endpoints {#5}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

  * ## Ticket: Task: GraphQL endpoints {#6}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP'

# --------------------------------------------------------------------------
# Step 6: Delete #1 recursively (removes #1, #2, #3)
# --------------------------------------------------------------------------

run_plan "del -r #1" 1 -r del > /dev/null

check_file "file after del -r #1" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 8

## Tickets {#tickets}

* ## Ticket: Task: API layer {#4}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP
      estimate: 3h

  * ## Ticket: Task: REST endpoints {#5}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

  * ## Ticket: Task: GraphQL endpoints {#6}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP'

out=$(run_plan "list after del subtree" list)
check_output "tree after recursive del" "#4 [open] API layer
  #5 [open] REST endpoints
  #6 [open] GraphQL endpoints" "$out"

# Deleted IDs are gone
python3 "$PLAN_PY" --file "$PLAN_FILE" 1 get 2>/dev/null
if [ $? -eq 0 ]; then
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}FAIL: #1 should not be found after recursive delete\n\n"
else
    PASS=$((PASS + 1))
fi

# --------------------------------------------------------------------------
# Step 7: Add project section
# --------------------------------------------------------------------------

run_plan "add description" project description add 'This project implements a REST API.' > /dev/null

check_file "file after add description" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 8

## Description {#description}

This project implements a REST API.

## Tickets {#tickets}

* ## Ticket: Task: API layer {#4}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP
      estimate: 3h

  * ## Ticket: Task: REST endpoints {#5}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP

  * ## Ticket: Task: GraphQL endpoints {#6}

        updated: TIMESTAMP
        status: open
        created: TIMESTAMP'

out=$(run_plan "project desc get" project description get)
check_output "project description get" "## Description {#description}

This project implements a REST API." "$out"

# Final check
out=$(run_plan "final check" check)
check_output "final check passes" "OK: no errors found" "$out"

# ==========================================================================
# Report
# ==========================================================================

echo "========================="
echo "Scenario tests complete"
echo "Passed: $PASS / Failed: $FAIL"
if [ -n "$ERRORS" ]; then
    echo ""
    echo "Failures:"
    echo -e "$ERRORS"
fi
echo "========================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
