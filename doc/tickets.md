# Working with Tickets

[Home](README.md) | [CLI Reference](cli-reference.md) | [File Format](file-format.md)

## Creating Tickets

### Simple Creation

```bash
plan create 'title="Fix login bug"'                     # Top-level ticket
plan create 5 'title="Implement validation"'             # Child of #5
plan create 'title="Urgent fix", status="in-progress"'   # With status
plan create 'title="Research", assignee="alice"'          # With assignee
```

### Interactive Creation

Open `$EDITOR` to write the ticket:

```bash
plan create -e          # New top-level ticket
plan create 5 -e        # New child of #5
```

### Bulk Creation

Create multiple tickets at once from markdown:

```bash
plan create - <<'EOF'
* ## Epic: Authentication
  Complete auth system.
  * ## Task: JWT tokens
    Implement JWT middleware.
  * ## Task: OAuth2
    Add OAuth2 provider.
* ## Task: Database schema
  Design and implement schema.
EOF
```

Use `{#placeholder}` IDs for dependencies between new tickets:

```bash
plan create - <<'EOF'
* ## Task: Set up database {#db}
* ## Task: Build API
      links: blocked:#db
EOF
```

See [Commands In-Depth: create](commands.md#create--create-a-new-ticket) for all creation options.

## Ticket Types

Tickets have a type prefix in their title:

| Type | Use for |
|------|---------|
| `Task` | Default. General work items |
| `Bug` | Bug reports and fixes |
| `Epic` | Large features containing subtasks |
| `Improvement` | Enhancements to existing features |

Set the type in the title: `plan create 'title="Bug: Login fails on Safari"'`

## Status Lifecycle

### Status Categories

Statuses fall into three categories:

| Category | Statuses | `is_open` | `is_active` |
|----------|----------|-----------|-------------|
| **Active** | `open`, `in-progress`, `assigned`, `blocked`, `reviewing`, `testing` | true | true |
| **Deferred** | `backlog`, `deferred`, `future`, `someday`, `wishlist`, `paused`, `on-hold` | true | false |
| **Closed** | `done`, `duplicate`, `wont-do`, or any other value | false | false |

An unset status (empty string) is treated as `open`.

### Typical Workflow

```
open → in-progress → done
                   → reviewing → done
                   → blocked → in-progress → done
```

### Changing Status

```bash
plan 5 status in-progress    # Set to in-progress
plan 5 status blocked        # Set to blocked
plan 5 close                 # Close as "done" (default)
plan 5 close duplicate       # Close with custom resolution
plan 5 close "won't do"      # Close with quoted resolution
plan 5 reopen                # Reopen (set to "open")
```

### Bulk Status Changes

```bash
plan 5 6 7 status in-progress           # Multiple tickets
plan 1 -r status done                   # Ticket and all descendants
plan 1 -r 'assignee == "alice"' close   # Close alice's subtasks
```

### Computed Properties

These are available in [DSL expressions](dsl.md):

| Property | Meaning |
|----------|---------|
| `is_open` | Status is active or deferred (not closed) |
| `is_active` | Status is active (not deferred, not closed) |
| `ready` | `is_active` AND no active blockers AND no active children |

## Links and Dependencies

### Link Types

| Type | Meaning | Mirror |
|------|---------|--------|
| `blocked` | This ticket is blocked by another | `blocking` |
| `blocking` | This ticket blocks another | `blocked` |
| `related` | Related to another ticket | `related` |
| `derived` | Derived from another ticket | `derived-from` |
| `derived-from` | Source of a derived ticket | `derived` |
| `caused` | Caused by another ticket | `caused-by` |
| `caused-by` | Source of a caused ticket | `caused` |

### Creating Links

```bash
plan 5 link 3                # #5 related to #3 (default type)
plan 5 link blocked 3        # #5 blocked by #3
plan 1 2 3 link blocked 5    # Link #1, #2, #3 as blocked by #5
```

Mirror links are maintained automatically. When you add `blocked:#3` to #5, `blocking:#5` is automatically added to #3.

### Removing Links

```bash
plan 5 unlink 3              # Remove ALL links between #5 and #3
plan 5 unlink blocked 3      # Remove only the "blocked" link to #3
```

### Links and Execution Order

`blocked`/`blocking` links affect execution order in `plan list order`. Blocked tickets appear after their blockers.

`ready` is only true for active tickets that have no active blockers and no active child tickets.

## Comments

### Adding Comments

```bash
plan 5 comment add "Needs review from team lead"
plan 5 comment add -e        # Open editor for comment
```

### Viewing Comments

```bash
plan 5 comment               # List all comments on #5
```

Output:
```
* ## Comments {#5:comments}

  * Needs review from team lead {#5:comment:6}
```

### Recursive Comments

```bash
plan 1 -r comment add "Sprint 5 note"   # Add comment to #1 and all descendants
```

## Modifying Tickets

### Using `mod` / `~`

The `mod` verb (shorthand `~`) lets you modify ticket attributes using [DSL expressions](dsl.md):

```bash
plan 5 ~ 'set(assignee="alice")'                         # Set assignee
plan 5 ~ 'set(status="in-progress", assignee="bob")'     # Set multiple attrs
plan 5 ~ 'add(text="Extra detail")'                       # Append to body
plan 5 ~ 'delete("estimate")'                             # Remove attribute
plan 5 ~ 'link("blocked", 3)'                             # Add link via DSL
```

### Bulk Modifications

```bash
plan 1 -r ~ 'set(status="in-progress")'             # All descendants
plan 1 -r 'assignee == ""' ~ 'set(assignee="bob")'  # Unassigned descendants
```

### Adding Body Text

```bash
plan 5 add "A new paragraph of text"
plan 5 + "Quick note"                    # + is shorthand for add
plan 5 add -e                            # Open editor
```

### Replacing Body Text

```bash
plan 5 replace --force "New body text"
plan 5 replace --force @notes.txt        # From file
```

## Moving and Reordering

### Reorder Among Siblings

```bash
plan 5 move first           # Move to first among current siblings
plan 5 move last            # Move to last among current siblings
```

### Move Relative to Another Ticket

```bash
plan 5 move before 7        # Place #5 before sibling #7
plan 5 move after 7         # Place #5 after sibling #7
```

### Reparent (Move Under a Different Parent)

```bash
plan 5 move first 3         # Move #5 as first child of #3
plan 5 move last 3          # Move #5 as last child of #3
plan 5 move first 0         # Move #5 to root level (first)
```

### Move Multiple Tickets

```bash
plan 5 7 9 move first       # Place 5, 7, 9 first (in selection order)
plan 5 7 move after 3       # Place 5 after 3, then 7 after 5
```

### Move via DSL

```bash
plan 5 ~ 'set(move="first")'
plan 5 ~ 'set(move="first 3")'      # Move under #3 as first child
plan 5 ~ 'set(move="after 3")'      # Move to be a sibling after #3
```

## Deleting Tickets

```bash
plan 5 del                   # Delete ticket (must have no children)
plan 5 -r del                # Delete ticket and all descendants
plan 1 -r 'status == "done"' del   # Delete only closed subtasks
```

Tickets with children require `-r` to prevent accidental deletion of subtrees.

## Attributes

### Reading Attributes

```bash
plan 5 attr status           # Get the status value
plan 5 attr assignee         # Get the assignee
```

### Modifying Attributes

```bash
plan 5 attr status replace --force in-progress
plan 1 -r attr status replace --force open       # Set on all descendants
plan 5 attr estimate del                          # Remove attribute
```

### Custom Attributes

Any key-value pair can be stored as an attribute:

```bash
plan 5 ~ 'set(priority="high", sprint="5")'
plan 5 attr priority         # → high
```

## See Also

- [Querying and Filtering](querying.md) — find and filter tickets
- [DSL Expression Language](dsl.md) — expressions for mod, filters, formats
- [Examples](examples.md) — practical examples
