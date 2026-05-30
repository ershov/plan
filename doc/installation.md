# Installation

[Home](README.md)

## Prerequisites

- **Python 3.9+** (standard library only — no pip packages needed)
- **git** (optional, but recommended — enables automatic `.PLAN.md` discovery at the repo root)

## Installation Methods

### Method 1: Manual Copy

Copy `plan.py` anywhere on your `PATH` and make it executable:

```bash
cp plan.py ~/bin/plan
chmod +x ~/bin/plan
```

Or symlink it:

```bash
ln -s /path/to/plan.py ~/bin/plan
```

This gives you the CLI tool but not the Claude Code plugin.

### Method 2: Per-Project Install (`plan install local`)

Installs everything into the current directory/project:

```bash
python3 plan.py install local
```

This creates:

| Component | Location | Purpose |
|-----------|----------|---------|
| Binary | `./plan` | CLI executable (skipped if `plan` is already on PATH) |
| Plugin | `.claude/plugins/claude-plan/` | Claude Code skills and hooks |
| CLAUDE.md | `./CLAUDE.md` | Appends task tracking instructions (skipped if already present) |
| Git merge driver | repo `.gitattributes`, git config, `.gitignore` | Reconciles `.PLAN.md` automatically on `git merge`/`rebase` |

Use this method when you want `plan` integrated into a specific project's Claude Code setup.

### Method 3: User-Wide Install (`plan install user`)

Installs globally for your user account:

```bash
python3 plan.py install user
```

This creates:

| Component | Location | Purpose |
|-----------|----------|---------|
| Binary | `~/.local/bin/plan` | CLI executable (skipped if `plan` is already on PATH) |
| Plugin | `~/.claude/plugins/claude-plan/` | Claude Code skills and hooks |
| CLAUDE.md | `~/.claude/CLAUDE.md` | Appends task tracking instructions (skipped if already present) |

Use this method when you want `plan` available in all projects with Claude Code.

### Method 4: Merge Driver Only (`plan install git`)

Configures **only** the structure-aware git merge driver in the current repository — no binary, plugin, or `CLAUDE.md`/`AGENTS.md`:

```bash
python3 plan.py install git
```

This adds:

| Component | Location | Purpose |
|-----------|----------|---------|
| Git merge driver | repo `.gitattributes`, git config, `.gitignore` | Reconciles `.PLAN.md` automatically on `git merge`/`rebase` |

Use this method when `plan` is already on your PATH (or installed user-wide) and you just want a particular repo's `.PLAN.md` to merge structurally. It must be run **inside a git repository**; outside one it exits with an error. `plan uninstall git` removes the same three driver artifacts.

## What Gets Installed

### Binary

A copy of `plan.py` named `plan`. If `plan` is already found on your `PATH`, the binary copy is skipped.

### Claude Code Plugin

A plugin directory with:

- **3 skills** that teach Claude Code how to use `plan`:
  - `planning-with-plan` — solo task planning and execution
  - `dispatch-with-plan` — leader dispatching subagent workers
  - `team-with-plan` — multi-agent coordination with assignees
- **SessionStart hook** — automatically shows current ticket status when a Claude Code session starts

The plugin is registered in the corresponding `settings.json`.

### CLAUDE.md Instructions

A section is appended to your `CLAUDE.md` with task tracking instructions. This tells Claude Code to use `plan` instead of TodoWrite/TaskCreate for task management. A marker prevents duplicate appends on re-install.

### Git Merge Driver (`local` and `git`)

`plan install local` and `plan install git` configure a structure-aware git merge driver for the repo so that `git merge` / `git rebase` / `cherry-pick` / `stash pop` reconcile `.PLAN.md` automatically (by ticket/comment ID, not line position). (`plan install git` configures **only** this driver; `plan install user` is global and does not touch any repo.) It is idempotent and adds:

- `.PLAN.md merge=plan` to `.gitattributes`
- `merge.plan.driver` (= `plan merge-driver %O %A %B %P`) to the repo's git config
- `.PLAN.md.reject` to `.gitignore`

On conflict, git leaves `.PLAN.md` merged-to-your-side plus a `.PLAN.md.reject`; finish with `plan merge --resolve` then `git add .PLAN.md`. See [Git integration](workflows.md#git-integration-workflow) and the [`merge` command](commands.md#merge--structure-aware-three-way-merge).

## Verifying Installation

After installation, verify everything works:

```bash
# Check the binary
plan help

# Check file discovery (from a git repo)
plan list
# If no .PLAN.md exists yet, this will show an error — that's fine

# Create a test ticket to bootstrap
plan create 'title="Test ticket"'
plan list
plan 1 del
```

**Restart Claude Code** after installing the plugin so the skills and hooks take effect.

## Uninstallation

```bash
plan uninstall local   # Remove project-local installation
plan uninstall user    # Remove user-wide installation
plan uninstall git     # Remove only the repo's git merge driver config
```

This removes the binary, plugin directory, plugin registration from `settings.json`, and the task tracking section from `CLAUDE.md`. For `local` and `git`, it also removes the git merge driver config (the `.gitattributes` line, the `merge.plan` git config section, and the `.reject` `.gitignore` line). `plan uninstall git` removes **only** that driver config and must be run inside a git repository.

## Next Steps

- [Quick Start](quick-start.md) — get started with your first tickets
- [Claude Code Integration](claude-code-integration.md) — learn how the plugin works
