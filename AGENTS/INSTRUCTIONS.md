You'll need to implement a ticket tracking system based on a single markdown file per project.

The file is supposed to be stored in the same git repo as the project itself and track tickets and issues. But also it's ok to have a standalone file.

The tickets are managed via a CLI binary called `plan`.

The program is written in Python3 and only uses standard libraries shipped with Python distribution like `sys`, `os`, etc. It's not allowed to pull in any external dependencies.

To simplify distribution, everything is implemented in one monolitic file.

All operations are handled by subcommands given in the command line.

Subcommands are divided into groups for reading/querying tickets and modifying them.

Subcommands must be both human and agent friendly.

It's ok to auto-detect batch/agent mode by testing if stdin and stdout are a terminal.

Sample md file structure in `template.md`.

Unit test specification in [TESTING.md](TESTING.md).

## File discovery

The plan file is located using the following precedence:

1. `--file` or `-f` flag on the command line.
2. The `PLAN_MD` environment variable.
3. The file `.PLAN.md` in the current git repository root (found via `git rev-parse --show-toplevel`).

## Common verbs:

* `get`: Print the thing out. This is the default (if no verb is given).
* `replace --force {text}`: Set the thing content to {text}. Requires `--force` flag.
* `replace --force -`: Set the thing content to <stdin>. Requires `--force` flag.
* `replace --force @file`: Set the thing content from file. Requires `--force` flag.
* `del`: Delete the thing.
* `add {text}` or `+ {text}`: Smart append — behavior depends on the target:
  * Ticket body (`plan 5 add "text"`): append text to the ticket body.
  * Comments section (`plan 5 comment add "text"`): create a new comment with auto-generated ID.
  * Specific comment (`plan 5:comment:1 add "text"`): add a reply (child) in the thread with auto-generated ID.
  * List attribute (`plan 5 attr links add "blocked:#3"`): parse and append to the list.
  * Scalar attribute (`plan 5 attr assignee add "bob"`): error — use `replace` or `set()`.
  * Project section (`plan project description add "text"`): append text to the section body.
* `add -` or `+ -`: Same as above, reading from stdin.
* `add @file` or `+ @file`: Same as above, reading from file.
* When `add` creates something that needs an ID (e.g. a comment), the ID is auto-generated from `next_id` in metadata.
* `mod {expr}` or `~ {expr}`: Modify the thing by evaluating a Python expression in a sandboxed namespace. See [DSL.md](DSL.md) for the full specification. Examples:
  * `~ 'set(assignee="alice")'`
  * `~ 'set(status="in-progress", assignee="alice")'`
  * `~ '[set(assignee="alice"), link("blocked", 3)]'`
  * `~ 'delete("assignee")'`
  * `~ 'link("related:#id")'`
  * `~ 'unlink("related:#id")'`

## Subcommands include:

* `project`: deal with per-project information. The project contains a bulk document describing the project. Subsections have IDs and can be accessed via the `project` subcommand (e.g. `plan project description get`).
* `list {query}`: list tickets - their titles and ids. Only tickets on one level are displayed by default. Tickets are ordered by file position. Query could be:
  * Empty or "-": top level.
  * `N`: list direct children of ticket N (titles).
  * "-r": list recursively.
  * "--self": also display the referenced ticket's title.
  * "--title text": search ticket titles.
  * "--text text": search ticket titles and contents.
  * "--attr value" search tickets with this attribute.
  * `-q {python expression}` (usually implicit — non-numeric args are auto-promoted to -q): eval this python expression to filter tickets. See [DSL.md](DSL.md). Examples: `'status == "open" and assignee == "alice"'`, `'"auth" in title.lower()'`.
  * `--format {python expression}`: eval this python expression to format each ticket for display. See [DSL.md](DSL.md). Examples: `'f"{indent}#{id} [{status}] {title}"'`.
  * `ready`: recursively list tasks ready for execution (no blockers and all children are closed).
  * `-n {N}`: limit the number of output lines.
