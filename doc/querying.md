# Querying and Filtering

[Home](README.md) | [CLI Reference](cli-reference.md) | [DSL](dsl.md)

## Basic Listing

```bash
plan list                    # All tickets (tree view)
plan 5 list                  # Ticket #5 in list format
plan 5 -r list               # Ticket #5 and all descendants
```

Output shows tree indentation with status and links:

```
#1 [open] Set up authentication
  #3 [in-progress] Implement JWT tokens <blocked:#2>
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
#5 [done] Write API docs
```

## Status Filters

Three built-in status filters are available as implicit expressions:

```bash
plan list is_open             # Active + deferred (not closed)
plan list is_active           # Active only (not deferred, not closed)
plan list ready               # Active + no active blockers or children
```

| Filter | Active | Deferred | Closed |
|--------|--------|----------|--------|
| `is_open` | included | included | excluded |
| `is_active` | included | excluded | excluded |
| `ready` | included* | excluded | excluded |

*`ready` additionally requires no active blockers and no active children.

## Execution Order

```bash
plan list order
```

Shows tickets in the order they should be worked on:

- Dependencies (blockers) come before blocked tickets
- Parent tickets come after their children
- Tickets ready for work appear first

Output:
```
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
  #3 [in-progress] Implement JWT tokens <blocked:#2>
#1 [open] Set up authentication
```

## The `next` Shortcut

```bash
plan next                    # Next ticket to work on
plan next -n 3               # Next 3 tickets
plan next 'assignee == ""'   # Next unassigned ticket
```

`next` is equivalent to `list order -n 1`.

## Filter Expressions

Non-numeric arguments are automatically promoted to `-q` filter expressions:

```bash
plan 'status == "open"' list
plan 'assignee == "alice"' list
plan 'status == "in-progress" and assignee != ""' list
plan 'depth == 0' list                         # Top-level only
plan '"auth" in title.lower()' list            # Title contains "auth"
plan 'any(c == "blocked" for c in links)' list # Has any blocked link
```

These are Python expressions evaluated per-ticket in a [sandboxed namespace](dsl.md).

## Title, Text, and Attribute Filters

```bash
plan list --title "auth"              # Tickets with "auth" in the title
plan list --text "database"           # Tickets with "database" in title or body
plan list --attr 'assignee == "alice"'  # Filter by attribute expression
```

## Custom Formatting

```bash
plan list --format 'f"{indent}#{id} [{status}] {title}"'
```

Output:
```
#1 | Set up authentication | open | assignee=
#3 | Implement JWT tokens | in-progress | assignee=alice
#4 | Add OAuth2 provider | open | assignee=
#2 | Design database schema | open | assignee=
#5 | Write API docs | backlog | assignee=
```

More format examples:

```bash
# Compact dashboard
plan list --format 'f"{indent}#{id} [{status}] {title}"'

# With assignee
plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'

# Just IDs
plan list --format 'id'

# CSV-like
plan list --format 'f"{id},{status},{assignee},{title}"'
```

The `--format` expression has access to all [DSL namespace variables](dsl.md).

## Recursive Listing

```bash
plan 1 -r list               # Ticket #1 and all its descendants
plan -r list                  # Same as plan list (all tickets are included)
```

## Parent Context

The `-p` flag adds ancestor tickets to the result, providing tree context:

```bash
plan -p 3                    # Show #3 with its ancestor chain
plan -p is_open -r list      # Open tickets with their ancestor path
```

This is useful when filtering deep tickets — `-p` shows where they sit in the hierarchy.

## Limiting Results

```bash
plan list -n 5               # First 5 tickets
plan list order -n 3         # Top 3 in execution order
plan next -n 3               # Next 3 actionable tickets
```

## Combining Filters

Filters and selectors form a left-to-right pipeline:

```bash
# Start with ticket #1's subtree, then filter to open ones
plan 1 -r is_open list

# Start with all tickets, filter to alice's, then list
plan 'assignee == "alice"' list

# Multiple conditions
plan 'is_active and assignee == "alice"' list

# Selector + filter
plan 1 -r 'status == "in-progress"' list
```

### Pipeline Order Matters

```bash
plan 1 -r is_open list    # Start with #1's subtree → filter to open
plan is_open 1 -r list    # Start with all open → add #1's subtree
```

If the first step is a selector (like `1`), the initial set is empty.
If the first step is a filter (like `is_open`), the initial set is all tickets.

## Viewing Individual Tickets

```bash
plan 5                       # Show ticket #5 (full content)
plan 5 get                   # Same as above (get is default)
plan 5 -r get                # Show #5 and full subtree
```

Output:
```
## Task: Implement JWT tokens {#3}

    updated: 2026-03-20 22:43:47 UTC
    status: in-progress
    created: 2026-03-20 22:22:54 UTC
    links: blocked:#2
    assignee: alice
```

## Project Sections

```bash
plan project                  # List all project sections
plan project description      # Show description section
plan project metadata         # Show metadata section
```

## See Also

- [DSL Expression Language](dsl.md) — full expression reference
- [Working with Tickets](tickets.md) — ticket operations
- [Examples](examples.md) — more filtering and formatting examples
