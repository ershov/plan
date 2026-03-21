# CLI Reference

[Home](README.md) | [Commands In-Depth](commands.md) | [DSL](dsl.md)

## General Syntax

```
plan <command> [args] [flags]
plan [selectors] [verb] [args] [flags] [; ...]
```

Selectors and verbs can appear in either order:

```bash
plan 5 list       # selector first
plan list 5       # verb first — same result
```

Multiple requests can be chained with `;`:

```bash
plan 5 status done ";" 6 status in-progress
```

## Commands

Commands are standalone operations — they must be the first word.

| Command | Syntax | Description |
|---------|--------|-------------|
| `create` | `create [parent] EXPR \| - \| -e` | Create a new ticket |
| `edit` | `edit ID [-r]` | Edit ticket in `$EDITOR` |
| `check` | `check` | Validate document structure |
| `fix` | `fix` | Auto-repair document |
| `resolve` | `resolve` | Resolve git merge conflicts |
| `install` | `install local\|user` | Install binary, plugin, CLAUDE.md |
| `uninstall` | `uninstall local\|user` | Remove installation |
| `help` | `help [TOPIC]` | Show help (`help dsl` for expressions) |

See [Commands In-Depth](commands.md) for detailed documentation of each command.

## Verbs

Verbs describe what to do with selected targets. At most one verb per request. Default is `get`.

| Verb | Syntax | Description |
|------|--------|-------------|
| `get` | `get` | Print content (default if no verb given) |
| `list` / `ls` | `list [order]` | List tickets with tree indentation |
| `replace` | `replace --force TEXT` | Replace body text (requires `--force`) |
| `add` / `+` | `add TEXT` | Smart append to body |
| `del` | `del` | Delete target (use `-r` for tickets with children) |
| `mod` / `~` | `mod EXPR` / `~ EXPR` | Modify via [DSL expression](dsl.md) |
| `link` | `link [TYPE] ID` | Create link (default: `related`) |
| `unlink` | `unlink [TYPE\|all] ID` | Remove link (default: `all`) |
| `status` | `status STATUS` | Set ticket status |
| `close` | `close [RESOLUTION]` | Close ticket (default: `done`) |
| `reopen` | `reopen` | Reopen ticket (set status to `open`) |
| `move` | `move DIRECTION [DEST]` | Reorder or reparent tickets |
| `next` | `next` | Next ticket in execution order (`list order -n 1`) |

### Text Input Methods

Several verbs accept text input (`add`, `replace`, `create`). Text can come from:

- **Literal string**: `plan 5 add "Some text"`
- **File reference**: `plan 5 add @notes.txt`
- **Stdin**: `echo "text" | plan 5 add -`
- **Editor**: `plan 5 add -e` (opens `$EDITOR`)

## Selectors

Selectors narrow which targets a verb acts on.

| Selector | Syntax | Description |
|----------|--------|-------------|
| Ticket ID | `N` | Select ticket by bare integer ID |
| Node ID | `id NAME` | Select any node by its `#id` |
| Comment | `comment` | Narrow to ticket's comments |
| Attribute | `attr NAME` | Narrow to a specific attribute |
| Project | `project [SECTION]` | Select project-level section |

### Selector Pipeline

Selectors and filters form a left-to-right pipeline:

- If the first step is a **selector**, the initial set is empty
- If the first step is a **filter**, the initial set is all tickets
- Order matters: `plan 1 -r is_open` is not the same as `plan is_open 1 -r`

Multiple ticket IDs can be selected: `plan 5 6 7 close`

## Flags

### Global Flags

| Flag | Description |
|------|-------------|
| `-f`, `--file FILE` | Use specific plan file (must appear before `;` in pipelines) |
| `-h`, `--help` | Show help |

### Selector/Filter Flags

| Flag | Description |
|------|-------------|
| `-r`, `--recursive` | Include all descendant tickets |
| `-p`, `--parent` | Include all ancestor tickets in results |
| `-q EXPR` | Query expression (usually implicit — see below) |
| `--title PAT` | Filter by title substring |
| `--text PAT` | Filter by body text substring |
| `--attr EXPR` | Filter by attribute expression |

### Output Flags

| Flag | Description |
|------|-------------|
| `--format EXPR` | Format output with [DSL expression](dsl.md) |
| `-n N` | Limit output to first N results |
| `--quiet` | Suppress output (useful in scripts) |

### Action Flags

| Flag | Description |
|------|-------------|
| `--force` | Required for `replace` verb |
| `-e`, `--edit` | Open `$EDITOR` for text input |

## Implicit Query Promotion

Non-numeric arguments that aren't recognized as verbs or keywords are automatically promoted to `-q` filter expressions:

```bash
plan is_open list           # same as: plan -q is_open list
plan 'status == "done"' list  # same as: plan -q 'status == "done"' list
plan ready list             # same as: plan -q ready list
```

This makes common filters concise and natural.

## `-p` Flag Behavior

`-p` is a flag, not a pipeline step. It always adds ancestors to the final result regardless of position:

```bash
plan -p 3        # same as: plan 3 -p
```

Combined with `-r` and filters, `-p` preserves tree context:

```bash
plan -p is_open -r list    # open tickets with their ancestor chain
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PLAN_MD` | Path to plan file (overrides auto-discovery) |
| `EDITOR` | Editor for `-e` flag and `edit` command |

## See Also

- [Commands In-Depth](commands.md) — detailed guide for each command
- [Working with Tickets](tickets.md) — ticket lifecycle and operations
- [DSL Expression Language](dsl.md) — expressions for `-q`, `--format`, and `mod`
- [Examples](examples.md) — practical examples
