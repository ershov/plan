#!/usr/bin/env bash
# Scenario tests for bulk ticket creation & editing in plan.py.
#
# Usage: bash test_bulk.sh
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
    sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC/TIMESTAMP/g'
}

check_output() {
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

run_plan_fail() {
    # Expect command to fail. Returns combined stdout+stderr.
    local label="$1" expected_msg="$2"; shift 2
    local out
    out=$(python3 "$PLAN_PY" --file "$PLAN_FILE" "$@" 2>&1)
    local rc=$?
    if [ $rc -eq 0 ]; then
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}FAIL: ${label} — expected failure but got exit 0\n  stdout: ${out}\n\n"
        return
    fi
    if echo "$out" | grep -qF "$expected_msg"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}FAIL: ${label} — expected message '${expected_msg}'\n  got: ${out}\n\n"
    fi
}

# ==========================================================================
# Scenario 1: Single bulk ticket from stdin
# ==========================================================================

rm -f "$PLAN_FILE"

out=$(printf '* ## Ticket: Task: Hello World\n\n  This is the body.\n' \
    | run_plan "bulk-single: create" create -)
check_output "bulk-single: stdout" "1" "$out"

check_file "bulk-single: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 2

## Tickets {#tickets}

* ## Ticket: Task: Hello World {#1}

      status: open
      created: TIMESTAMP
      updated: TIMESTAMP

  This is the body.'

out=$(run_plan "bulk-single: check" check)
check_output "bulk-single: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 2: Hierarchy with cross-references
# ==========================================================================

rm -f "$PLAN_FILE"

BULK_INPUT='* ## Ticket: Epic: Auth System {#newAuth}

      links: blocking:#newDB

  Implement JWT-based authentication.

  * ## Ticket: Task: JWT Middleware

    Token verification.

  * ## Ticket: Task: Login Endpoint

        links: blocked:#newDB

    POST /login.

* ## Ticket: Epic: Database Layer {#newDB}

      links: blocked:#newAuth

  Schema design.'

out=$(printf '%s\n' "$BULK_INPUT" | run_plan "bulk-hierarchy: create" create -)
check_output "bulk-hierarchy: stdout" "1
2
3
4" "$out"

check_file "bulk-hierarchy: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 5

## Tickets {#tickets}

* ## Ticket: Epic: Auth System {#1}

      links: blocking:#4
      status: open
      created: TIMESTAMP
      updated: TIMESTAMP

  Implement JWT-based authentication.

  * ## Ticket: Task: JWT Middleware {#2}

        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Token verification.

  * ## Ticket: Task: Login Endpoint {#3}

        links: blocked:#4
        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    POST /login.

* ## Ticket: Epic: Database Layer {#4}

      links: blocked:#1
      status: open
      created: TIMESTAMP
      updated: TIMESTAMP

  Schema design.'

out=$(run_plan "bulk-hierarchy: check" check)
check_output "bulk-hierarchy: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 3: Bulk create under existing parent
# ==========================================================================

rm -f "$PLAN_FILE"

# Create a parent ticket first (expression mode)
out=$(run_plan "bulk-under-parent: create parent" create 'title="Parent Epic", type="Epic"')
check_output "bulk-under-parent: parent stdout" "1" "$out"

# Bulk-create children under #1
out=$(printf '* ## Ticket: Task: Child One\n\n  First child.\n\n* ## Ticket: Task: Child Two\n\n  Second child.\n' \
    | run_plan "bulk-under-parent: create children" create 1 -)
check_output "bulk-under-parent: children stdout" "2
3" "$out"

check_file "bulk-under-parent: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 4

## Tickets {#tickets}

