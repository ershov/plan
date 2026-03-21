# Examples

[Home](README.md) | [CLI Reference](cli-reference.md) | [DSL](dsl.md)

A cookbook of copy-paste examples organized by task.

## Creating Tickets

```bash
# Simple ticket
plan create 'title="Fix login bug"'

# With attributes
plan create 'title="Implement caching", status="backlog", assignee="alice"'

# Child ticket
plan create 5 'title="Write unit tests"'

# Create and position first
plan create 'title="Urgent hotfix", move="first"'

# Create as first child of #3
plan create 'title="Subtask", move="first 3"'
```

### Bulk Creation from Stdin

```bash
plan create - <<'EOF'
* ## Epic: Payment System
  Implement payment processing.
  * ## Task: Stripe integration
    Connect to Stripe API.
  * ## Task: Payment form
    Build the checkout form.
  * ## Task: Receipt emails
    Send confirmation emails.
EOF
```

### Bulk Creation with Dependencies

```bash
plan create - <<'EOF'
* ## Task: Design schema {#schema}
  Define the database schema.
* ## Task: Create migrations {#migrate}
      links: blocked:#schema
  Write migration files.
* ## Task: Seed data {#seed}
      links: blocked:#migrate
  Create seed data for development.
* ## Task: Build API
      links: blocked:#migrate
  REST endpoints.
EOF
```

### Create as Children of Existing Ticket

```bash
plan create 5 - <<'EOF'
* ## Task: Step 1
  First step.
* ## Task: Step 2
  Second step.
* ## Task: Step 3
  Third step.
EOF
```

## Viewing Tickets

```bash
# View a single ticket
plan 5

# View with all children (tree)
plan 5 -r get

# View comments
plan 5 comment

# View a specific attribute
plan 5 attr status
plan 5 attr assignee

# View project description
plan project description
```

## Listing and Filtering

```bash
# All tickets
plan list

# Open tickets only
plan list is_open

# Active tickets (excludes deferred like backlog)
plan list is_active

# Ready for work (active + no blockers + no active children)
plan list ready

# Execution order (respects dependencies)
plan list order

# Next ticket to work on
plan next

# Next 5 tickets
plan next -n 5

# Filter by assignee
plan 'assignee == "alice"' list

# Filter by status
plan 'status == "in-progress"' list

# Unassigned tickets
plan 'assignee == ""' list

# Title search
plan list --title "auth"

# Text search (title + body)
plan list --text "database"

# Top-level tickets only
plan 'depth == 0' list

# All subtasks (depth > 0)
plan 'depth > 0' list

# Tickets with children
plan 'len(children) > 0' list

# Leaf tickets (no children)
plan 'len(children) == 0' list

# Descendants of #1
plan 1 -r list

# Children of #1 that are active
plan 1 -r is_active list

# Ticket #3 with its ancestor chain
plan -p 3

# Combined: active tickets with tree context
plan -p is_active list

# Limit results
plan list -n 10
plan list order -n 5
```

## Custom Format Output

```bash
# Dashboard view
plan list --format 'f"{indent}#{id} [{status}] {title}"'

# With assignee
plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'

# CSV output
plan list --format 'f"{id},{status},{assignee},{title}"'

# Just IDs
plan list --format 'id'

# Just titles
plan list --format 'title'

# Detailed
plan list --format 'f"#{id} ({status}) {title} [{len(children)} children]"'
```

## Status Management

```bash
# Set status
plan 5 status in-progress
plan 5 status blocked
plan 5 status reviewing

# Close (default: done)
plan 5 close
plan 5 close duplicate
plan 5 close "won't do"

# Reopen
plan 5 reopen

# Bulk status change
plan 5 6 7 status in-progress
plan 1 -r close                        # Close #1 and all descendants

# Close only alice's open tickets under #1
plan 1 -r 'assignee == "alice" and is_open' close
```

## Links and Dependencies

```bash
# Create links
plan 5 link 3                          # related (default)
plan 5 link blocked 3                  # #5 blocked by #3
plan 5 link blocking 3                 # #5 blocks #3
plan 5 link related 3                  # Bidirectional related
plan 5 link derived 3                  # #5 derived from #3
plan 5 link caused 3                   # #5 caused by #3

# Link multiple tickets
plan 1 2 3 link blocked 5             # #1, #2, #3 all blocked by #5

# Remove links
plan 5 unlink 3                        # Remove ALL links between #5 and #3
plan 5 unlink blocked 3               # Remove only the blocked link

# Find blocked tickets
plan 'links.get("blocked")' list
```

