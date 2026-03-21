# DSL Expression Language

[Home](README.md) | [CLI Reference](cli-reference.md) | [Querying](querying.md)

The DSL (Domain-Specific Language) is used in three contexts:

1. **Filters** (`-q EXPR` or implicit) — evaluated per-ticket, return truthy to include
2. **Formatting** (`--format EXPR`) — evaluated per-ticket, result is printed
3. **Modification** (`mod` / `~`) — apply mutations to ticket attributes

Expressions are Python syntax evaluated in a sandboxed namespace.

## Namespace Variables

These variables are available in all expression contexts:

| Variable | Type | Description |
|----------|------|-------------|
| `id` | `int` | Ticket number |
| `title` | `str` | Ticket title |
| `text` | `str` | Body text |
| `status` | `str` | Status value (empty string if unset = "open") |
| `is_open` | `bool` | Status is active or deferred (not closed) |
| `is_active` | `bool` | Status is active (not deferred or closed) |
| `ready` | `bool` | `is_active` AND no active blockers or children |
| `assignee` | `str` | Assignee name |
| `depth` | `int` | Nesting level (0 = top-level) |
| `indent` | `str` | `"  " * depth` (for formatting) |
| `parent` | `int` | Parent ticket ID (0 if root) |
| `children` | `list` | Child ticket IDs |
| `links` | `dict` | Link dict, e.g. `{"blocked": [3]}` |
| `created` | `str` | Creation timestamp |
| `updated` | `str` | Last update timestamp |
| `move` | — | Ephemeral positioning attribute (mod only) |

Any custom attribute on the ticket is also available. Missing attributes resolve to `""`.

### Status Categories

| Category | Statuses |
|----------|----------|
| Active | `open`, `in-progress`, `assigned`, `blocked`, `reviewing`, `testing` |
| Deferred | `backlog`, `deferred`, `future`, `someday`, `wishlist`, `paused`, `on-hold` |
| Closed | `done`, `duplicate`, `wont-do`, or any other value |

## Helper Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `parent_of(N)` | `int` | Parent ticket ID of #N (0 if root) |
| `is_descendant_of(P)` | `bool` | True if current ticket is a descendant of #P |
| `is_descendant_of(P, C)` | `bool` | True if #C is a descendant of #P |
| `children_of(N)` | `list` | Direct child ticket IDs of #N (N=0 for top-level) |
| `children_of(N, True)` | `list` | All descendant IDs recursively |
| `children()` | `list` | Direct children of current ticket |
| `children(recursive=True)` | `list` | All descendants recursively |

## Builtins

```
len, any, all, min, max, sorted, int, str, float, True, False, None
```

The `file(path)` function reads a file and returns its contents as a string.

## Filter Expressions

Used with `-q` or as implicit arguments. Evaluated per-ticket; truthy return includes the ticket.

```bash
# Status filters
plan 'status == "open"' list
plan is_open list
plan is_active list
plan ready list

# Assignee
plan 'assignee == "alice"' list
plan 'assignee != ""' list                # Assigned to anyone
plan 'assignee == ""' list                # Unassigned

# Title/text search
plan '"auth" in title.lower()' list
plan '"database" in text' list

# Hierarchy
plan 'depth == 0' list                    # Top-level only
plan 'depth > 0' list                     # All subtasks
plan 'parent == 1' list                   # Direct children of #1
plan 'is_descendant_of(1)' list           # All descendants of #1
plan 'len(children) == 0' list            # Leaf tickets (no children)

# Links
plan 'links.get("blocked")' list          # Has blocked links
plan '3 in links.get("blocked", [])' list # Blocked by #3

# Combining
plan 'is_active and assignee == "alice"' list
plan 'status == "open" or status == "in-progress"' list
plan 'ready and depth == 0' list
```

### Boolean Return

If the expression returns a boolean, it filters the current selection:

```bash
plan 1 -r 'is_active' list    # Active descendants of #1
```

### List/Int Return

If the expression returns a list or int, it selects tickets by ID:

```bash
plan -q 'children_of(1)' list   # Children of #1 (returns list of IDs)
```

## Format Expressions

Used with `--format`. Evaluated per-ticket; result is converted to string and printed.

```bash
# f-string formatting
plan list --format 'f"{indent}#{id} [{status}] {title}"'
plan list --format 'f"{id},{status},{assignee},{title}"'

# Simple value
plan list --format 'id'
plan list --format 'title'
plan list --format 'status'

# Computed values
plan list --format 'f"#{id} ({len(children)} children)"'
plan list --format 'f"{indent}#{id} {title} [{assignee or \"unassigned\"}]"'
```

## Modification Expressions

Used with the `mod` / `~` verb. These are the only expressions that can change ticket data.

### `set(key=val, ...)`

Set attribute values:

```bash
plan 5 ~ 'set(status="in-progress")'
plan 5 ~ 'set(assignee="alice")'
plan 5 ~ 'set(status="in-progress", assignee="alice")'
plan 5 ~ 'set(title="New title")'
plan 5 ~ 'set(text="New body text")'
```

Special keys:
- `title` — changes the ticket title
- `text` — replaces the body text
- `move` — repositions the ticket: `"first"`, `"last"`, `"first N"`, `"last N"`, `"before N"`, `"after N"`

```bash
plan 5 ~ 'set(move="first")'           # First among siblings
plan 5 ~ 'set(move="first 3")'         # First child of #3
plan 5 ~ 'set(move="after 7")'         # After sibling #7
```

### `add(key=val, ...)`

Append to composite attributes:

```bash
plan 5 ~ 'add(text="Extra paragraph")'       # Append to body
plan 5 ~ 'add(links="blocked:#3")'            # Add a link
plan 5 ~ 'add(comment="Review note")'         # Create a new comment
```

### `delete(name, ...)`

Remove named attributes:

```bash
plan 5 ~ 'delete("estimate")'
plan 5 ~ 'delete("assignee", "estimate")'
```

### `link(type, id)` / `unlink(type, id)`

Manage links with automatic mirror maintenance:

```bash
plan 5 ~ 'link("blocked", 3)'       # #5 blocked by #3 (adds blocking:#5 to #3)
plan 5 ~ 'unlink("blocked", 3)'     # Remove the blocked link
```

### Composition

Chain multiple mutations with commas:

```bash
plan 5 ~ 'set(status="done"), add(comment="Completed")'
plan 5 ~ 'set(assignee="bob"), link("blocked", 3)'
```

### Bulk Modifications

Apply to multiple tickets:

```bash
plan 1 -r ~ 'set(status="in-progress")'                    # All descendants
plan 1 -r 'assignee == ""' ~ 'set(assignee="bob")'          # Unassigned only
plan 1 -r 'status == "open"' ~ 'set(status="in-progress")'  # Open tickets only
```

## See Also

- [Querying and Filtering](querying.md) — practical filtering examples
- [CLI Reference](cli-reference.md) — verb and flag reference
- [Examples](examples.md) — cookbook of DSL examples