* ## Ticket: Task: Parent Epic {#1}

      type: Epic
      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: Child One {#2}

        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    First child.

  * ## Ticket: Task: Child Two {#3}

        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Second child.'

out=$(run_plan "bulk-under-parent: check" check)
check_output "bulk-under-parent: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 4: Rank reparenting in bulk create
# ==========================================================================

rm -f "$PLAN_FILE"

REPARENT_INPUT='* ## Ticket: Epic: Parent A {#newA}

  * ## Ticket: Task: Child of A

    Belongs under A.

* ## Ticket: Epic: Parent B {#newB}

  * ## Ticket: Task: Move to A

        move: last #newA

    Should end up under A.'

out=$(printf '%s\n' "$REPARENT_INPUT" | run_plan "bulk-reparent: create" create -)
check_output "bulk-reparent: stdout" "1
2
3
4" "$out"

check_file "bulk-reparent: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 5

## Tickets {#tickets}

* ## Ticket: Epic: Parent A {#1}

      status: open
      created: TIMESTAMP
      updated: TIMESTAMP

  * ## Ticket: Task: Child of A {#2}

        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Belongs under A.

  * ## Ticket: Task: Move to A {#4}

        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Should end up under A.

* ## Ticket: Epic: Parent B {#3}

      status: open
      created: TIMESTAMP
      updated: TIMESTAMP'

out=$(run_plan "bulk-reparent: check" check)
check_output "bulk-reparent: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 5: edit -r adding new tickets
# ==========================================================================

rm -f "$PLAN_FILE"

out=$(run_plan "edit-r-new: create parent" create 'title="Parent"')
check_output "edit-r-new: parent stdout" "1" "$out"

# Create a fake editor that appends a new child ticket
cat > "$TMPDIR_BASE/editor5.sh" << 'EDSCRIPT'
#!/bin/bash
cat >> "$1" << 'EOF'

  * ## Ticket: Task: New Child

        links: depends:#1

    Added via edit.
EOF
EDSCRIPT
chmod +x "$TMPDIR_BASE/editor5.sh"

EDITOR="$TMPDIR_BASE/editor5.sh" run_plan "edit-r-new: edit" edit 1 -r >/dev/null

check_file "edit-r-new: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 3

## Tickets {#tickets}

* ## Ticket: Task: Parent {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: New Child {#2}

        links: depends:#1
        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Added via edit.'

out=$(run_plan "edit-r-new: check" check)
check_output "edit-r-new: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 6: edit -r adding new tickets with cross-references
# ==========================================================================

rm -f "$PLAN_FILE"

out=$(run_plan "edit-r-xref: create root" create 'title="Root"')
check_output "edit-r-xref: root stdout" "1" "$out"

# Editor adds two new children with cross-references
cat > "$TMPDIR_BASE/editor6.sh" << 'EDSCRIPT'
#!/bin/bash
cat >> "$1" << 'EOF'

  * ## Ticket: Task: New A {#newA}

        links: blocking:#newB

    First new.

  * ## Ticket: Task: New B {#newB}

        links: blocked:#newA

    Second new.
EOF
EDSCRIPT
chmod +x "$TMPDIR_BASE/editor6.sh"

EDITOR="$TMPDIR_BASE/editor6.sh" run_plan "edit-r-xref: edit" edit 1 -r >/dev/null

check_file "edit-r-xref: file" \
'# Project {#project}

## Metadata {#metadata}

    next_id: 4

## Tickets {#tickets}

* ## Ticket: Task: Root {#1}

      updated: TIMESTAMP
      status: open
      created: TIMESTAMP

  * ## Ticket: Task: New A {#2}

        links: blocking:#3
        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    First new.

  * ## Ticket: Task: New B {#3}

        links: blocked:#2
        status: open
        created: TIMESTAMP
        updated: TIMESTAMP

    Second new.'

out=$(run_plan "edit-r-xref: check" check)
check_output "edit-r-xref: check" "OK: no errors found" "$out"

# ==========================================================================
# Scenario 7: Error — explicit numeric ID in create mode
# ==========================================================================

rm -f "$PLAN_FILE"

run_plan_fail "err-numeric-id: create" \
    "all tickets must be new; found existing numeric ID" \
    create - <<< '* ## Ticket: Task: Bad {#42}'

# ==========================================================================
# Scenario 8: Error — undefined placeholder reference
# ==========================================================================

rm -f "$PLAN_FILE"

run_plan_fail "err-undef-placeholder: create" \
    "Undefined placeholder references" \
    create - << 'EOF'
* ## Ticket: Task: Ref test

      links: blocked:#newMissing
EOF

# ==========================================================================
# Scenario 9: Error — duplicate placeholder names
# ==========================================================================

rm -f "$PLAN_FILE"

run_plan_fail "err-dup-placeholder: create" \
    "Duplicate placeholder" \
    create - << 'EOF'
* ## Ticket: Task: First {#newDup}

* ## Ticket: Task: Second {#newDup}
EOF

# ==========================================================================
# Summary
# ==========================================================================

echo ""
echo "========================================="
echo "  Bulk scenario tests: $PASS passed, $FAIL failed"
echo "========================================="
if [ $FAIL -gt 0 ]; then
    echo ""
    printf "%b" "$ERRORS"
    exit 1
fi
