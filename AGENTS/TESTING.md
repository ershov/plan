# Unit Tests

Tests use Python's built-in `unittest` module. No external test frameworks.

Tests live in a single file `test_plan.py` next to `plan.py`. Run with:

```bash
python3 -m pytest test_plan.py      # if pytest happens to be available
python3 -m unittest test_plan       # always works
python3 test_plan.py                # also works (file has __main__ block)
```

## Test structure

Each test class inherits from `unittest.TestCase`. Tests that need a plan document create one as a string in `setUp` and parse it in-memory — no temp files needed for pure logic tests.

Helper: a `make_doc(text)` function that parses a markdown string into the document model. Tests that exercise CLI I/O use `subprocess.run` against a temp file.

## What to test

### 1. Document parsing and round-trip

* Parse `template.md` and verify the project title, metadata (`next_id`), description, roles, and tickets are extracted correctly.
* Parse a document, serialize it back, and verify the output matches the original byte-for-byte (round-trip).
* Parse a document with deeply nested subtasks (3+ levels) and verify parent/child relationships.
* Verify that attribute lines (indented 4 spaces, `key: value`) are parsed into the attribute dict.
* Verify that the `{#id}` suffix is stripped from display titles but stored in the id map.
* Verify that all IDs are unique and present in the global id map.
* Verify that custom (non-standard) attributes are parsed and stored as text.

### 2. File discovery

* `--file` / `-f` flag overrides everything.
* `PLAN_MD` env variable is used when no flag is given.
* Falls back to `.PLAN.md` at git repo root.
* Error when no file is found by any method.

### 3. Command-line parsing

* Verbs and selectors can appear in any order: `plan get 5 attr assignee` == `plan 5 attr assignee get`.
* Pipeline order matters for `-r` and query expressions (selectors add, filters narrow, left-to-right).
* `-p` is position-independent — always adds ancestors to the final result.
* Commands must be the first word: `plan edit 5`, not `plan 5 edit`.
* Bare integers select tickets by ID: `plan 5` is equivalent to `plan 5 get`.
* Multiple targets in one request: `plan 5 3 get`.
* Multiple requests separated by `;`.
* At most one verb per request — error on two verbs.
* Commands that reject verbs (`create`, `check`, `fix`, `resolve`) error when a verb is supplied.
* `status`, `close`, `reopen`, `move` are verbs that act on selectors.
* Unknown subcommands produce an error.

### 4. `get` verb

* `plan 1 get` prints the ticket content with indentation starting from 0.
* `plan project description get` prints the description section.
* `get` is the default verb when none is specified.
* Getting a nonexistent id is an error.

### 5. `replace` verb

* `replace --force "new text"` replaces the body.
* `replace` without `--force` is an error.
* `replace --force -` reads from stdin.
* `replace --force @file` reads from a file.
* Indentation is restored correctly when writing back.

### 6. `add` verb

* Appending text to a ticket body.
* Adding a comment to a ticket's comment section — auto-generated comment id uses `next_id` and increments it.
* Adding a reply to an existing comment (thread nesting).
* Appending to a list attribute (e.g. `links`).
* Error when adding to a scalar attribute (e.g. `assignee`).
* `add -` reads from stdin.
* `add @file` reads from a file.

### 7. `del` verb

* Delete a ticket — removed from parent's children and from global id map.
* Delete an attribute.
* Delete a comment.

### 8. `edit` command

* `plan edit 5` launches `$EDITOR` for ticket #5.
* `plan edit 5 -r` includes children in the edit buffer.
* Test that the correct temp file content is prepared and that the edited content is inserted back with correct indentation. Can mock `$EDITOR` with a script.

### 9. `mod` / `~` verb (DSL)

* `set(assignee="alice")` changes assignee.
* `set(status="in-progress", assignee="alice")` sets multiple attributes.
* `[set(assignee="alice"), link("blocked", 3)]` applies multiple modifications.
* `delete("assignee")` removes the attribute.
* `link("blocked", 3)` adds a link entry.
* `unlink("related", 7)` removes a link entry.
* `set(text=file("path"))` reads a file and sets body text.
* Sandboxing: `import os` is blocked, `open` is not available, `__import__` is not available.
* Missing attributes resolve to `""` rather than raising `NameError`.

### 10. `list` subcommand

