#!/bin/bash
# Non-interactive tests for plzf --function callbacks
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/plzf"
PLAN="$(cd "$(dirname "$0")" && pwd)/plan.py"
PASS=0; FAIL=0; ERRORS=()

plan() { "$PLAN" "$@"; }

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    ((PASS++))
  else
    ((FAIL++))
    ERRORS+=("FAIL: $label\n  expected: $expected\n  actual:   $actual")
  fi
}

assert_contains() {
  local label="$1" pattern="$2" actual="$3"
  if echo "$actual" | grep -qE "$pattern"; then
    ((PASS++))
  else
    ((FAIL++))
    ERRORS+=("FAIL: $label\n  pattern: $pattern\n  actual:  $actual")
  fi
}

# --- Setup test plan file ---
TFILE="$(mktemp)"
trap "rm -f '$TFILE'" EXIT
export PLAN_MD="$TFILE"

plan create 'title="Alpha"' > /dev/null
plan create 'title="Beta"' > /dev/null
plan create 2 'title="Beta child"' > /dev/null

# --- Test _fn_list (root scope, no depth limit) ---
export PLZF_STATE="$(mktemp)"; export PLZF_DEPTH="$(mktemp)"
trap "rm -f '$TFILE' '$PLZF_STATE' '$PLZF_DEPTH'" EXIT

OUT=$("$SELF" --function list)
assert_contains "list shows Alpha" '#1.*Alpha' "$OUT"
assert_contains "list shows Beta" '#2.*Beta' "$OUT"
assert_contains "list shows Beta child indented" '  #3.*Beta child' "$OUT"

# --- Test _fn_list (scoped to ticket 2) ---
echo -n "2" > "$PLZF_STATE"
OUT=$("$SELF" --function list)
assert_contains "scoped list shows Beta" '#2.*Beta' "$OUT"
assert_contains "scoped list shows child" '#3.*Beta child' "$OUT"

# --- Test _fn_preview (with children) ---
echo -n "" > "$PLZF_STATE"
export FZF_PREVIEW_LINES=10 FZF_PREVIEW_COLUMNS=120
OUT=$("$SELF" --function preview 2)
assert_contains "preview has column separator" '│' "$OUT"

# --- Test _fn_preview (no children) ---
OUT=$("$SELF" --function preview 1)
assert_contains "preview shows ticket detail" 'Alpha' "$OUT"

# --- Test _fn_down ---
echo -n "" > "$PLZF_STATE"
"$SELF" --function down 2
assert_eq "down sets scope" "2" "$(cat "$PLZF_STATE")"

# --- Test _fn_up from scoped ---
echo -n "3" > "$PLZF_STATE"
"$SELF" --function up
# Ticket 3's parent is ticket 2
assert_eq "up from child goes to parent" "2" "$(cat "$PLZF_STATE")"

# --- Test _fn_up from root child ---
echo -n "2" > "$PLZF_STATE"
"$SELF" --function up
assert_eq "up from top-level goes to root" "" "$(cat "$PLZF_STATE")"

# --- Test _fn_up from root (no-op) ---
echo -n "" > "$PLZF_STATE"
"$SELF" --function up
assert_eq "up from root stays root" "" "$(cat "$PLZF_STATE")"

# --- Test _fn_collapse / _fn_expand ---
echo -n "" > "$PLZF_DEPTH"
"$SELF" --function collapse
assert_eq "collapse from all sets depth 1" "1" "$(cat "$PLZF_DEPTH")"

"$SELF" --function collapse
assert_eq "collapse again sets depth 0" "0" "$(cat "$PLZF_DEPTH")"

"$SELF" --function collapse
assert_eq "collapse at 0 stays 0" "0" "$(cat "$PLZF_DEPTH")"

"$SELF" --function expand
assert_eq "expand from 0 sets depth 1" "1" "$(cat "$PLZF_DEPTH")"

"$SELF" --function expand
assert_eq "expand past max resets to all" "" "$(cat "$PLZF_DEPTH")"

# --- Test _fn_list with depth filter ---
echo -n "" > "$PLZF_STATE"
echo -n "0" > "$PLZF_DEPTH"
OUT=$("$SELF" --function list)
assert_contains "depth-filtered list shows Alpha" '#1.*Alpha' "$OUT"
assert_contains "depth-filtered list shows Beta" '#2.*Beta' "$OUT"
if echo "$OUT" | grep -qE 'Beta child'; then
  ((FAIL++)); ERRORS+=("FAIL: depth filter should hide children")
else
  ((PASS++))
fi

# --- Test create -e with move attribute prefill ---
OUT=$(EDITOR=cat plan create -e 'title="Movable", move="last 1"' 2>/dev/null)
assert_contains "create -e move prefill" 'move: last 1' "$OUT"
# Ticket should have been created (editor returns template as-is)
OUT2=$(plan list --format 'f"#{id} {title}"')
assert_contains "create -e move created ticket" 'Movable' "$OUT2"

# _fn_status, _fn_move, _fn_create require interactive fzf — tested manually

# --- Test _fn_close ---
# plan close sets status to "done" by default
echo -n "" > "$PLZF_STATE"
"$SELF" --function close 1
OUT_AFTER=$(plan 1 list --format 'f"{status}"')
assert_eq "close sets status done" "done" "$OUT_AFTER"

# --- Test _fn_reopen ---
"$SELF" --function reopen 1
OUT_AFTER=$(plan 1 list --format 'f"{status}"')
assert_eq "reopen sets status open" "open" "$OUT_AFTER"

# --- Summary ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
for e in "${ERRORS[@]+"${ERRORS[@]}"}"; do echo -e "  $e"; done
[[ $FAIL -eq 0 ]]
