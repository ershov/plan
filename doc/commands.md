# Commands In-Depth

[Home](README.md) | [CLI Reference](cli-reference.md) | [Working with Tickets](tickets.md)

Commands are standalone operations that must be the first word in the invocation.

## create — Create a New Ticket

```bash
plan create [parent] EXPR
plan create [parent] -
plan create [parent] -e
```

### Expression Syntax

Create a ticket with keyword arguments evaluated via `set()`:

```bash
plan create 'title="Fix login bug"'
plan create 'title="Urgent task", status="in-progress"'
plan create 5 'title="Subtask under #5"'
```

The `title` is required. Other attributes are optional.

### Editor Mode

Open `$EDITOR` with a template:

```bash
plan create -e                          # Create top-level ticket
plan create 5 -e                        # Create child of #5
plan create -e 'title="Pre-filled"'     # Open editor with title pre-set
```

### Stdin Mode

Read from stdin (same format as the editor template):

```bash
echo '## My task' | plan create -
```

### Bulk Creation

When stdin or editor input contains `* ##` headers, tickets are created in bulk from the markdown hierarchy:

```bash
plan create - <<'EOF'
* ## Epic: Auth
  Auth system implementation.
  * ## Task: JWT middleware
    Implement JWT validation.
  * ## Task: OAuth2 provider
    Add OAuth2 support.
* ## Epic: Database
  Schema and migrations.
EOF
```

Output:
```
1
2
3
4
```

### Placeholder Cross-References

Use `{#placeholder}` IDs for cross-references between new tickets in bulk creation:

```bash
plan create - <<'EOF'
* ## Task: Set up database {#db}
  Configure the database.
* ## Task: Build API {#api}
      links: blocked:#db
  Build the REST API layer.
* ## Task: Frontend integration
      links: blocked:#api
  Connect frontend to the API.
EOF
```

Placeholders are resolved to real IDs after all tickets are created. The resulting tickets will have proper numeric IDs and working links.

### Positioning

The `move` attribute controls where the new ticket is placed:

```bash
plan create 'title="First task", move="first"'     # First among siblings
plan create 'title="Under #3", move="first 3"'     # First child of #3
plan create 'title="After #5", move="after 5"'     # After sibling #5
```

### Options

| Flag | Description |
|------|-------------|
| `--quiet` | Suppress printing the new ticket ID |

## edit — Edit in External Editor

```bash
plan edit ID          # Edit single ticket
plan edit ID -r       # Edit entire subtree
```

Opens the ticket (or section) in `$EDITOR`. Saves changes back on exit.

```bash
plan edit 5           # Edit ticket #5
plan edit 5 -r        # Edit #5 and all its children
plan edit description  # Edit the project description section
```

When editing recursively (`-r`), you can add new tickets by writing `* ##` headers without an ID or with `{#newXXX}` placeholders. New ticket IDs, timestamps, and status are auto-assigned.

## check — Validate Document

```bash
plan check
```

Checks for structural issues:

- Duplicate IDs
- Broken links (referencing non-existent tickets)
- Orphaned comments
- Other inconsistencies

Exits with a non-zero status if errors are found.

```bash
plan check
# OK: no errors found
```

## fix — Auto-Repair Document

```bash
plan fix
```

Automatically fixes common issues found by `check`:

- Re-assigns duplicate IDs
- Removes broken links
- Repairs other structural problems

## resolve — Resolve Merge Conflicts

```bash
plan resolve
```

Parses git merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in the plan file and produces a clean merged document. Useful when multiple people or agents are editing `.PLAN.md` concurrently.

## install — Install Binary, Plugin, and CLAUDE.md

```bash
plan install local    # Into current directory / project
plan install user     # Into ~/.local/bin and ~/.claude
```

See [Installation](installation.md) for full details on what gets installed.

## uninstall — Remove Installation

```bash
plan uninstall local
plan uninstall user
```

Removes the binary, plugin directory, plugin registration from `settings.json`, and the task tracking section from `CLAUDE.md`.

## help — Show Help

```bash
plan help             # General help
plan help dsl         # DSL expression language
plan help create      # Help on 'create' command
plan help list        # Help on 'list' verb
plan help mod         # Help on 'mod' verb
plan help move        # Help on 'move' verb
plan help link        # Help on 'link' verb
plan help comment     # Help on 'comment' selector
plan help attr        # Help on 'attr' selector
plan help project     # Help on 'project' selector
plan help id          # Help on 'id' selector
plan help install     # Help on installation
```

Every command, verb, and selector has its own help topic.

## See Also

- [CLI Reference](cli-reference.md) — tables of all verbs, selectors, and flags
- [Working with Tickets](tickets.md) — ticket lifecycle and operations
- [Examples](examples.md) — practical examples