* `create [parent] {expr}`: create a new ticket as a child of the given parent. `parent` is an optional bare integer for nesting. The expression is implicitly wrapped in `set(...)`, so only kwargs are needed. `title` is mandatory. See [DSL.md](DSL.md). Examples: `create 'title="Fix login bug"'`, `create 5 'title="Subtask"'`.
* `status {status}`: set ticket status. Shortcut for `~ 'set(status="...")'`. Syntax: `plan 5 status in-progress`. The status is either "open", "in-progress", or a free-text resolution (which implies the ticket is closed). E.g. `plan 5 status "won't do"` closes the ticket with that resolution.
* `close {resolution}`: close ticket and set resolution. Same as `status {resolution}`.
* `comment`: deal with comments. Syntax: `plan 5 comment get`, `plan 5 comment add "text"`. Comment IDs are integers starting from 1, unique within a ticket (e.g. `{#5:comment:1}`).
* `resolve`: resolve merge/rebase conflicts in the plan file after git pull/merge/rebase. This is a top-level command (`plan resolve`) that scans the entire file. Must understand markers `[<>=]{7}` and properly resolve them. Uses knowledge of the file structure: timestamps should be resolved by picking the newer value, indentation must be maintained to preserve hierarchy, and structural elements (ids, metadata blocks) should be merged correctly.
* `move`: reorder or reparent tickets. This is a verb — it acts on selectors.
* `move first`: move to first among current siblings.
* `move last`: move to last among current siblings.
* `move before N`: move before sibling N.
* `move after N`: move after sibling N.
* `move N`: reparent as last child of N.
* `move first N` / `move last N`: reparent as first/last child of N.
* Multiple targets are placed in selection order (e.g. `plan 5 7 9 move first`).
* `attr {attr}`: deal with attributes (e.g. `plan 5 attr assignee get`). Smart handling: "depends on" / "dependent on" links are interlinked automatically (adding `blocked:#3` to #5 also adds `blocking:#5` to #3). "related" links are also interlinked (adding `related:#3` to #5 also adds `related:#5` to #3).
* `check`: Check the file for errors. No verbs are allowed.
* `fix`: Try to automatically fix errors. No verbs are allowed.
* `h`, `help`, `-h`, `--help`: help text.

* Ticket ordering is determined by file position. The `move` verb reorders tickets within the file.

## Rules

* Commands (`create`, `edit`, `check`, `fix`, `resolve`, `help`) must be the first word.
* Verbs and selectors can go in any order on the command line. For example, `plan get 5 attr assignee` is equivalent to `plan 5 attr assignee get`.
* Pipeline order matters for `-r` and query expressions: `plan 1 -r is_open list` (descendants of #1, then filter) differs from `plan is_open 1 -r list` (open tickets, then add #1 and its descendants).
* `-p` is position-independent — it always adds ancestors to the final result. `plan -p 3` = `plan 3 -p`.
* At most one verb per request. Multiple verbs are an error.
* Multiple ticket IDs per request are allowed — the verb is applied to all of them. For example, `plan 5 3 get` gets both #5 and #3. `plan 5 3 del` deletes both.
* `status`, `close`, `reopen`, `move` are verbs — they act on selectors like any other verb.
* Multiple requests can be separated by `;` on the command line. The document is read once, then all requests are executed sequentially against the in-memory state, then the document is written back once.
* By default, only one level of hierarchy is displayed.
* When displaying or editing the ticket or a group of tickets, the indentation always starts from 0. When the edited content is inserted back to the original document, it's indented properly to fit the hierarchy.
* Ticket ids are flat global integers — a single incrementing number from `next_id` in metadata. IDs are stable: moving a ticket never changes its ID.
* Ticket IDs are positive integers starting at 1.
* Top-level tickets have no parent.

## Document structure

* The collection of tickets, comments, and other project information is stored in a single markdown file. The file is organized into sections, with each section containing relevant information about the project, such as metadata, description, roles, and tickets. Each ticket has its own section with details such as creation date, status, assignee, and related tickets. Comments on tickets are nested within the ticket sections, allowing for easy tracking of discussions and updates related to each ticket. This structure allows for a comprehensive overview of the project and its progress.
* The file structure is designed to be easily readable by humans and agents and for scripted processing.
* The markdown file is structured as follows:
  * The structure is maintained as a (potentially, deeply) nested bullet list.
  * The ticket's content is determined by indentation.
  * Tickets are organized in a hierarchical manner, allowing for subtasks and related tickets to be easily tracked.
  * Special lines end with `{#id}` and are used to identify sections, tickets, comments, etc. All IDs are global and unique across the entire document.
  * Attributes may follow the special lines and use this syntax: {indentation} {4 spaces} {non-whitespace-attribute-name} {:} {value}
  * "links" is a list of links.
  * Custom attributes are allowed and are treated as text.
  * The special line can be followed by metadata block (indented by 4 spaces) that contains key-value pairs providing additional information about the section, ticket, comment, etc.
  * The content of the section, ticket, comment, etc. follows the metadata block and can include descriptions, discussions, and other relevant information.
  * Comments are arranged in threads.

## Python program requirements

* No external dependencies except standard libraries.
* The entire document must be represented in a Python class with methods to manipulate it.
* The Project and Ticket must be classes.
* Project has a list of Tickets, a map of project's properties and a global map from id to things.
* Tickets have a list of subtickets.
* All entities have a map of attributes.

