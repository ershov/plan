# Workflows

[Home](README.md) | [Claude Code Integration](claude-code-integration.md) | [Examples](examples.md)

## Solo Development Workflow

For working through a feature or task on your own:

### 1. Plan the Work

Break the task into tickets:

```bash
plan create - <<'EOF'
* ## Epic: User authentication
  Implement complete auth system.
  * ## Task: Set up database tables
    Create users, sessions, and tokens tables.
  * ## Task: Implement login endpoint
    POST /api/auth/login with JWT response.
  * ## Task: Add middleware
    JWT validation middleware for protected routes.
  * ## Task: Write tests
    Integration tests for auth flow.
EOF
```

### 2. Check the Plan

```bash
plan list
```

```
#1 [open] User authentication
  #2 [open] Set up database tables
  #3 [open] Implement login endpoint
  #4 [open] Add middleware
  #5 [open] Write tests
```

### 3. Work Through Tickets

```bash
plan next                          # What should I work on?
plan 2 status in-progress          # Starting database tables
# ... do the work ...
plan 2 comment add "Added users, sessions, tokens tables"
plan 2 close                       # Done
plan next                          # What's next?
```

### 4. Adapt

If new work surfaces:

```bash
plan create 3 'title="Handle refresh tokens"'  # New subtask under #3
plan 5 close wontfix                            # Skip if unnecessary
```

### 5. Review Progress

```bash
plan list --format 'f"{indent}#{id} [{status}] {title}"'
```

## Multi-Agent Team Workflow

For coordinating multiple Claude Code subagents:

### 1. Create and Assign Tickets

```bash
plan create - <<'EOF'
* ## Task: Backend API
      assignee: backend-agent
  Implement REST endpoints.
* ## Task: Frontend components
      assignee: frontend-agent
  Build React components.
* ## Task: Database migrations
      assignee: backend-agent
  Schema changes and migrations.
EOF
```

### 2. Monitor Progress (as coordinator)

```bash
plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'
```

### 3. Agent Self-Service

Each agent finds and works on its own tickets:

```bash
# Find my work
plan 'assignee == "backend-agent" and is_open' list

# Work on a ticket
plan 1 status in-progress
plan 1 comment add "Implementing endpoints"
plan 1 close

# Check for more
plan list ready
```

## Sprint Planning

### Set Up the Sprint

```bash
plan create - <<'EOF'
* ## Epic: Sprint 5
  * ## Task: Fix login timeout bug
        assignee: alice
  * ## Bug: Cart total rounding error
        assignee: bob
  * ## Improvement: Dashboard performance
        assignee: alice
  * ## Task: Update API docs
        assignee: bob
        status: backlog
EOF
```

### Track Sprint Progress

```bash
# What's in progress?
plan 'status == "in-progress"' list

# What's ready for work?
plan list ready

# Sprint dashboard
plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'

# What's done?
plan 'not is_open' list
```

## Bug Triage

### Log Bugs

```bash
plan create 'title="Bug: Login fails on Safari", assignee="alice"'
plan create 'title="Bug: Cart total off by 1 cent"'
plan create 'title="Bug: Email notifications delayed", status="backlog"'
```

### Triage Unassigned Bugs

```bash
plan '"Bug" in title and assignee == ""' list
```

### Work Through Bugs

```bash
plan next 'type == "Bug"'          # Note: type must be in title for this filter
plan 7 status in-progress
# ... investigate and fix ...
plan 7 comment add "Root cause: Safari cookie SameSite policy"
plan 7 close
```

## Feature Breakdown with Dependencies

### Plan with Dependencies

```bash
plan create - <<'EOF'
* ## Task: Design API schema {#schema}
  Define OpenAPI spec.
* ## Task: Set up database {#db}
      links: blocked:#schema
  Create tables from schema.
* ## Task: Implement endpoints {#api}
      links: blocked:#db
  Build REST handlers.
* ## Task: Write integration tests {#tests}
      links: blocked:#api
  Test the complete flow.
* ## Task: Update documentation
      links: blocked:#api
  API docs and changelog.
EOF
```

### Follow Execution Order

