# Quick Start

[Home](README.md) | [Installation](installation.md) | [CLI Reference](cli-reference.md)

This tutorial walks you through the basics of `plan` in 5 minutes. All examples use real output.

## 1. Create Your First Ticket

Run `plan create` from inside a git repository. If no `.PLAN.md` exists, it will be created automatically:

```bash
plan create 'title="Set up authentication", status="open"'
```

Output:
```
1
```

The number `1` is the assigned ticket ID.

## 2. Create More Tickets

```bash
plan create 'title="Design database schema"'
plan create 1 'title="Implement JWT tokens"'    # child of #1
plan create 1 'title="Add OAuth2 provider"'      # child of #1
plan create 'title="Write API docs", status="backlog"'
```

Output (one ID per command):
```
2
3
4
5
```

## 3. List All Tickets

```bash
plan list
```

Output:
```
#1 [open] Set up authentication
  #3 [open] Implement JWT tokens
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema
#5 [backlog] Write API docs
```

Indentation shows the parent-child hierarchy. Tickets `#3` and `#4` are children of `#1`.

## 4. View a Ticket

```bash
plan 1
```

Output:
```
## Task: Set up authentication {#1}

    status: open
    updated: 2026-03-20 22:22:38 UTC
    created: 2026-03-20 22:22:38 UTC
```

## 5. Update Status

```bash
plan 3 status in-progress
```

Now list to see the change:

```bash
plan list
```

Output:
```
#1 [open] Set up authentication
  #3 [in-progress] Implement JWT tokens
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema
#5 [backlog] Write API docs
```

## 6. Add a Dependency Link

Mark ticket `#3` as blocked by `#2`:

```bash
plan 3 link blocked 2
```

```bash
plan list
```

Output:
```
#1 [open] Set up authentication
  #3 [in-progress] Implement JWT tokens <blocked:#2>
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
#5 [backlog] Write API docs
```

Notice that the mirror link `blocking:#3` was automatically added to `#2`.

## 7. Add a Comment

```bash
plan 5 comment add "Needs review from team lead"
```

View the comments:

```bash
plan 5 comment
```

Output:
```
* ## Comments {#5:comments}

  * Needs review from team lead {#5:comment:6}
```

## 8. Assign a Ticket

```bash
plan 3 mod 'set(assignee="alice")'
```

View the updated ticket:

```bash
plan 3
```

Output:
```
## Task: Implement JWT tokens {#3}

    updated: 2026-03-20 22:43:47 UTC
    status: in-progress
    created: 2026-03-20 22:22:54 UTC
    links: blocked:#2
    assignee: alice
```

## 9. Filter Tickets

Show only tickets assigned to alice:

```bash
plan 'assignee == "alice"' list
```

Output:
```
  #3 [in-progress] Implement JWT tokens <blocked:#2>
```

Show tickets ready for work (active, with no active blockers or children):

```bash
plan list ready
```

Output:
```
#4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
```

## 10. Close a Ticket

```bash
plan 5 close
```

```bash
plan list
```

Output:
```
#1 [open] Set up authentication
  #3 [in-progress] Implement JWT tokens <blocked:#2>
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
#5 [done] Write API docs
```

## 11. View Execution Order

`plan list order` shows tickets in the order they should be worked on — respecting dependencies and hierarchy:

```bash
plan list order
```

Output:
```
  #4 [open] Add OAuth2 provider
#2 [open] Design database schema <blocking:#3>
  #3 [in-progress] Implement JWT tokens <blocked:#2>
#1 [open] Set up authentication
```

`#2` appears before `#3` because `#3` is blocked by `#2`.

## 12. Get the Next Ticket

```bash
plan next
```

Output:
```
  #4 [open] Add OAuth2 provider
```

This is a shortcut for `plan list order -n 1`.

## What's Next

- [Working with Tickets](tickets.md) — statuses, links, comments, bulk creation
- [Querying and Filtering](querying.md) — advanced filtering and formatting
- [CLI Reference](cli-reference.md) — complete command reference
- [Claude Code Integration](claude-code-integration.md) — use with AI agents
