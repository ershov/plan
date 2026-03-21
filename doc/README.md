# plan — Markdown Ticket Tracker

**plan** is a single-file CLI tool that manages tickets in a structured markdown file (`.PLAN.md`). It is designed to live alongside your code in a git repository and integrate with [Claude Code](https://claude.ai) agents for structured task planning and multi-agent coordination.

- No external dependencies — Python 3 standard library only
- All data stored in a single `.PLAN.md` file — version-control friendly
- Hierarchical tickets with statuses, comments, links, and custom attributes
- Powerful DSL for filtering, formatting, and modifying tickets
- Built-in Claude Code plugin for AI-assisted planning and team coordination

## Documentation

| Guide | Description |
|-------|-------------|
| [Installation](installation.md) | How to install — manual, per-project, or user-wide |
| [Quick Start](quick-start.md) | Hands-on tutorial to get up and running in 5 minutes |
| [File Format](file-format.md) | Structure of the `.PLAN.md` file |
| [CLI Reference](cli-reference.md) | Complete reference of all commands, verbs, selectors, and flags |
| [Commands In-Depth](commands.md) | Detailed guide for each command |
| [Working with Tickets](tickets.md) | Statuses, links, comments, bulk creation |
| [Querying and Filtering](querying.md) | List, filter, format, and sort tickets |
| [DSL Expression Language](dsl.md) | Filter, format, and modify tickets with expressions |
| [Claude Code Integration](claude-code-integration.md) | Plugin, skills, hooks, and agent workflows |
| [Workflows](workflows.md) | Common workflow patterns for solo and team use |
| [Examples](examples.md) | Cookbook of copy-paste examples |

## Quick Example

```bash
# Create a ticket (auto-creates .PLAN.md)
plan create 'title="Fix login bug"'

# List all tickets
plan list

# Update status and close
plan 1 status in-progress
plan 1 close
```

## Source Code

The tool is built from source files in `src/` and compiled into a single `plan.py` via `build.sh`. See [CLAUDE.md](../CLAUDE.md) for development instructions.

## License

MIT — see [LICENSE](../LICENSE).
