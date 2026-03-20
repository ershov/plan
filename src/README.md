# src/

Source files for the `plan` CLI tool. Numbered `.py` files are concatenated by `build.sh` to produce the single-file `plan.py` executable.

## Python source files

| File | Description |
|------|-------------|
| `010-preambula.py` | Module docstring and standard library imports. |
| `020-constants.py` | Constants: safe builtins for DSL evaluation, link mirror mappings, and status category sets. |
| `030-utils.py` | Utility functions: `DefaultNamespace`, file reading, timestamp generation, link parsing, indentation helpers, and ancestor traversal. |
| `040-data-model.py` | Core data model: `Node`, `Section`, `Comment`, `Comments`, `Ticket`, `ChildrenAccessor`, and `Project` classes representing the hierarchical document structure. |
| `050-patterns.py` | Regular expressions for parsing ticket headers, comments, sections, and attributes from `.PLAN.md` files. |
| `060-parser.py` | Multi-pass parser that converts markdown text into a `Project` object, handling nested tickets, comments, attributes, and section boundaries. |
| `070-bulk.py` | Bulk ticket creation: scans headers, allocates IDs, substitutes placeholder references, and fills in default attributes. |
| `080-serialize.py` | Serializes a `Project` back to markdown with dirty-tracking for efficient round-trip editing. |
| `090-dsl-sandbox.py` | DSL evaluation sandbox for filter, format, and modification expressions with a safe namespace exposing ticket attributes and helper functions. |
| `100-rank.py` | Ticket ordering: internal rank calculation, positional expressions (`first`/`last`/`before`/`after`), and reparenting logic. |
| `110-link.py` | Link management with automatic mirror link creation (e.g. `blocked`/`blocking`, `related`, `derived`). |
| `120-cli.py` | CLI argument parser: selectors, verbs, flags, and a left-to-right selection pipeline. Parses multi-step requests separated by semicolons. |
| `130-file.py` | Plan file discovery with precedence: `--file` flag, `PLAN_MD` env var, `.PLAN.md` at git root, walk up from cwd. |
| `140-handlers.py` | Handler functions implementing verbs (`list`, `get`, `replace`, `add`, `delete`, `mod`, `link`, `status`, `close`, `reopen`, `move`) and commands (`create`, `edit`). |
| `150-dispatch.py` | Command dispatcher: routes parsed requests to handlers, executes the selection pipeline, and invokes verb handlers. |
| `170-install.py` | Installation/uninstallation: copies binary to `~/.local/bin`, creates Claude Code plugin structure, registers in `settings.json`, updates `CLAUDE.md`. |
| `180-main.py` | Entry point: handles install/uninstall, parses arguments, discovers file, acquires locks, bootstraps projects, dispatches requests, and writes output. |

## Build scripts

Files suffixed with `+` are executable build scripts run during `build.sh`, not included in the final `plan.py`:

| File | Description |
|------|-------------|
| `135-help+.py` | Generates help text constants from `.txt` files in `src/help/` for embedding in the binary. |
| `160-install-files+.py` | Embeds plugin files and `CLAUDE.md` into a `_PLUGIN_FILES` dict and related constants for `plan install`. |

## Directories

### `help/`

Help text source files loaded at build time:

- `general.txt` — Main help: usage, file discovery, selectors, verbs, command examples.
- `dsl.txt` — DSL reference: filter expressions, format strings, mutator functions.
- `commands/*.txt` — Per-command help files (one `.txt` per verb), auto-loaded into the `COMMAND_HELP` dict.

### `claude-template/`

Template for the Claude Code plugin installed by `plan install`:

- `plugins/claude-plan/.claude-plugin/plugin.json` — Plugin metadata.
- `plugins/claude-plan/hooks/hooks.json` — Lifecycle hook config running `load-plan-context.sh` on session start.
- `plugins/claude-plan/hooks/scripts/load-plan-context.sh` — Discovers the plan file and displays ticket status at session start.
- `plugins/claude-plan/skills/planning-with-plan/SKILL.md` — Skill for breaking down tasks into a ticket hierarchy.
- `plugins/claude-plan/skills/dispatch-with-plan/SKILL.md` — Skill for a leader coordinating subagent workers on plan tickets.
- `plugins/claude-plan/skills/team-with-plan/SKILL.md` — Skill for coordinating multiple named agents with assignees.

## `CLAUDE.md`

Project-specific instructions for using `plan` as the task tracker, with skill references and guidelines for breaking down work and team coordination.