## Comments

```bash
# Add a comment
plan 5 comment add "Needs review"
plan 5 comment add "Found edge case with empty input"

# Add comment via editor
plan 5 comment add -e

# View comments
plan 5 comment

# Add comment to all descendants
plan 1 -r comment add "Sprint 5 note"
```

## Modifying Tickets (DSL)

```bash
# Set single attribute
plan 5 ~ 'set(assignee="alice")'
plan 5 ~ 'set(status="in-progress")'

# Set multiple attributes
plan 5 ~ 'set(status="in-progress", assignee="alice")'

# Change title
plan 5 ~ 'set(title="Updated title")'

# Append to body
plan 5 ~ 'add(text="Additional details here")'

# Add a comment via DSL
plan 5 ~ 'add(comment="Reviewed and approved")'

# Delete attributes
plan 5 ~ 'delete("estimate")'
plan 5 ~ 'delete("assignee", "estimate")'

# Add link via DSL
plan 5 ~ 'link("blocked", 3)'

# Chain operations
plan 5 ~ 'set(status="done"), add(comment="Completed")'

# Bulk modification
plan 1 -r ~ 'set(status="open")'                        # Reset all descendants
plan 'assignee == ""' ~ 'set(assignee="unassigned")'     # Tag unassigned
plan 1 -r 'is_open' ~ 'set(status="in-progress")'       # Start all open
```

## Moving and Reordering

```bash
# Reorder among siblings
plan 5 move first                     # First among current siblings
plan 5 move last                      # Last among current siblings

# Move relative to another ticket
plan 5 move before 7                  # Place before #7
plan 5 move after 7                   # Place after #7

# Reparent
plan 5 move first 3                   # First child of #3
plan 5 move last 3                    # Last child of #3
plan 5 move first 0                   # Move to root level

# Move multiple
plan 5 7 9 move first                 # Place in selection order
plan 5 7 move after 3                 # 5 after 3, then 7 after 5

# Move via DSL
plan 5 ~ 'set(move="first")'
plan 5 ~ 'set(move="first 3")'
plan 5 ~ 'set(move="after 7")'
```

## Adding and Replacing Content

```bash
# Append text
plan 5 add "New paragraph"
plan 5 + "Quick note"                 # + is shorthand

# Append from file
plan 5 add @notes.txt

# Append from stdin
echo "Imported text" | plan 5 add -

# Append via editor
plan 5 add -e

# Replace body (requires --force)
plan 5 replace --force "New body text"
plan 5 replace --force @updated.txt
```

## Deleting

```bash
# Delete ticket (no children)
plan 5 del

# Delete ticket and all descendants
plan 5 -r del

# Delete only closed subtasks
plan 1 -r 'not is_open' del

# Delete an attribute
plan 5 attr estimate del
```

## Project Sections

```bash
# List all sections
plan project

# View section
plan project description
plan project metadata

# Append to section
plan project description add "New paragraph"

# Replace section content
plan project description replace --force "Updated description"

# Access by id
plan id description
plan id metadata
```

## Multi-Request Pipelines

Execute multiple operations atomically (single file read-write):

```bash
# Update multiple tickets
plan 5 status done ";" 6 status in-progress

# Close and reassign
plan 3 close ";" 4 ~ 'set(assignee="bob")'

# Create and immediately modify
plan create 'title="New task"' --quiet ";" 1 move last
```

## Validation and Repair

```bash
# Check for structural issues
plan check

# Auto-fix issues
plan fix

# Resolve merge conflicts
plan resolve
```

## Environment and File Selection

```bash
# Use specific plan file
plan -f /path/to/.PLAN.md list

# Set via environment variable
export PLAN_MD=/path/to/.PLAN.md
plan list

# Check which file is being used (create bootstraps if absent)
plan list
```

## See Also

- [Quick Start](quick-start.md) — getting started tutorial
- [CLI Reference](cli-reference.md) — complete reference
- [DSL Expression Language](dsl.md) — expression syntax
- [Workflows](workflows.md) — common workflow patterns
