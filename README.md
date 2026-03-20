# plan — Markdown Ticket Tracker

A single-file CLI tool that manages tickets in a structured markdown file. Designed to live alongside your code in a git repository.

No external dependencies — only Python 3 standard library.

## Quick start

```bash
# Create a ticket (bootstraps the plan file automatically)
python3 plan.py create 'title="Fix login bug"'

# List tickets
python3 plan.py list

# View a ticket
python3 plan.py 1

# Update status
python3 plan.py 1 status in-progress

# Close a ticket
python3 plan.py 1 close done
```

## Installation

Copy `plan.py` anywhere on your `PATH`:

```bash
cp plan.py ~/bin/plan
chmod +x ~/bin/plan
```

For a single project (binary + Claude Code plugin + CLAUDE.md in current directory):

```bash
python3 plan.py install local
```

For user-wide installation (binary to `~/.local/bin/`, plugin + CLAUDE.md to `~/.claude/`):

```bash
python3 plan.py install user
```

## File discovery

The plan file is located using this precedence:

1. `--file` / `-f` flag
2. `PLAN_MD` environment variable
3. `.PLAN.md` at the git repository root

## Usage

```
plan [selectors] [verb] [args] [; ...]
plan [verb] [args] [selectors] [; ...]
```

## Examples

```bash
plan list                          # All tickets
plan 5                             # Show ticket #5
plan create -e                     # Create ticket (opens editor)
plan create 5 -e                   # Create child of #5
plan edit 5                        # Edit in $EDITOR
plan 5 status in-progress          # Set status
plan 5 close                       # Close ticket
plan 5 comment add "Note"          # Add comment
plan 5 -r list                     # Ticket #5 and descendants
plan 5 move 3                      # Move #5 under #3
```

### Verbs

Verbs describe *what to do* with a target. At most one verb per request. Default is `get`.

| Verb | Description |
|------|-------------|
| `get` | Print content (default) |
| `list` | List tickets (top-level by default) |
| `replace --force` | Replace content (`text`, `-` for stdin, `@file`) |
| `add` / `+` | Smart append (body, comment, list attr) |
| `del` | Delete target |
| `mod` / `~` | Modify via DSL expression |
| `link [TYPE] ID` | Link to ticket (default: related) |
| `unlink [TYPE\|all] ID` | Remove link (default: all) |
| `status STATUS` | Set ticket status |
| `close [RESOLUTION]` | Close ticket (default: done) |
| `reopen` | Reopen ticket (set status to open) |
| `move` | Reorder (`first`, `last`, `before\|after dest`) or reparent (`dest`, `first\|last dest`) |

### Selectors

Selectors narrow what verbs act on.

| Selector | Description |
|----------|-------------|
| `N` | Select ticket by ID (bare integer) |
| `id NAME` | Select any node by its `#id` (section, ticket, comment) |
| `comment` | Narrow to ticket's comments |
| `attr NAME` | Narrow to a specific attribute |
| `project [section]` | Select project-level section |

### Commands

Commands are standalone operations that don't use the selector/verb system.

| Command | Description |
|---------|-------------|
| `create [parent] EXPR` | Create a new ticket |
| `edit ID [-r]` | Edit ticket in `$EDITOR` (`-r` includes children) |
| `check` | Validate document |
| `fix` | Auto-repair document |
| `resolve` | Resolve git merge conflicts |
| `install local\|user` | Install binary, Claude Code plugin, CLAUDE.md |
| `uninstall local\|user` | Remove binary, plugin, CLAUDE.md section |
| `help` | Show help |

### Flags

| Flag | Description |
|------|-------------|
| `-f`, `--file FILE` | Specify plan file |
| `-r` | Recursive (include all descendants) |
| `-p` | Include ancestor path; with `-r` + filter, keeps tree structure |
| `-n N` | Limit output lines |
| `-q EXPR` | Filter by Python expression (usually implicit) |
| `--format EXPR` | Format output with Python expression |
| `--title TEXT` | Filter by title |
| `--text TEXT` | Filter by title and body |
| `--attr VALUE` | Filter by attribute value |
| `--self` | Include the target ticket in listings |
| `--force` | Required for `replace` |

## DSL expressions

Filter (`-q`), format (`--format`), and modification (`mod`/`~`) expressions are plain Python evaluated in a sandboxed namespace. Each ticket's attributes are available as variables. Missing attributes resolve to `""`.

Available builtins: `len`, `any`, `all`, `min`, `max`, `sorted`, `int`, `str`, `float`, `True`, `False`, `None`.

Modification functions: `set()`, `add()`, `delete()`, `link()`, `unlink()`.

See `AGENTS/DSL.md` for full specification.

## Document structure

The plan file is a structured markdown document:

```markdown
# Project Name {#project}

## Metadata {#metadata}

    next_id: 3

## Description {#description}

Project description here.

## Tickets {#tickets}

* ## Ticket: Task: Title {#1}

      created: 2024-01-01 00:00:00 UTC
      status: open

  Ticket body text.

  * ## Comments {#1:comments}

    * First comment {#1:comment:1}

  * ## Ticket: Task: Subtask {#2}

        status: open
```

All IDs are global and unique. Tickets are hierarchical (nested via indentation). Attributes follow the `{#id}` header line, indented by 4 additional spaces. Links between tickets are automatically interlinked (e.g., adding `blocked:#3` to #5 also adds `blocking:#5` to #3).

## Claude Code plugin

A plugin is included that teaches Claude Code to use `plan` for structured planning and team coordination, replacing ad-hoc markdown checklists and the built-in TodoWrite/TaskList system.

### What it provides

| Skill | Replaces | Purpose |
|-------|----------|---------|
| `claude-plan:planning-with-plan` | `writing-plans` + `executing-plans` + TodoWrite | Solo planning and task execution |
| `claude-plan:team-with-plan` | `subagent-driven-development` + TaskCreate/TaskList | Multi-agent coordination |

### Installation

For a single project (binary + plugin + CLAUDE.md in current directory):

```bash
plan install local
```

For user-wide installation (binary to `~/.local/bin/`, plugin + CLAUDE.md to `~/.claude/`):

```bash
plan install user
```

This installs three things:
- **Binary** — copies `plan` to the target location (skipped if already on PATH)
- **Plugin** — skills and a SessionStart hook that shows ticket status on every session
- **CLAUDE.md** — task tracking instructions that enforce the `plan` workflow

Restart Claude Code after installing.

To uninstall:

```bash
plan uninstall local   # or: plan uninstall user
```

### Usage

Once installed, Claude will automatically use `plan` when:

- You ask it to implement a multi-step feature (activates `planning-with-plan`)
- You ask it to coordinate subagents or a team (activates `team-with-plan`)

You can also invoke skills explicitly:

```
Use the planning-with-plan skill to break this task down.
Use the team-with-plan skill to coordinate agents on this.
```

## Testing

```bash
python3 -m unittest test_plan -v
```

## License

See repository for license information.
