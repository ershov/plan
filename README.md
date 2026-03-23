# plan — Markdown Ticket Tracker

A single-file CLI tool that manages tickets in a structured markdown file. Designed to live alongside your code in a git repository.

No external dependencies — only Python 3 standard library.

* [Comprehensive documentation](doc/README.md)

## Concepts

Small and medium-sized projects in git need a lightweight way to track bugs, features, and todo lists without leaving the repository. External issue trackers add friction; plain-text checklists lack structure.

`plan` solves this with a single markdown file that is both **human-readable** and **agent-friendly**. The storage format is easy to understand and edit directly. The CLI provides a convenient interface on top of it.

### Hierarchical tickets

Tickets form a tree. The top level describes high-level objectives in broad terms. Each objective is broken into smaller tasks, and those tasks into individual chunks of work — small enough to complete in one sitting (or one agent context window).

Each ticket carries only the description appropriate for its level — not too detailed, not too vague. Tickets must not contain TODO lists; instead, those items are organized as subtickets. If additional work is discovered during execution, new tickets are created and placed at the right level in the hierarchy.

### Execution order

The natural execution order is **depth-first, post-order** (topological order) — children before parents, left to right. For single-agent or single-person work, tickets are simply executed one at a time in this order. No additional metadata is needed.

For parallel execution (multiple agents or team members), `plan` supports **blocking links** between tickets. For single-agent work, blocking links should not be used — topological order is sufficient.

### Project documentation

Project-wide information — goals, architecture notes, conventions — lives in the **project** section of the plan file, separate from tickets.

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

Download files from https://github.com/ershov/plan/releases/latest

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

## CLI overview

```
plan [selectors] [verb] [args] [; ...]
```

Common operations: `create`, `list`, `get`, `status`, `close`, `move`, `edit`, `link`, `comment add`. Filter with `-q`, recurse with `-r`, format output with `--format`.

See the [CLI reference](doc/cli-reference.md) for the full list of verbs, selectors, flags, and DSL expressions. See [examples](doc/examples.md) for copy-paste recipes.

## Terminal UI

`plan-tui` provides an interactive terminal interface for browsing and managing tickets. Navigate the ticket tree, search, and update statuses without leaving the terminal.

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
