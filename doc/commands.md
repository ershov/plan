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

## merge — Structure-Aware Three-Way Merge

```bash
plan merge <branch> [--renumber to|from] [--prefer to|from] \
                    [--stage|--no-stage] [--no-edit]
plan merge <branch> --check     # dry run: report conflict count, write nothing
plan merge --resolve            # apply the edited .reject and finish
plan merge --abort              # discard an in-progress merge
```

Merges the plan file from `<branch>` into the current branch using a structural three-way merge (base = merge-base, `to` = current branch, `from` = `<branch>`). The two sides are **`to`** (the side merged *into* — your current branch, kept canonical) and **`from`** (the side merged *from* — `<branch>`). Tickets and comments are merged by identity (ID), per field, not by file position — so it reconciles changes a line-based merge cannot, including tickets created independently on both branches that happen to share an ID (those are renumbered and every reference is rewritten).

The auto-merged result is always written to `.PLAN.md` and is always valid: at each unresolved conflict the **`to`** (your) side is kept. If genuine conflicts remain, a `<planfile>.reject` sidecar is written and the command exits non-zero.

| Flag | Description |
|------|-------------|
| `--renumber to\|from` | Which side's colliding new IDs get reassigned (default: `from`) |
| `--prefer to\|from` | Auto-resolve **all** conflicts to one side; no `.reject` |
| `--stage` / `--no-stage` | Mark the plan file unmerged in the git index; standalone default is file-only |
| `--no-edit` | Do not auto-launch `$EDITOR` on the `.reject` |

**Resolving the `.reject` file.** Each conflict block shows `--- to (<branch>) ---` and `--- from (<branch>) ---`. Keep exactly one side (delete the other, or delete a side's indicator line and leave only its content). Do not edit the content — only choose a side. A side whose content is `<DELETED>` removes the entry. Then run `plan merge --resolve`.

**Git merge driver.** `plan install local` configures a git merge driver for the repo, so a plain `git merge` / `git rebase` / `cherry-pick` / `stash pop` reconciles `.PLAN.md` automatically. On conflict git leaves the file unmerged plus a `.reject`; finish with `plan merge --resolve` then `git add`. (`merge-driver` is the internal entry git calls — you do not run it directly.)

**Exit codes:** `0` = clean / resolved; `1` = conflicts need action (or `--check` found conflicts); `2` = error.

See [Merging Branches](workflows.md#git-integration-workflow) for the full workflow.

## resolve — Recover Raw Conflict Markers

```bash
plan resolve
```

Best-effort recovery for a plan file that already contains raw git conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) — i.e. a merge done **without** the git merge driver. It reconstructs both sides from the markers and runs a structure-aware merge (three-way if diff3 `|||||||` base markers are present, otherwise a lossier two-way merge that cannot distinguish add from delete). The markers are removed and the auto-merged result written, defaulting unresolved conflicts to your side; if conflicts remain, a `.reject` is written so you can finish with `plan merge --resolve`.

This is the degraded cousin of [`merge`](#merge--structure-aware-three-way-merge) — prefer `plan merge <branch>`, or install the merge driver with `plan install local` so merges reconcile automatically.

## install — Install Binary, Plugin, and CLAUDE.md

```bash
plan install local    # Into current directory / project
plan install user     # Into ~/.local/bin and ~/.claude
plan install git      # ONLY the git merge driver, in the current repo
```

See [Installation](installation.md) for full details on what gets installed. For `local`, `install` also configures the [git merge driver](#merge--structure-aware-three-way-merge) for the repo (adds `.PLAN.md merge=plan` to `.gitattributes`, sets `merge.plan.driver` in git config, and ignores the `.reject` sidecar) so plain `git merge`/`git rebase` reconcile `.PLAN.md` automatically.

`plan install git` configures **only** that merge driver — no binary, plugin, or `CLAUDE.md`/`AGENTS.md`. Use it when `plan` is already on your PATH and you just want a repo's `.PLAN.md` to merge structurally. It must be run inside a git repository; outside one it exits with an error.

## uninstall — Remove Installation

```bash
plan uninstall local
plan uninstall user
plan uninstall git    # Remove only the repo's git merge driver config
```

Removes the binary, plugin directory, plugin registration from `settings.json`, and the task tracking section from `CLAUDE.md`. For `local` and `git`, it also removes the git merge driver config (the `.gitattributes` line, the `merge.plan` git config section, and the `.reject` `.gitignore` line). `plan uninstall git` removes **only** that driver config.

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
