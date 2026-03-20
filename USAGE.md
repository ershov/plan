# Plan — Usage Guide

`plan` is a markdown-based ticket tracker that lives inside your git repository.
All project state — tickets, hierarchy, comments, metadata — is stored in a single
`.PLAN.md` file, versioned alongside your code.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Bootstrapping a Project](#bootstrapping-a-project)
3. [File Structure](#file-structure)
4. [Ticket Lifecycle](#ticket-lifecycle)
5. [Planning Work — Epics, Tasks, Subtasks](#planning-work)
6. [Day-to-Day Workflows](#day-to-day-workflows)
7. [Querying and Reporting](#querying-and-reporting)
8. [Collaboration Patterns](#collaboration-patterns)
9. [Best Practices](#best-practices)

---

## Quick Start

```bash
# 1. Create the plan file with your first ticket
plan --file .PLAN.md create -e

# 2. Set up project description
plan edit description

# 3. Start working
plan 1 status in-progress

# 4. See what's there
plan list
```

After the initial setup, `plan` auto-discovers `.PLAN.md` at the git root — no
`--file` flag needed.

---

## Bootstrapping a Project

### Step 1: Initialize the plan file

Create `.PLAN.md` at the root of your git repository:

```bash
plan --file .PLAN.md create -e
```

### Step 2: Write the project description

The project description is the single source of truth for anyone (human or AI)
picking up the project. Put everything a newcomer needs here.

```bash
plan edit description
```

**What to include:** goal, architecture, tech stack, build/test instructions,
key design decisions, conventions.

### Step 3: Define project sections

Sections are individually retrievable via `plan project <section>`:

```bash
plan edit building               # How to build
plan edit testing                # How to run tests
plan edit design                 # Conventions and patterns
```

Read them back:

```bash
plan project building
plan project testing
```

### Step 4: Write agent instructions (optional)

If AI agents will work on the project, add concise rules:

```bash
plan edit agents
```

Include: workflow rules, code conventions, guardrails, communication norms.

### Step 5: Commit

```bash
git add .PLAN.md
git commit -m "Initialize project plan"
```

---

## File Structure

The `.PLAN.md` file is a structured markdown document using nested bullet lists:

```markdown
# Project: My App {#project}

## Metadata {#metadata}

    next_id: 5

## Description {#description}

Goal, architecture, key design decisions...

## Tickets {#tickets}

* ## Ticket: Epic: User Authentication {#1}

      status: in-progress
      assignee: alice

  Implement the full auth system.

  * ## Ticket: Task: Login endpoint {#2}

        status: open
        links: blocked:#3

    POST /api/login with JWT.

  * ## Ticket: Task: Database schema {#3}

        status: done

    Create users table with email, password_hash, created_at.
```

**Key rules:**

- IDs (`{#N}`) are global, unique, auto-incrementing integers.
- Hierarchy is expressed by indentation (nested bullet lists).
- Attributes are indented 4 extra spaces below the ticket header.
- Ticket ordering within a level is determined by file position.

---

## Ticket Lifecycle

### Statuses

| Status | Meaning |
|---|---|
| `open` | Not started, available for work |
| `planned` | Acknowledged, scheduled for future |
| `in-progress` | Actively being worked on |
| `done` | Completed successfully |
| `won't do` | Intentionally skipped |
| *(any text)* | Custom closed resolution (e.g. `"duplicate"`, `"obsolete"`) |

Open statuses: `open`, `in-progress`, `planned`, `assigned`.
Any other value is treated as a closed/resolved state.

### Status transitions

```bash
plan 5 status in-progress       # Start work
plan 5 close                    # Close (default: "done")
plan 5 close "duplicate"        # Close with custom resolution
plan 5 reopen                   # Reopen
```

---

## Planning Work

The recommended hierarchy has three levels. Deeper nesting is supported but
rarely needed.

### Epics → Tasks → Subtasks

```bash
# Epics (top-level)
plan create 'title="Epic: User Authentication"'

# Tasks (children of epics)
plan create 1 'title="Task: Design auth database schema"'
plan create 1 'title="Task: Implement JWT middleware"'

# Subtasks (optional — break down large tasks)
plan create 2 'title="Subtask: Create users table migration"'
```

### Dependencies and ordering

```bash
# "Login endpoint" is blocked by "Database schema"
plan 5 link blocked 6
# This automatically adds "blocking:#5" to ticket #6

# Control execution order within a parent
plan 5 move first
plan 6 move after 5
plan 7 move last
```

---

## Day-to-Day Workflows

### Starting your day

```bash
plan list                        # All tickets
plan list ready                  # Ready for work (no blockers, children done)
plan list order                  # Execution order (topological sort)
plan next                        # Single highest-priority ready ticket
```

### Picking up a task

```bash
plan 5                           # Read the task
plan -p 5 get                    # Read with ancestor context
plan 5 status in-progress        # Start work
```

### Working on a task

```bash
plan 5 add "Implementation notes."
plan 5 comment add "Found edge case, investigating."
plan edit 5                      # Full edit in $EDITOR
```

### Finishing a task

```bash
plan 5 close                     # Close with default "done"
plan 5 close "won't do"          # Close with custom resolution

# Close all open subtasks of an epic at once
plan 1 -r is_open close done
```

### Reorganizing

```bash
plan 8 move 2                    # Move #8 under #2
plan 8 move before 9             # Move before a sibling

plan 12 del                      # Delete a leaf ticket
plan 12 -r del                   # Delete ticket and all children
```

Note: deleting a ticket with children requires `-r`. Without it, `plan`
refuses to avoid accidental data loss.

---

## Querying and Reporting

### Selection pipeline

Selectors and filters are processed left-to-right. Selectors add to the
working set, filters narrow it. Order matters:

```bash
# Filter all tickets to open ones
plan is_open list

# Select #1, expand to descendants, then filter to open
plan 1 -r is_open list

# Select descendants of #1, add #1 back
plan is_descendant_of(1) 1 list
```

### Filtering with `-q`

The `-q` flag takes a Python expression evaluated against each ticket.
Available: `id`, `title`, `status`, `is_open`, `is_active`, `ready`,
`assignee`, `depth`, `parent`, `children`, `links`, plus custom attrs.

```bash
plan 'assignee == "alice"' list
plan '"auth" in title.lower()' list
plan '"blocked" in links' list
plan 'not children' list                 # Leaf tickets only
```

### Custom formatting

```bash
plan --format 'f"{indent}#{id} [{status}] {title}"' list
plan is_open --format 'f"@{assignee} #{id} {title}"' list
```

### Bulk operations

```bash
# Close all open children of epic #1
plan 1 -r is_open close done

# Set assignee on all open subtasks
plan 1 -r is_open ~ 'set(assignee="alice")'

# Multiple operations in one invocation (one file read/write)
plan 5 close \; 6 status in-progress \; create 1 'title="Follow-up"'
```

For DSL details: `plan help dsl`

---

## Collaboration Patterns

### Working with AI agents

The plan file doubles as a task queue. See [USAGE-AGENTS.md](USAGE-AGENTS.md)
for the full agent guide. The basic loop:

```bash
plan list ready                  # Find work
plan 5 status in-progress        # Claim it
plan 5                           # Read it
# ... do the work ...
plan 5 close                     # Done
```

### Merge conflicts

When `git merge` or `git rebase` creates conflicts in `.PLAN.md`:

```bash
plan resolve
```

This resolves conflicts intelligently: timestamps pick the newer value,
IDs are merged correctly, structure is preserved.

### Validation

```bash
plan check                       # Validate (duplicate IDs, broken links, etc.)
plan fix                         # Auto-repair structural issues
```

---

## Best Practices

### Project setup

1. **Write the description first.** Before creating tickets, document the
   project in `plan edit description`. This is the context window for everyone.

2. **Add build/test sections.** `plan edit building` and `plan edit testing`
   so anyone can get started.

3. **Commit `.PLAN.md` with code.** Version it, review it in PRs.

### Ticket hygiene

4. **Three-level hierarchy.** Epics > Tasks > Subtasks. Resist going deeper.

5. **One deliverable per task.** Completable in a single focused session.

6. **Write enough in the body.** Motivation, acceptance criteria, implementation
   hints. The ticket body is the spec.

7. **Link dependencies explicitly.** `plan 5 link blocked 6` so that
   `plan list ready` and `plan list order` work correctly.

### During development

8. **Update status promptly.** `in-progress` when you start, `close` when done.

9. **Add notes as you go.** `plan N add "..."` for notes,
   `plan N comment add "..."` for discussions.

10. **Create tickets for discoveries.** Found a bug? Create a ticket.

11. **Use `plan next` as your driver.** Shows the highest-priority ready task.
