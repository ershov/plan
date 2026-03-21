# The .PLAN.md File Format

[Home](README.md) | [CLI Reference](cli-reference.md) | [Working with Tickets](tickets.md)

## File Discovery

`plan` locates the plan file using this precedence:

1. **`--file` / `-f` flag** — explicit path: `plan -f path/to/.PLAN.md list`
2. **`PLAN_MD` environment variable** — e.g. `export PLAN_MD=~/project/.PLAN.md`
3. **`.PLAN.md` at the git repository root** — found via `git rev-parse --show-toplevel`
4. **Walk-up** — search from the current directory upward for `.PLAN.md`

If no file is found and a write operation is requested (like `create`), the file is created at the git repository root.

## Document Structure

A `.PLAN.md` file is a structured markdown document with anchor IDs (`{#...}`) on every heading:

```markdown
# Project Name {#project}

## Metadata {#metadata}

    next_id: 6

## Description {#description}

Project description goes here.

## Tickets {#tickets}

* ## Ticket: Task: Set up authentication {#1}

      status: open
      created: 2026-03-20 22:22:38 UTC
      updated: 2026-03-20 22:22:38 UTC

  Authentication system for the application.

  * ## Ticket: Task: Implement JWT tokens {#3}

        status: in-progress
        created: 2026-03-20 22:22:54 UTC
        updated: 2026-03-20 22:43:47 UTC
        links: blocked:#2
        assignee: alice

    JWT middleware implementation.

    * ## Comments {#3:comments}

      * Found edge case with token expiry {#3:comment:7}

        Need to handle refresh tokens as well.

  * ## Ticket: Task: Add OAuth2 provider {#4}

        status: open
        created: 2026-03-20 22:22:55 UTC
        updated: 2026-03-20 22:22:55 UTC

* ## Ticket: Task: Design database schema {#2}

      status: open
      created: 2026-03-20 22:22:54 UTC
      updated: 2026-03-20 22:22:54 UTC
      links: blocking:#3
```

## Sections Breakdown

### Project Root

```markdown
# Project Name {#project}
```

The top-level heading. The `{#project}` anchor is required. Access via `plan project`.

### Metadata

```markdown
## Metadata {#metadata}

    next_id: 6
```

Stores internal state. `next_id` is the next ticket ID to be assigned. You typically don't need to edit this directly.

### Description

```markdown
## Description {#description}

Project description goes here.
```

Optional project description. Access via `plan project description`.

### Custom Sections

You can add any sections you want between Metadata and Tickets:

```markdown
## Building {#building}

Build instructions...

## Testing {#testing}

Test instructions...

## Design {#design}

Architecture notes...

## Agents {#agents}

Instructions for AI agents...
```

Access any section via `plan project SECTION` (e.g., `plan project building`).

### Role Sections

Define roles for multi-agent workflows:

```markdown
## Role: lead {#role:lead}

You are the team lead...

## Role: executor {#role:executor}

You write code...
```

### Tickets Section

```markdown
## Tickets {#tickets}
```

Contains all tickets. This section is required and must be the last major section.

## Ticket Format

Each ticket is a list item (`* ##`) with an anchor ID:

```markdown
* ## Ticket: Task: Title goes here {#1}

      status: open
      assignee: alice
      links: blocked:#3 related:#2
      estimate: 5
      created: 2026-03-20 22:22:38 UTC
      updated: 2026-03-20 22:22:38 UTC

  Body text of the ticket. Can be multiple paragraphs.

  More details here.
```

### Ticket Header

```
* ## Ticket: TYPE: Title {#ID}
```

- `* ##` — required bullet + heading marker
- `Ticket:` — literal prefix (auto-added by `plan create`)
- `TYPE:` — ticket type: `Task`, `Bug`, `Epic`, `Improvement` (default: `Task`)
- `Title` — the ticket title
- `{#ID}` — unique numeric ID (auto-assigned)

### Attributes

Attributes appear immediately after the header, indented by **4 additional spaces** beyond the ticket's indentation level:

```markdown
* ## Ticket: Task: My ticket {#1}

      status: open
      assignee: alice
      custom-field: any value
```

Built-in attributes:

| Attribute | Description | Example |
|-----------|-------------|---------|
| `status` | Ticket status | `open`, `in-progress`, `done` |
| `assignee` | Who is responsible | `alice` |
| `links` | Dependencies and relationships | `blocked:#3 related:#2` |
| `created` | Creation timestamp (auto-set) | `2026-03-20 22:22:38 UTC` |
| `updated` | Last modification timestamp (auto-set) | `2026-03-20 22:43:47 UTC` |
| `estimate` | Work estimate | `5` |

You can add any custom attributes — they're just key-value pairs.

### Body Text

Body text appears below the attributes, at the ticket's base indentation + 2 spaces:

```markdown
* ## Ticket: Task: My ticket {#1}

      status: open

  This is the body text.

  It can have multiple paragraphs, code blocks,
  lists, or any markdown content.
```

### Nesting (Child Tickets)

Tickets nest via indentation. Each level adds 2 spaces:

```markdown
* ## Ticket: Task: Parent {#1}           ← top-level (0 spaces)

  * ## Ticket: Task: Child {#2}          ← level 1 (2 spaces)

    * ## Ticket: Task: Grandchild {#3}   ← level 2 (4 spaces)
```

## Comments

Comments live inside a special `Comments` container under a ticket:

```markdown
* ## Ticket: Task: My ticket {#1}

      status: open

  * ## Comments {#1:comments}

    * First comment {#1:comment:5}

      Comment body can be multi-line.

    * Second comment {#1:comment:6}
```

Comment IDs follow the pattern `TICKET_ID:comment:COMMENT_ID`.

## ID System

- Every node (section, ticket, comment) has a globally unique ID
- Ticket IDs are auto-incrementing integers
- Section IDs are their name (e.g., `metadata`, `description`)
- Comment IDs are compound: `TICKET_ID:comments`, `TICKET_ID:comment:N`
- The `next_id` in Metadata tracks the next available ID
- IDs are assigned at creation time and never reused

## Links Format

Links are stored as a space-separated list in the `links` attribute:

```
links: blocked:#3 blocking:#5 related:#2
```

Link types come in mirror pairs — when you add one side, the other is added automatically:

| You add | Mirror added |
|---------|-------------|
| `blocked:#3` on #5 | `blocking:#5` on #3 |
| `blocking:#3` on #5 | `blocked:#5` on #3 |
| `related:#3` on #5 | `related:#5` on #3 |
| `derived:#3` on #5 | `derived-from:#5` on #3 |
| `derived-from:#3` on #5 | `derived:#5` on #3 |
| `caused:#3` on #5 | `caused-by:#5` on #3 |
| `caused-by:#3` on #5 | `caused:#5` on #3 |

## See Also

- [Working with Tickets](tickets.md) — creating, editing, and managing tickets
- [CLI Reference](cli-reference.md) — complete command reference
- [Examples](examples.md) — practical examples
