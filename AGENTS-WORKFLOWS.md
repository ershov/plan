# plan CLI — Agent Workflows

Step-by-step playbooks for common agent tasks.

---

## 1. Starting a Project

Set up a new plan file and create the initial ticket structure.

```bash
# Step 1: Create the first ticket (auto-creates .PLAN.md at git root)
plan create 'title="Project Setup", status="open"'

# Step 2: Verify the file was created
plan list

# Step 3: Add project-level description
plan project description add "This project tracks..."

# Step 4: Create initial work items
plan create 'title="Implement feature X", status="open"'
plan create 'title="Fix bug Y", status="open"'
plan create 'title="Write tests", status="open"'
```

---

## 2. Triaging Work

Understand what's in the backlog and decide what to work on.

```bash
# Step 1: See all open tickets
plan 'status in ("open", "planned")' list

# Step 2: See what's actionable (no blockers, no open children)
plan list ready
plan list order

# Step 3: See unassigned items
plan 'assignee == ""' list

# Step 4: Get full context on a specific ticket
plan 5

# Step 5: Check what's currently in progress
plan 'status == "in-progress"' list

# Step 6: Check blocked tickets and their blockers
plan '"blocked" in str(links)' list --format 'f"{indent}#{id} {title} — links: {links}"'
```

---

## 3. Working a Ticket

Claim a ticket, do the work, and close it.

```bash
# Step 1: Read the ticket to understand requirements
plan 7

# Step 2: Claim it by setting status
plan 7 status in-progress

# Step 3: (Do the actual work — write code, run tests, etc.)

# Step 4: Add progress notes as you work
plan 7 comment add "Implemented the core logic, tests passing"

# Step 5: If you discover additional work, create subtickets under your current ticket
plan create 7 'title="Handle edge case: empty input"'
plan create 7 'title="Add validation for negative values"'

# Step 7: If blocked, record it
plan 7 link blocked 12
plan 7 comment add "Blocked on #12 — need API endpoint first"

# Step 8: When unblocked, remove the link
plan 7 unlink blocked 12

# Step 9: Close when done
plan 7 close
# or with a specific resolution:
plan 7 close fixed
```

---

## 4. Breaking Down Work

Decompose a large ticket into smaller actionable items.

```bash
# Step 1: Read the parent ticket
plan 3

# Step 2: Create child tickets
plan create 3 'title="Design API schema"'
plan create 3 'title="Implement endpoints"'
plan create 3 'title="Write integration tests"'
plan create 3 'title="Update documentation"'

# Step 3: Add dependencies between children
# "Implement endpoints" (#N+1) is blocked by "Design API schema" (#N)
plan 5 link blocked 4

# Step 4: Verify the breakdown
plan 3 list

# Step 5: See full subtree with details
plan 3 -r

# Step 6: The parent stays open until all children are done.
# Check if all children are closed:
plan 3 -r 'status in ("open","in-progress","planned")' list
# If empty, close the parent:
plan 3 close
```

---

## 5. Querying and Reporting

Find specific tickets and generate summaries.

```bash
# All open tickets with custom format
plan 'status in ("open","in-progress")' list \
  --format 'f"{indent}#{id} [{status}] @{assignee} {title}"'

# Count open vs closed (use shell)
echo "Open:"; plan 'status in ("open","in-progress","planned")' list | wc -l
echo "Closed:"; plan 'status not in ("open","in-progress","planned","assigned")' list | wc -l

# Find tickets by title keyword
plan -r list --title "login"

# Find tickets by body text
plan -r list --text "database"

# Get a summary of a ticket and its children
plan 3 --self list

# Get all attributes of a ticket in one view
plan 3
```

---

## 6. Organizing and Restructuring

Move tickets around, change hierarchy, reorder priorities.

```bash
# Step 1: Move ticket #8 to be a child of #3
plan 8 move 3

# Step 2: Reorder children — put #5 first among siblings
plan 5 move first

# Step 3: Position #6 right after #5
plan 6 move after 5

# Step 4: Move #9 to be a sibling before #5 (not reparent, just reorder)
plan 9 move before 5

# Step 5: Bulk status update on a subtree
plan 3 -r ~ 'set(status="planned")'

# Step 6: Bulk close completed children
plan 3 -r 'status == "done"' ~ 'set(status="done")'

# Step 7: Delete obsolete tickets
plan del 15                    # Single ticket (no children)
plan 10 -r del                 # Ticket and all descendants
```

---

## 7. Merge Conflict Resolution

When git merges cause conflicts in the plan file.

```bash
# Step 1: Try automatic resolution
plan resolve

# Step 2: Validate the result
plan check

# Step 3: If issues remain, fix them
plan fix

# Step 4: Verify everything looks correct
plan -r list
```
