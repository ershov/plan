#!/bin/bash
# Non-interactive tests for plan-tui data layer and state management
set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/plan-tui"
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

# --- Test data layer: plan_list (root scope) ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
tickets = plan_list(None)
for t in tickets:
    print('{id}\t{parent}\t{status}\t{has_children}\t{depth}\t{title}'.format(**t))
")
assert_contains "plan_list shows Alpha" 'Alpha' "$OUT"
assert_contains "plan_list shows Beta" 'Beta' "$OUT"
assert_contains "plan_list shows Beta child" 'Beta child' "$OUT"

# --- Test data layer: plan_list (scoped) ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
tickets = plan_list(2)
for t in tickets:
    print('{id}\t{title}'.format(**t))
")
assert_contains "scoped plan_list shows Beta" 'Beta' "$OUT"
assert_contains "scoped plan_list shows child" 'Beta child' "$OUT"

# --- Test data layer: plan_get ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
text, err = plan_get(1)
print(text)
")
assert_contains "plan_get shows Alpha" 'Alpha' "$OUT"

# --- Test data layer: plan_get project ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
text, err = plan_get(0)
print(text)
")
# Should not error (project get returns something)
assert_eq "plan_get project does not fail" "0" "$?"

# --- Test data layer: plan_children ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
children, err = plan_children(2)
for c in children:
    print('{id}\t{title}'.format(**c))
")
assert_contains "plan_children shows Beta child" 'Beta child' "$OUT"

# --- Test state: visible_tickets at root ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
all_tickets = plan_list(None)
_mark_visible_dirty()
vis = visible_tickets()
for t in vis:
    print('{id}\t{title}'.format(**t))
")
assert_contains "visible_tickets has Project entry" '^0\tProject' "$OUT"
assert_contains "visible_tickets has Alpha" '1\tAlpha' "$OUT"
assert_contains "visible_tickets has Beta" '2\tBeta' "$OUT"

# --- Test state: visible_tickets hides children when collapsed ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
all_tickets = plan_list(None)
_mark_visible_dirty()
vis = visible_tickets()
for t in vis:
    print('{id}\t{title}'.format(**t))
")
if echo "$OUT" | grep -qE 'Beta child'; then
  ((FAIL++)); ERRORS+=("FAIL: collapsed view should hide children")
else
  ((PASS++))
fi

# --- Test state: visible_tickets shows children when expanded ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
all_tickets = plan_list(None)
expanded.add(2)
_mark_visible_dirty()
vis = visible_tickets()
for t in vis:
    print('{id}\t{title}'.format(**t))
")
assert_contains "expanded view shows Beta child" 'Beta child' "$OUT"

# --- Test data layer: plan_close / plan_reopen ---
python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
plan_close([1])
" > /dev/null
OUT_AFTER=$(plan 1 list --format 'f"{status}"')
assert_eq "close sets status done" "done" "$OUT_AFTER"

python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
plan_reopen([1])
" > /dev/null
OUT_AFTER=$(plan 1 list --format 'f"{status}"')
assert_eq "reopen sets status open" "open" "$OUT_AFTER"

# --- Test cache_invalidate ---
OUT=$(python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('$SELF').read().split(\"if __name__\")[0])
plan_list(None)
cache_invalidate()
# After invalidation, next call should refetch
tickets = plan_list(None)
print(len(tickets))
")
assert_contains "cache works after invalidate" '[0-9]' "$OUT"

# --- Summary ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
for e in "${ERRORS[@]+"${ERRORS[@]}"}"; do echo -e "  $e"; done
[[ $FAIL -eq 0 ]]
