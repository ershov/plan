# Claude Code Integration

[Home](README.md) | [Installation](installation.md) | [Workflows](workflows.md)

`plan` includes a Claude Code plugin that teaches Claude how to use the tool for structured task planning and multi-agent coordination, replacing the built-in TodoWrite/TaskCreate system.

## Overview

After installation (`plan install local` or `plan install user`), Claude Code gets:

| Component | What it does |
|-----------|-------------|
| **3 skills** | Teach Claude when and how to use `plan` for different scenarios |
| **SessionStart hook** | Shows current ticket status when a Claude Code session starts |
| **CLAUDE.md instructions** | Enforce the `plan` workflow over TodoWrite/TaskCreate |

## What Changes for Claude

Once installed, Claude Code will:

- Use `plan create` instead of `TodoWrite` for task tracking
- Use `plan list` instead of `TaskList` for viewing progress
- Use `plan N status in-progress` / `plan N close` instead of `TaskUpdate`
- Automatically see current ticket status at the start of each session
- Break down complex tasks into hierarchical ticket structures
- Track progress with status transitions and comments

## Skills

### planning-with-plan

**Trigger:** Multi-step implementation tasks (3+ steps), feature development, any work that would normally use TodoWrite or a markdown checklist.

**What Claude does:**

1. Breaks the task into tickets using `plan create` (often with bulk creation)
2. Works through tickets in order, updating status as it goes
3. Reports progress using `plan list`
4. Adapts the plan as new work surfaces

**Quick reference commands Claude uses:**

```bash
plan create 'title="Step name"'              # Create task
plan create PARENT 'title="Subtask"'          # Create subtask
plan list                                     # View all tickets
plan list ready                               # Actionable tickets
plan list order                               # Execution order
plan N status in-progress                     # Start work
plan N close                                  # Complete work
plan N comment add "Note"                     # Add note
```

### dispatch-with-plan

**Trigger:** When dispatching subagents via the Agent tool to work on tickets.

**What Claude does:**

1. Gets the next ticket: `plan list order -n 1`
2. Reads the ticket content
3. Dispatches a worker subagent with the ticket content in the prompt
4. Processes the return and moves to the next ticket

The leader (Claude) does not implement tickets itself — it delegates to subagent workers. Each worker:
- Marks the ticket `in-progress`
- Does the implementation work
- Adds comments about findings
- Closes the ticket when done

### team-with-plan

**Trigger:** Coordinating 2+ named subagents or a team of agents on implementation work.

**What Claude does:**

As the coordinator:
- Creates tickets with assignees: `plan create 'title="Task", assignee="agent-name"'`
- Monitors progress: `plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'`
- Adds feedback via comments
- Does not implement anything itself

Each team agent:
- Finds its tasks: `plan 'assignee == "my-name" and is_open' list`
- Works through assigned tickets
- Reports via comments

## SessionStart Hook

When a Claude Code session starts in a project with a `.PLAN.md` file, a hook script runs automatically. It locates the plan file and shows the current ticket status:

```
Plan file: /path/to/project/.PLAN.md

Current tickets:
#1 [open] Set up authentication
  #3 [in-progress] Implement JWT tokens <blocked:#2>
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
```

This gives Claude immediate context about the project's current state.

## CLAUDE.md Instructions

The installer appends a task tracking section to your project's `CLAUDE.md` with instructions that tell Claude Code to:

- Use `plan` for all task tracking (not TodoWrite or TaskCreate)
- Break tasks into tickets before starting work
- Track status transitions (`in-progress` → `close`)
- Add notes via comments
- Show progress with formatted listing
- Provide subagent instructions when dispatching workers

### What Gets Added

```markdown
## Task tracking

Use the `plan` CLI for ALL task tracking. Do not use TodoWrite or TaskCreate.

### Before starting work
- Break the task into tickets
- Create tickets in preferred execution order
- Put details in each subtask body, not as a TODO list in the parent

### While working
- Before starting: plan N status in-progress
- After completing: plan N close
- Add notes: plan N comment add "What happened"
- Check next: plan list ready or plan list order

### For subagents / team workers
- Find tasks: plan 'assignee == "YOUR-NAME" and is_open' list
- Start work: plan N status in-progress
- Complete: plan N close
```

## Plugin Directory Structure

After installation, the plugin lives at `.claude/plugins/claude-plan/` (local) or `~/.claude/plugins/claude-plan/` (user):

```
claude-plan/
├── .claude-plugin/
│   └── plugin.json              # Plugin metadata
├── hooks/
│   ├── hooks.json               # SessionStart hook config
│   └── scripts/
│       └── load-plan-context.sh # Script that shows ticket status
└── skills/
    ├── planning-with-plan/
    │   └── SKILL.md             # Solo planning skill
    ├── dispatch-with-plan/
    │   └── SKILL.md             # Subagent dispatch skill
    └── team-with-plan/
        └── SKILL.md             # Team coordination skill
```

## Equivalence Table

| Old Approach | plan Equivalent |
|-------------|-----------------|
| `TodoWrite(subject="...")` | `plan create 'title="..."'` |
| `TaskUpdate(id, status="in_progress")` | `plan N status in-progress` |
| `TaskUpdate(id, status="completed")` | `plan N close` |
| `TaskList()` | `plan list --format 'f"{indent}#{id} [{status}] {title}"'` |
| `TaskCreate(subject, agent)` | `plan create 'title="...", assignee="agent"'` |
| Ad-hoc markdown checklist | `plan create -` with bulk markdown |

## See Also

- [Installation](installation.md) — how to install the plugin
- [Workflows](workflows.md) — workflow patterns for solo and team use
- [Working with Tickets](tickets.md) — ticket operations reference