* Default (no query): lists top-level ticket titles and ids, ordered by file position.
* `list 5`: lists direct children of ticket #5.
* `list -r`: recursive listing.
* `list --self`: includes the referenced ticket itself.
* `list --title text`: filters by title substring.
* `list --text text`: filters by title and body.
* `list --attr value`: filters by attribute value.
* `list -q 'status == "open"'`: DSL filter expression (also works as implicit: `plan 'status == "open"' list`).
* `list --format 'f"{indent}#{id} [{status}] {title}"'`: custom format expression.
* `list ready`: only tasks with no blockers and all children closed.
* `list -n 3`: limits output to 3 lines.
* Results are always ordered by file position.

### 11. `create` subcommand

* `create 'title="Bug"'` creates a top-level ticket.
* `create 5 'title="Subtask"'` creates a child of #5.
* New ticket gets the `next_id` value; `next_id` is incremented.
* `created` and `updated` timestamps are set.
* Default status is `open`.
* New ticket is placed last among siblings by default.
* Missing `title` is an error.
* Rejects verbs (e.g. `create get ...` is an error).

### 12. `status` / `close` / `reopen` verbs

* `status`, `close`, `reopen` are verbs that act on selectors.
* `plan 5 status open` sets status to `"open"`.
* `plan 5 status in-progress` sets status to `"in-progress"`.
* `plan 5 status "won't do"` closes the ticket with that resolution.
* `plan 5 close "duplicate"` sets status to `"duplicate"` (closed).
* `plan 5 reopen` sets status to `"open"`.
* `updated` timestamp is refreshed.
* Works with filters: `plan is_open close done`.

### 13. `comment` subcommand

* `comment get` prints all comments for a ticket.
* `comment add "text"` creates a new comment with auto-generated id.
* Comment ids are integers starting from 1, unique within the ticket.
* Threaded replies: adding to `{#5:comment:1}` creates a nested child.
* `updated` timestamp on the ticket is refreshed.

### 14. `move` verb

* `move` is a verb that acts on selectors.
* `move first` — reorder to first among current siblings.
* `move last` — reorder to last among current siblings.
* `move before 3` — position before sibling #3.
* `move after 3` — position after sibling #3.
* `move 10` — reparent as last child of #10.
* `move first 10` / `move last 10` — reparent as first/last child of #10.
* Multiple targets are placed in selection order.
* Ticket id does not change after move.
* The ticket is removed from the old parent's children list and added to the new parent's.

### 15. `attr` subcommand

* `attr assignee get` prints the assignee value.
* `attr assignee replace --force "bob"` sets the assignee.
* `attr links get` prints the links list.
* Link interlinking: adding `blocked:#3` to #5 also adds `blocking:#5` to #3.
* Link interlinking: adding `related:#3` to #5 also adds `related:#5` to #3.
* Removing an interlinked link also removes the reverse link.
* Custom attributes are get/set as text: `attr myfield get`, `attr myfield replace --force "value"`.

### 16. `check` and `fix` subcommands

* `check` on a valid document reports no errors.
* `check` detects duplicate ids.
* `check` detects missing `next_id` or `next_id` that conflicts with existing ids.
* `check` detects broken links (links to nonexistent ids).
* `fix` auto-repairs what it can (e.g. regenerates `next_id`).
* Rejects verbs.

### 18. `resolve` subcommand

* Resolves git conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in the plan file.
* Timestamps are resolved by picking the newer value.
* Structural merges: IDs and metadata blocks are merged correctly.
* Indentation is preserved.
* Rejects verbs.

### 19. Batch mode / agent detection

* When stdin/stdout are not a TTY, output is machine-friendly (no color, no interactive prompts).
* Interactive mode detects TTY and may use color/prompts.

### 20. Edge cases and error handling

* Empty plan file (only metadata, no tickets).
* Ticket with no attributes.
* Ticket with no body text.
* Operating on the top-level (no target specified).
* Moving tickets with many siblings.
* Unicode in ticket titles, bodies, and comments.
* Attribute values containing colons.
* Multiple `;`-separated requests modifying the same ticket.
* File written only once after all `;`-separated requests complete.

## Test conventions

* Test method names: `test_<component>_<behavior>`, e.g. `test_parse_nested_tickets`, `test_move_before_sibling`.
* Use `self.assertEqual`, `self.assertIn`, `self.assertRaises` — standard `unittest` assertions.
* Tests that run the CLI as a subprocess use a temp file created via `tempfile.NamedTemporaryFile` and pass it with `-f`.
* Tests must not depend on execution order.
* Tests must not leave temp files behind (use `addCleanup` or `tearDown`).
