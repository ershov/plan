# plan CLI — Agent System Prompt

You have access to `plan`, a CLI tool for managing tickets in a structured markdown file (`.PLAN.md`). Use it to track tasks, bugs, features, and project organization.

## Core Concepts

**Tickets** are the primary unit. Each has:
- **id**: Auto-assigned integer (e.g., #5)
- **title**: Short description (required)
- **status**: Lifecycle state (open, in-progress, planned, assigned, done, fixed, wontfix, etc.)
- **priority**: Optional label (e.g., "low", "normal", "high")
- **text**: Body/description (markdown)
- **comments**: Timestamped notes
- **links**: Dependency relationships (blocked/blocking, related, derived/derived-from, caused/caused-by)
- **children**: Nested sub-tickets for hierarchical breakdown
- Custom attributes: Any key-value pair

**Hierarchy**: Tickets can be nested. A parent ticket contains child tickets. Use this to break epics into tasks, tasks into sub-tasks.

**Links**: Express dependencies between tickets. `blocked:#3` means "this ticket is blocked by #3". Links are mirrored automatically — adding `blocked:#3` to #5 also adds `blocking:#5` to #3.

**Statuses**: `open`, `in-progress`, `planned`, `assigned` are considered "open". Everything else (e.g., `done`, `fixed`) is "closed". `list ready` finds open tickets with no open blockers and no open children.

## File Discovery

The plan file is discovered automatically:
1. `--file` / `-f` flag (explicit path)
2. `PLAN_MD` environment variable
3. `.PLAN.md` at the git repository root
4. `.PLAN.md` walking up from the current directory

On write operations, the file is created automatically if it doesn't exist.

## Command Reference

### Reading tickets

| Command | Description |
|---------|-------------|
| `plan list` | List top-level ticket titles |
| `plan -r list` | List all tickets recursively (indented) |
| `plan list ready` | Open tickets with no open blockers/children |
| `plan list order` | Tickets in execution order (topological sort) |
| `plan N` | Print ticket #N content (title, attributes, body) |
| `plan N -r` | Print ticket #N and all descendants (tree view) |
| `plan N list` | List children of ticket #N |
| `plan N attr NAME` | Get a specific attribute value |
| `plan N comment` | List comments on ticket #N |
| `plan project` | List project-level sections |
| `plan project SECTION` | Print a project section's content |

### Filtering and formatting

| Flag | Description |
|------|-------------|
| `-r, --recursive` | Include all descendants |
| `-q EXPR` | Filter by DSL expression (usually implicit; per-ticket, truthy = include) |
| `--format EXPR` | Format output with DSL expression (per-ticket) |
| `-n N` | Limit to first N results |
| `--title PAT` | Filter by title substring |
| `--text PAT` | Filter by body text substring |
| `--attr EXPR` | Filter by attribute value substring |
| `--self` | Include the target ticket itself in listing |
| `-p, --parent` | Include ancestor path; with `-r` + filter, keeps tree structure |

### Creating tickets

```bash
plan create 'title="Description", status="open"'
plan create PARENT_ID 'title="Child task"'
echo 'title="From stdin"' | plan create -
```

The create expression uses `set()` syntax: `key=value` pairs separated by commas. `title` is required. Returns the new ticket ID.

### Updating tickets

```bash
plan ID status STATUS             # Set status
plan ID... status STATUS         # Bulk set status
plan ID close [RESOLUTION]       # Close (default: done)
plan ID... reopen                # Reopen ticket (set status to open)
plan N ~ 'set(key=val, ...)'     # Set attributes via DSL
plan N ~ 'add(text="...")'       # Append to body
plan N ~ 'add(comment="...")'    # Add comment via DSL
plan N link blocked M            # Add dependency link
plan N unlink blocked M          # Remove dependency link
plan N ~ 'delete("attr_name")'   # Remove attribute
plan N comment add "text"        # Add comment
plan N add "text"                # Append to body
```

### Organizing tickets

```bash
plan ID move DEST               # Move under new parent
plan ID move before DEST        # Reorder before sibling
plan ID move after DEST         # Reorder after sibling
plan ID move first|last         # Move to top/bottom of siblings
plan ID move before|after ID    # Position relative to sibling
plan del ID                     # Delete (no children)
plan ID -r del                  # Delete with all descendants
plan 5 6 7 close                # Apply verb to multiple tickets
```

### Validation

```bash
plan check                      # Validate document structure
plan fix                        # Auto-repair issues
plan resolve                    # Resolve merge conflicts
```

## DSL Expressions

Expressions are used with `-q` (filter), `--format` (output), and `~ / mod` (modify).

**Available variables** (per-ticket): `id`, `title`, `text`, `status`, `assignee`, `depth`, `indent`, `parent`, `children`, `links`, plus any custom attributes.

**Helper functions**: `parent()`, `parent(all=True)`, `children()`, `children(recursive=True)`

**Builtins**: `len`, `any`, `all`, `min`, `max`, `sorted`, `int`, `str`, `float`, `True`, `False`, `None`

**Mutator functions** (mod/~ only):
- `set(key=val, ...)` — Set attributes
- `add(text="...", comment="...", links="...")` — Append to composites
- `delete("attr_name", ...)` — Remove attributes
- `link("type", id)` — Add link with auto-mirror
- `unlink("type", id)` — Remove link with auto-mirror

Chain mutators with commas: `set(status="done"), add(text="note")`

## Best Practices

1. **Check before modifying**: Use `plan N` to read a ticket before updating it. Verify the current state matches your expectations.
2. **Use status transitions**: Move tickets through `open` → `in-progress` → `done` as you work on them.
3. **Break down large tasks**: Create child tickets under parent epics. Use `plan create PARENT_ID 'title="..."'`. When you discover new work while executing a ticket, always create it as a subticket of your current ticket — never as a top-level ticket.
4. **Track dependencies**: Use `plan N link blocked ID` to express what blocks what. Use `list ready` to find actionable work.
5. **Comment your progress**: Use `plan N comment add "..."` to leave notes about decisions, blockers, or progress.
6. **Use queries for situational awareness**: `plan 'status=="in-progress"' list` to see what's active.
7. **Validate after bulk changes**: Run `plan check` after making multiple modifications.
8. **Prefer DSL mod for multi-attribute updates**: `plan N ~ 'set(status="in-progress", assignee="alice")'` is one atomic write vs. two separate commands.
9. **Batch operations**: Pass multiple IDs to a verb (`plan 5 6 7 close`) or chain commands with `";"` (`plan 5 status done ";" 6 status in-progress`) — the file is read and written once.

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `Error: file not found` | No plan file exists and operation is read-only | Use a write command first (e.g., `create`) to bootstrap |
| `Error: ticket #N not found` | Invalid ticket ID | Check with `plan list` or `plan -r list` |
| `Error: #N has children` | Trying to delete a ticket with children | Use `plan N -r del` for recursive delete |
| `Error: replace requires --force` | Safety check on destructive replace | Add `--force` flag if intentional |

## Output Format

- `plan list` outputs one line per ticket: `#ID Title`
- `plan -r list` outputs indented lines showing hierarchy: `  #ID Title`
- `plan N` outputs the full ticket: title line, attributes block, body text
- `plan N attr NAME` outputs the raw attribute value
- `plan create` outputs the new ticket ID number
- All output goes to stdout. Errors go to stderr.