```bash
plan list order
```

The order respects dependencies — `#schema` appears first, then `#db`, then `#api`, etc.

```bash
plan next       # Always gives you the next unblocked ticket
```

## Dependency Management

### Visualize Dependencies

```bash
plan list
```

Links are shown in the listing:

```
#1 [open] Design API schema
#2 [open] Set up database <blocked:#1>
#3 [open] Implement endpoints <blocked:#2>
```

### Add/Remove Dependencies

```bash
plan 5 link blocked 3          # #5 is now blocked by #3
plan 5 unlink blocked 3        # Remove the dependency
```

### Find Blocked Work

```bash
plan 'status == "blocked"' list
plan 'links.get("blocked")' list     # Tickets with any blocked links
```

### Find Ready Work

```bash
plan list ready    # Active, no blockers, no active children
```

## Git Integration Workflow

### Merging a Branch

`.PLAN.md` is a single file, so when two branches both change it the copies must be reconciled. `plan merge` does this structurally (per ticket/comment, by ID), which a line-based merge cannot.

**Automatic (recommended).** Once `plan install local` has configured the git merge driver, a plain merge or rebase reconciles `.PLAN.md` for you:

```bash
plan install local           # one-time: configures the merge driver for the repo
git merge main               # .PLAN.md is merged structurally and automatically
```

If git reports a conflict, it leaves `.PLAN.md` merged-to-your-side plus a `.PLAN.md.reject`; finish with:

```bash
plan merge --resolve         # apply the edits you make to the .reject
git add .PLAN.md             # mark it resolved for git
```

**Manual.** Without the driver (or to merge a branch without a full `git merge`):

```bash
plan merge main              # structure-aware three-way merge into the working tree
plan merge main --check      # or: dry run — report the conflict count, write nothing
```

A clean merge writes the result and exits 0. On conflicts it writes the auto-merged result (your side kept) plus `.PLAN.md.reject`, and exits non-zero.

### Resolving the `.reject` File

When conflicts remain, edit `.PLAN.md.reject`. Each block looks like:

```
<<< PLAN-CONFLICT id=1 type=field node=#12 field=status ...
--- to (feature-x) ---
in-progress
--- from (main) ---
done
>>> END id=1
```

Keep **exactly one** side per block — delete the other side, or delete a side's indicator line and leave only its content. Do not edit the content (only choose a side); a side whose content is `<DELETED>` removes the entry. Then:

```bash
plan merge --resolve         # apply your edits and finish
plan merge --abort           # or: discard the whole merge instead
```

To take one side everywhere without editing, use `--prefer`:

```bash
plan merge main --prefer to      # keep your side on every conflict
plan merge main --prefer from    # take the incoming side on every conflict
```

### Recovering Raw Conflict Markers

If `.PLAN.md` ended up with raw git conflict markers (`<<<<<<<` / `=======` / `>>>>>>>`) — a merge done without the driver — `resolve` is the best-effort recovery:

```bash
plan resolve      # reconstruct both sides from the markers and merge structurally
plan check        # validate the result
plan fix          # auto-repair if needed
```

`resolve` is lossier than `merge` (without a merge-base it cannot always distinguish add from delete). If conflicts remain it writes a `.reject` to finish with `plan merge --resolve`. Prefer `plan merge` or the installed driver.

### Validate Before Committing

```bash
plan check        # Ensure document is valid
# If issues found:
plan fix          # Auto-repair
```

## Using `plan` with Claude Code

### Asking Claude to Plan

```
Implement user authentication with JWT. Use the planning-with-plan skill.
```

Claude will:
1. Create a ticket hierarchy
2. Work through each ticket
3. Report progress

### Asking Claude to Coordinate Agents

```
Use the team-with-plan skill to coordinate agents on implementing the payment system.
```

Claude will:
1. Create tickets with assignees
2. Dispatch subagents
3. Monitor and review progress

See [Claude Code Integration](claude-code-integration.md) for full details.

## See Also

- [Quick Start](quick-start.md) — basic tutorial
- [Working with Tickets](tickets.md) — ticket operations
- [Examples](examples.md) — copy-paste command examples
