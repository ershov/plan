# Plan — Agent Usage Guide

This document describes how AI agents and scripts should use `plan` for
non-interactive ticket management. All operations are performed through the CLI
with no interactive prompts, no editor, and no TTY required.

---

## Table of Contents

1. [Principles](#principles)
2. [Setup and File Discovery](#setup-and-file-discovery)
3. [Reading Context](#reading-context)
4. [Work Loop](#work-loop)
5. [Creating and Structuring Tickets](#creating-and-structuring-tickets)
6. [Modifying Tickets](#modifying-tickets)
7. [Non-Interactive Editing](#non-interactive-editing)
8. [Querying and Filtering](#querying-and-filtering)
9. [Bulk Operations](#bulk-operations)
10. [Multi-Agent Coordination](#multi-agent-coordination)
11. [Piping and Stdin Patterns](#piping-and-stdin-patterns)
12. [Error Handling](#error-handling)
13. [Recipes](#recipes)

---

## Principles

1. **No interactive commands.** Never use `edit` without `--start` — it launches `$EDITOR`.
   Use `add`, `mod`/`~`, and `create` for attribute and body changes.
   Use `edit --start` / `edit --accept` only when you need to restructure
   a ticket's markdown body or rearrange a subtree.
2. **Prefer `add` and `mod`/`~` over `replace`.** `add` appends text,
   `~ 'set(key=val)'` sets attributes. Use `replace --force` only when you
   need to overwrite an entire body and `add` won't work (e.g. the existing
   content is wrong and must be discarded).
3. **One file, one write.** Multiple operations can be batched with `;` in a
   single invocation. The file is read once and written once.
4. **Stdout is your API.** All output goes to stdout. Errors go to stderr.
   Exit code 0 means success.
5. **Use `--format` for structured output.** Default list output is
   human-readable. Use `--format` to get exactly the fields you need.
6. **IDs are stable integers.** Moving or reparenting a ticket never changes
   its ID. Always reference tickets by ID, never by title.
7. **`create` prints the new ID to stdout.** Capture it to reference the
   ticket in subsequent commands.
8. **Set title and body in one `create` call.** Use `text=` to include body
   content directly: `create 'title="...", text="..."'`. This avoids an
   extra `add` invocation and a second file write.

---

## Setup and File Discovery

Set the `PLAN_MD` environment variable so every invocation finds the file
automatically:

```bash
export PLAN_MD=/path/to/repo/.PLAN.md
```

Alternatively, pass `-f` on every call:

```bash
plan -f /path/to/.PLAN.md list
```

If neither is set, `plan` looks for `.PLAN.md` at the git root of the
current working directory.

---

## Reading Context

Before starting work, read the project context and understand what's available.

### Project information

Project-level sections are tagged with `{#id}` markers in the markdown
(e.g. `## Building {#building}`) and are individually retrievable. The
standard sections are:

```bash
# Agent-specific instructions — read this first
plan project agents

# Project description (goal, architecture, key decisions)
plan project description

# Build instructions
plan project building

# Test instructions
plan project testing

# Design conventions and patterns
plan project design

# Your role instructions (if roles are defined)
plan project role:executor
```

The `agents` section contains concise, actionable rules written
specifically for AI agents: workflow expectations, code conventions,
guardrails, and communication norms. Always read it before picking
up your first ticket.

Sections are auto-created when you write to one that doesn't exist:

```bash
plan project building add "Run: make build"
```

### Ticket overview

```bash
# All tickets
plan list

# All tickets with status
plan --format 'f"{indent}#{id} [{status}] {title}"' list

# All tickets with all key attributes
plan --format 'f"{indent}#{id} [{status}] @{assignee} {title}"' list
```

### Reading a specific ticket

```bash
# Ticket content (body text, metadata)
plan 5

# Ticket with its ancestor chain for context
plan -p 5

# Just the status
plan 5 attr status

# Just the links
plan 5 attr links

# Ticket 5 and its subtree
plan 5 -r list

# Children of ticket 5 only
plan children_of(5) list
```

---

## Work Loop

The standard agent work loop:

```
0. Read instructions    →  plan project agents  (once per session)
1. Find next task       →  plan list ready (or plan list order)
2. Read the task        →  plan N
3. Read context         →  plan -p N  (ancestor chain)
                           plan project description  (project context)
4. Claim the task       →  plan N status in-progress
5. Do the work          →  (write code, run tests, etc.)
6. Log progress         →  plan N add "Implementation notes..."
7. Close the task       →  plan N close
8. Loop                 →  go to 1
```

### Finding ready tasks

`list ready` returns open tickets that have no open blockers and no open
children — the true "what to work on next":

```bash
plan list ready
plan list order
```

With more detail:

```bash
plan list ready --format 'f"{indent}#{id} {title}"'
plan list order --format 'f"{indent}#{id} {title}"'
```

The first result is typically the highest-priority available task.

### Claiming a task

```bash
# Assign yourself and mark in-progress in one call
plan N ~ 'set(status="in-progress", assignee="agent-1")'
```

Or as two separate operations:

```bash
plan N status in-progress
```

### Closing a task

```bash
plan N close
```

With a resolution:

```bash
plan N close done
plan N close "won't do"
plan N close "duplicate of #3"
```

---

## Creating and Structuring Tickets

### Creating tickets

The `create` command takes a Python expression (implicitly wrapped in `set()`).
`title` is mandatory. It prints the new ticket ID to stdout.

```bash
# Top-level ticket
plan create 'title="Epic: User Auth"'
# → prints: 1

# Child of ticket #1 — title and body in one call
plan create 1 'title="Task: JWT middleware", text="All API endpoints require Bearer token auth. Tokens must carry user ID and role claims, expire after 1 hour, and support refresh."'
# → prints: 2

# Capture the ID for subsequent use
NEW_ID=$(plan create 1 'title="Task: DB schema", text="The auth system needs persistent storage for users, hashed credentials, and active sessions. Must support email-based lookup and session expiry."')
```

### Creating with multiline body

Use `text=file("-")` to pipe body content directly into `create`:

```bash
plan create 'title="Task: Migrate to PostgreSQL", text=file("-")' <<'EOF'
The app currently uses SQLite which cannot handle concurrent writes under
load. PostgreSQL supports row-level locking, JSONB columns for flexible
metadata, and has better tooling for production backups and monitoring.
EOF
```

For passing the whole expression via stdin:

```bash
echo 'title="Simple task"' | plan create -
```

### Creating a full hierarchy in one session

```bash
# Use ; to batch operations (single file read/write)
plan create 'title="Epic: Payments"' \; \
    create 'title="Epic: Notifications"'
```

For deep hierarchies, create parents first, capture IDs, then create children:

```bash
EPIC=$(plan create 'title="Epic: Search"')
plan create $EPIC 'title="Task: Indexing pipeline"'
plan create $EPIC 'title="Task: Query parser"'
plan create $EPIC 'title="Task: Results ranking"'
```

### Setting up dependencies

```bash
# Ticket 5 is blocked by ticket 3
plan 5 link blocked 3
# Automatically creates the reverse link: blocking:#5 on ticket #3

# Related tickets
plan 5 link related 7
```

### Ordering tickets

```bash
plan 4 move first        # Do first
plan 5 move after 4      # Do second
plan 6 move last         # Do last
```

---

## Modifying Tickets

All modifications use non-interactive commands. Do not use `edit` without `--start`.

### Setting attributes (`mod` / `~`)

```bash
# Single attribute
plan 5 ~ 'set(assignee="alice")'

# Multiple attributes at once
plan 5 ~ 'set(status="in-progress", assignee="agent-1")'

# Set title
plan 5 ~ 'set(title="Revised: Fix login with OAuth")'
```

### Appending text (`add`)

```bash
# Append to ticket body
plan 5 add "Found that the root cause is a race condition in session refresh."

# Append from stdin (useful for long text or multiline)
echo "After investigation, the root cause is a race condition between
concurrent session refresh requests. The refresh token gets invalidated
by the first request before the second one can use it." | plan 5 add -
```

### Setting body text via `mod`

When you need to set (not append) the body, use `~ 'set(text=...)'`:

```bash
plan 5 ~ 'set(text="New complete description of this ticket.")'

# From a file
plan 5 ~ 'set(text=file("specs/ticket-5-spec.txt"))'

# From stdin
echo "New body" | plan 5 ~ 'set(text=file("-"))'
```

### Replacing body text (`replace` — last resort)

Use `replace --force` only when you must discard the entire existing body and
neither `add` nor `~ 'set(text=...)'` is appropriate (e.g. overwriting a
project section from a file):

```bash
plan 5 replace --force "Completely rewritten content."
plan 5 replace --force @specs/ticket-5-spec.txt
```

### Deleting attributes

```bash
plan 5 ~ 'delete("assignee")'
plan 5 ~ 'delete("estimate", "sprint")'
```

### Managing links

```bash
# Add link
plan 5 link blocked 3

# Remove link
plan 5 unlink blocked 3
```

Link types and their automatic mirrors:

| Link | Mirror |
|---|---|
| `blocked` | `blocking` |
| `blocking` | `blocked` |
| `related` | `related` |
| `derived` | `derived-from` |
| `derived-from` | `derived` |
| `caused` | `caused-by` |
| `caused-by` | `caused` |

### Adding comments

```bash
# Add a comment
plan 5 comment add "Started implementation, ETA 30 minutes."

# Reply to a comment
plan 5:comment:1 add "Hit a snag with the OAuth flow, investigating."
```

### Multiple modifications in one call

```bash
# List of operations
plan 5 ~ '[set(assignee="alice"), link("blocked", 3)]'

# Batch via semicolons
plan 5 ~ 'set(status="in-progress")' \; 6 ~ 'set(status="open")'
```

---

## Non-Interactive Editing

Use `edit --start` / `edit --accept` when you need to restructure a ticket's
markdown body or rearrange a subtree — cases where `add` and `~ 'set(text=...)'`
are insufficient (e.g. reordering existing content, adding child tickets inline).

### Workflow

```bash
# 1. Export the ticket to a temp file
plan edit --start 5

# 2. Edit the file at the path printed by --start
#    (e.g. .PLAN-edit-5-a3f9.md next to .PLAN.md)

# 3. Apply and clean up
plan edit --accept 5
# Or, if only one edit is in flight:
plan edit --accept
```

To export a ticket and all its children in one file:

```bash
plan edit --start 5 -r
# ... edit the file ...
plan edit --accept 5
```

### Aborting and restarting

```bash
# Discard the edit without applying
plan edit --abort 5

# Start over (abort existing + export fresh)
plan edit --restart 5
```

`--abort` and `--restart` are idempotent — they succeed even if no edit is in flight.

### Error: hash mismatch

If `--accept` fails with a hash mismatch error, the base content changed since
`--start` was called. Use `--restart` to get a fresh export:

```bash
plan edit --restart 5
# ... re-edit the file ...
plan edit --accept 5
```

---

## Querying and Filtering

### Query expressions

Query expressions are Python expressions evaluated per ticket. All ticket
attributes are available as variables. Missing attributes resolve to `""`
(empty string). Non-numeric arguments are implicit `-q` queries, so the
`-q` flag is usually unnecessary.

```bash
# Open tickets
plan 'status == "open"' list

# Assigned open tickets
plan 'status == "open" and assignee != ""' list

# Assigned to a specific agent
plan 'assignee == "agent-1"' list

# Unassigned and open
plan 'status == "open" and assignee == ""' list

# Tickets containing a keyword
plan '"auth" in title.lower()' list

# Leaf tickets only (no subtasks)
plan 'not children' list

# Tickets with open blockers
plan '"blocked" in links' list

# Tickets with a custom attribute
plan 'sprint == "5"' list
```

### The `--format` flag

Use `--format` to control output. The expression is evaluated per ticket and
its result is printed as a line.

```bash
# ID only (one per line, useful for scripting)
plan 'status == "open"' --format 'str(id)' list

# ID and title
plan --format 'f"{indent}#{id} {title}"' list

# Full status board
plan --format 'f"#{id:>4} [{status:^11}] @{assignee:>8} {title:.50}"' list

# CSV-like
plan --format 'f"{id},{status},{assignee},{title}"' list
```

### Combining queries and `--format`

```bash
# Open tasks assigned to me, formatted for parsing
plan 'assignee == "agent-1" and status == "in-progress"' \
  --format 'f"{indent}#{id} {title}"' list
```

### Search shortcuts

```bash
plan list --title "login"       # Title substring
plan list --text "OAuth"        # Title + body substring
plan list --assignee agent-1    # By attribute value
```

---

## Bulk Operations

### Apply to all descendants

The `-r` flag combined with a filter expression on verbs operates on entire subtrees.

```bash
# Close all open subtasks of epic #1
plan 1 -r 'status == "open"' close done

# Assign all open tickets under #1
plan 1 -r 'status == "open"' ~ 'set(assignee="agent-1")'

# Add a comment to all in-progress tickets under #1
plan 1 -r 'status == "in-progress"' comment add "Sprint 5 checkpoint."

# Reassign all tickets from one agent to another
plan 1 -r 'assignee == "agent-1"' ~ 'set(assignee="agent-2")'
```

### Multiple IDs in one command

```bash
# Close several specific tickets
plan 5 7 9 close

# Modify several tickets
plan 5 7 9 ~ 'set(assignee="alice")'
```

### Semicolon batching

Multiple operations in one invocation — one file read, one file write:

```bash
plan 5 ~ 'set(status="done")' \; \
    6 ~ 'set(status="in-progress")' \; \
    create 1 'title="Follow-up"'
```

---

## Multi-Agent Coordination

### Assignment pattern

Use `assignee` to claim tickets and avoid conflicts:

```bash
# Agent checks for available work
plan list ready --format 'f"{indent}#{id} @{assignee} {title}"'
plan list order --format 'f"{indent}#{id} @{assignee} {title}"'

# Agent claims an unassigned task
plan N ~ 'set(status="in-progress", assignee="agent-1")'

# Other agents skip assigned tickets
plan 'assignee == ""' list ready
plan 'assignee == ""' list order
```

### Progress reporting

Agents should log their progress as comments:

```bash
plan N comment add "Starting work on JWT middleware."
plan N comment add "Implemented token generation, testing now."
plan N comment add "All tests pass. Closing."
plan N close
```

### Handoff between agents

```bash
# Agent-1 finishes part of the work and hands off
plan N comment add "Schema created. Frontend agent can proceed with forms."
plan N ~ 'set(assignee="agent-2")'

# Agent-2 picks it up
plan N comment add "Picking up from agent-1's schema work."
```

### Blocking and unblocking

```bash
# Agent discovers a blocker
BLOCKER=$(plan create 1 'title="Bug: Token expiry not handled", text="When a JWT expires mid-session, the API returns a raw 401 instead of triggering a token refresh. Users are logged out without warning after the 1-hour token lifetime, even if they are actively using the app."')
plan N link blocked $BLOCKER
plan N comment add "Blocked by #$BLOCKER — token expiry issue."

# Another agent resolves the blocker
plan $BLOCKER close
# Now ticket N will appear in 'list ready' again
```

### Role-based work selection

If the project defines roles, an agent should read its role first:

```bash
# Read role instructions
plan project role:executor

# Then filter tasks accordingly
plan 'assignee == "" or assignee == "executor"' list ready
plan 'assignee == "" or assignee == "executor"' list order
```

---

## Piping and Stdin Patterns

### Creating tickets from generated text

```bash
# From a variable
TITLE="Fix CORS headers"
plan create "title=\"$TITLE\""

# Title + body in one call via heredoc
plan create 'title="Task: Rate limiting", text=file("-")' <<'EOF'
Public API endpoints are vulnerable to abuse. We need per-client rate
limiting to protect backend resources and ensure fair usage. The limits
should be configurable per endpoint and return standard 429 responses
with Retry-After headers.
EOF

# Appending to an existing ticket via heredoc
plan 5 add - <<'EOF'
Discovered that the upstream load balancer already tracks client IPs,
so we can use X-Forwarded-For instead of implementing our own tracking.
EOF
```

### Reading ticket content into a variable

```bash
# Capture ticket body
BODY=$(plan 5)

# Capture a specific attribute
STATUS=$(plan 5 attr status)
ASSIGNEE=$(plan 5 attr assignee)

# Capture list of IDs
OPEN_IDS=$(plan 'status == "open"' --format 'str(id)' list)
```

### Setting body from a file

```bash
# Generated spec → ticket body
plan 5 ~ 'set(text=file("generated-spec.md"))'

# Append a file's content to the body instead
plan 5 add @generated-notes.md
```

### Chaining commands with shell

```bash
# Find and close all done tickets that are still marked open
for ID in $(plan 'status == "open" and not children' --format 'str(id)' list); do
    plan $ID close
done
```

---

## Error Handling

`plan` exits with code 0 on success, non-zero on error. Errors go to stderr.

### Common errors and their meaning

| Error | Cause | Fix |
|---|---|---|
| `Error: file not found` | No plan file discovered | Set `PLAN_MD` or use `-f` |
| `Error: #N not found` | Ticket ID doesn't exist | Check with `plan list` |
| `Error: replace requires --force` | Missing `--force` flag | Add `--force`, or prefer `add` / `~ 'set(...)'` |
| `Error: create requires title attribute` | No `title` in create expr | Add `title="..."` |
| `Error: multiple verbs` | Two verbs in one request | Use `;` to separate |
| `Error: #N has children` | Deleting ticket with subtasks | Use `plan N -r del` |

### Defensive patterns

```bash
# Check before acting
if plan 5 attr status 2>/dev/null; then
    plan 5 status in-progress
else
    echo "Ticket 5 not found" >&2
fi

# Validate the file
plan check
```

---

## Recipes

### Recipe: Bootstrap a project plan from a spec

```bash
# 1. Set up the project description
plan project description add @PROJECT_SPEC.md

# 2. Write agent instructions
plan project agents add - <<'EOF'
Before starting a ticket, read it fully and check `plan project building`
and `plan project testing`. Run the full test suite before and after every
change. Use snake_case for all Python identifiers. Never modify files
under vendor/. Log what you did in the ticket body with `plan N add`.
Close tickets only after tests pass.
EOF

# 3. Create epics
E1=$(plan create 'title="Epic: Core API", text="Backend service exposing RESTful endpoints for all client applications. Handles authentication, data validation, and business logic. Must be stateless and horizontally scalable."')
E2=$(plan create 'title="Epic: Frontend", text="Single-page React application providing the end-user interface. Communicates exclusively through the Core API. Must work on mobile viewports."')
E3=$(plan create 'title="Epic: Infrastructure", text="Automated build, test, and deployment pipeline. Local dev environment must be one-command setup. Staging must mirror production topology."')

# 4. Break epics into tasks — body describes context, not steps
plan create $E1 'title="Task: Database schema", text="The API needs persistent storage for users, sessions, roles, and audit logs. Schema must support soft deletes and have indexes for common query patterns."'
plan create $E1 'title="Task: REST endpoints", text="Standard CRUD endpoints for all domain resources. Must follow REST conventions, return appropriate HTTP status codes, and support pagination on list endpoints."'
plan create $E1 'title="Task: Auth middleware", text="Every API request except /health and /login must carry a valid JWT. The middleware must verify token signatures, check expiry, and inject the authenticated user into the request context."'

plan create $E2 'title="Task: Component library", text="Reusable UI primitives shared across all pages. Must follow the existing design system tokens for spacing, color, and typography. Needs Storybook entries for visual review."'
plan create $E2 'title="Task: Login page", text="First screen users see. Must handle email/password authentication, show field-level validation errors, and redirect to the dashboard on success."'

plan create $E3 'title="Task: CI pipeline", text="Every push to main must be automatically linted, tested, and built. PRs must not be mergeable until the pipeline passes. Build artifacts must be tagged with the commit SHA."'
plan create $E3 'title="Task: Docker setup", text="Developers need a one-command local environment that runs the app, database, and any background workers. Must use the same base images as production."'

# 5. Set dependencies
plan 8 link blocked 6            # Login page needs auth middleware

# 6. Order tasks within epics
plan 4 move first
plan 6 move after 4
plan 5 move after 6

# 7. Validate
plan check
```

### Recipe: Agent work session

```bash
# Read context — agents section first
plan project agents
plan project description
plan project building
plan project testing

# Find work
TASK_LINE=$(plan list order --format 'f"{indent}#{id} {title}"' -n 1)
TASK_ID=$(echo "$TASK_LINE" | grep -o '#[0-9]*' | tr -d '#')

# Read the task
plan $TASK_ID
plan -p $TASK_ID

# Claim it
plan $TASK_ID ~ 'set(status="in-progress", assignee="agent")'

# ... do the work ...

# Log what was done
plan $TASK_ID add "Implemented in commit abc123. All tests pass."

# Close
plan $TASK_ID close
```

### Recipe: Status report

```bash
echo "=== OPEN ==="
plan 'status == "open"' --format 'f"  #{id} {title}"' list

echo "=== IN PROGRESS ==="
plan 'status == "in-progress"' --format 'f"  #{id} @{assignee} {title}"' list

echo "=== BLOCKED ==="
plan '"blocked" in links and status in ("open","in-progress")' \
  --format 'f"  #{id} {title}"' list

echo "=== DONE (recent) ==="
plan 'status == "done"' --format 'f"  #{id} {title}"' list

echo "=== READY ==="
plan list ready --format 'f"  #{id} {title}"'
plan list order --format 'f"  #{id} {title}"'
```

### Recipe: Close an epic bottom-up

```bash
# Close all leaf tasks under epic #1
plan 1 -r 'not children and status in ("open","in-progress")' close done

# Now close the epic itself
plan 1 close
```

### Recipe: Create a ticket with subtasks

Body text describes *what* and *why*. Implementation steps become subtasks.

```bash
# Create the parent task with a descriptive body
ID=$(plan create 'title="Task: Caching layer", text=file("-")' <<'EOF'
Database queries for user profiles account for 60% of API latency.
Adding an in-memory cache at the repository layer would reduce load
on PostgreSQL and bring p95 response times under 50ms. The cache
must be transparent to handlers and automatically invalidated on
writes to maintain consistency.
EOF
)

# Break the work into subtasks
plan create $ID 'title="Subtask: LRU cache module with TTL support"'
plan create $ID 'title="Subtask: Integrate cache into repository layer"'
plan create $ID 'title="Subtask: Write-through invalidation on mutations"'
plan create $ID 'title="Subtask: Cache hit/miss metrics"'
```

### Recipe: Move tickets between epics

```bash
# Move tasks 5, 6, 7 from epic #1 to epic #2
plan 5 move 2
plan 6 move 2
plan 7 move 2

# Reorder within the new parent
plan 5 move first
plan 6 move after 5
plan 7 move after 6
```

### Recipe: Daily standup query

```bash
# What did agent-1 close recently?
plan 'assignee == "agent-1" and status == "done"' \
  --format 'f"  #{id} {title}"' list

# What is agent-1 working on?
plan 'assignee == "agent-1" and status == "in-progress"' \
  --format 'f"  #{id} {title}"' list

# What can agent-1 pick up next?
plan 'assignee == "" or assignee == "agent-1"' list ready \
  --format 'f"  #{id} {title}"'
plan 'assignee == "" or assignee == "agent-1"' list order \
  --format 'f"  #{id} {title}"'
```
