# Expression DSL

All user-facing expressions (`-q`, `--format`, `mod`/`~`) are plain Python expressions evaluated via `eval()` with a sandboxed namespace. No custom parser is needed — Python handles all parsing.

## Sandbox

Every `eval()` call gets a namespace with `__builtins__` restricted to safe functions:

```python
SAFE_BUILTINS = {
    "len": len, "any": any, "all": all,
    "min": min, "max": max, "sorted": sorted,
    "int": int, "str": str, "float": float,
    "True": True, "False": False, "None": None,
}
```

No `import`, `open`, `exec`, `eval`, `compile`, or `__import__` are available.

## Namespace contents

The namespace is populated from the entity being operated on (ticket, project, etc.):

| Variable    | Type          | Description                                |
|-------------|---------------|--------------------------------------------|
| `id`        | `int`         | Ticket id                                  |
| `title`     | `str`         | Ticket title                               |
| `status`    | `str`         | Status value                               |
| `is_open`   | `bool`        | `True` if active or deferred (not closed)                |
| `is_active` | `bool`        | `True` if status is `"open"`, `"in-progress"`, or unset |
| `ready`     | `bool`        | `True` if open with no open blockers and no open children |
| `assignee`  | `str`         | Assignee name or `""`                      |
| `move`      | `str`         | Ephemeral positioning attribute. `set()` and `create` accept positional expressions: `"first [N]"`, `"last [N]"`, `"before N"`, `"after N"` — may reparent the ticket. Not persisted. |
| `links`     | `dict`        | `{"blocked": [3, 7], "related": [2]}`      |
| `created`   | `str`         | Created timestamp                          |
| `updated`   | `str`         | Updated timestamp                          |
| `parent`    | `ParentAccessor` | Parent ticket. Callable: `parent()` returns parent, `parent(all=True)` returns all ancestors |
| `children`  | `ChildrenAccessor` | Child tickets (list). Callable: `children()` or `children(recursive=True)` for all descendants |
| `text`      | `str`         | Ticket body text                           |
| `depth`     | `int`         | Nesting depth (0 for top-level, 1 for child, etc.) |
| `indent`    | `str`         | `"  " * depth` — two spaces per depth level |
| *any attr*  | `str`         | Any other attribute from the metadata block|

All ticket attributes are injected directly as variables. Missing attributes resolve to `""` (empty string) rather than raising `NameError` — this can be done by using a `defaultdict`-like namespace or a custom `__missing__` dict subclass.

### Helper functions

Available in all expression contexts (filtering, formatting, and modification):

| Function       | Type  | Description                                              |
|----------------|-------|----------------------------------------------------------|
| `file(path)`   | `str` | Read and return the contents of a file. `"-"` reads stdin. |

## Use case 1: Filtering (`-q`)

The expression must return a truthy/falsy value. It is evaluated once per ticket.

```bash
plan 'status == "open" and assignee == "alice"' list
plan '"auth" in title.lower()' list
plan 'assignee == "alice"' list
plan 'children and any(c.status == "open" for c in children)' list
plan 'status != "done" and not children' list    # leaf tickets only
plan '"blocked" in links' list
```

### Implementation

```python
class DefaultNamespace(dict):
    """Dict that returns "" for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return ""

def _file(path):
    """Read file contents. "-" reads stdin."""
    if path == "-":
        return sys.stdin.read()
    with open(path) as f:
        return f.read()

def match(ticket, expr):
    ns = DefaultNamespace(SAFE_BUILTINS)
    ns["file"] = _file
    ns.update(ticket.as_namespace())  # id, title, status, ...
    return eval(expr, {"__builtins__": {}}, ns)
```

## Use case 2: Formatting (`--format`)

The expression is evaluated and its result is converted to `str`. Typically an f-string.

```bash
plan list --format 'f"#{id:>4} [{status:^11}] {title:.40}"'
plan list --format 'f"{id} @{assignee or \"-\"}: {title}"'
plan 'status == "open"' --format 'f"{indent}#{id} {title}"' list
```

### Implementation

Same namespace as filtering — just `str(eval(expr, ...))`.

## Use case 3: Modifications (`mod` / `~`)

Mutator functions are added to the namespace. Each returns `True` so they can be composed.

```bash
# Single modification
plan 5 ~ 'set(assignee="alice")'
plan 5 ~ 'set(status="in-progress", assignee="alice")'

# Multiple modifications (list of calls)
plan 5 ~ '[set(assignee="alice"), link("blocked", 3)]'

# Delete an attribute
plan 5 ~ 'delete("assignee")'

# Links
plan 5 ~ 'link("blocked", 3)'
plan 5 ~ 'unlink("related", 7)'

# Title and text
plan 5 ~ 'set(title="New title")'

# Set text from file or stdin
plan 5 ~ 'set(text=file("spec.txt"))'
echo "description" | plan 5 ~ 'set(text=file("-"))'

# Smart add — append to body, list, or comments
plan 5 ~ 'add(text="Additional notes.")'
plan 5 ~ 'add(links="blocked:#3")'
plan 5 ~ 'add(comment="This needs review.")'
```

### Available mutator functions

| Function                     | Description                              |
|------------------------------|------------------------------------------|
| `set(attr=value, ...)`       | Set one or more attributes               |
| `add(attr=value, ...)`       | Smart append — see below                 |
| `delete(attr, ...)`          | Remove one or more attributes            |
| `link(type, target_id)`      | Add a link                               |
| `unlink(type, target_id)`    | Remove a link                            |

#### `add()` behavior by attribute type

| Call                          | Attribute type | Behavior                                          |
|-------------------------------|----------------|---------------------------------------------------|
| `add(text="...")`            | body text      | Append to the ticket body                         |
| `add(links="blocked:#3")`    | list           | Parse and append to the links list                |
| `add(comment="text")`        | comments       | Create a new comment with auto-generated ID       |
| `add(assignee="x")`          | scalar string  | Error — use `set()` instead                       |
| `add(move="first")`          | positional     | Error — use `set()` instead                       |

### Implementation

```python
def apply_mod(ticket, expr):
    def _set(**kw):
        ticket.set_attrs(kw)
        return True
    def _add(**kw):
        ticket.add_attrs(kw)
        return True
    def _delete(*names):
        ticket.del_attrs(names)
        return True
    def _link(type, target):
        ticket.add_link(type, target)
        return True
    def _unlink(type, target):
        ticket.del_link(type, target)
        return True

    ns = DefaultNamespace(SAFE_BUILTINS)
    ns["file"] = _file
    ns.update(ticket.as_namespace())
    ns["set"] = _set
    ns["add"] = _add
    ns["delete"] = _delete
    ns["link"] = _link
    ns["unlink"] = _unlink
    eval(expr, {"__builtins__": {}}, ns)
```

## Use with `create`

The `create` subcommand takes a single expression that is implicitly wrapped in `set(...)`. Only kwargs are needed. `title` is mandatory.

```bash
plan create 'title="Fix login bug", status="open"'
plan create 'title="Add caching"'
```

Internally, `create` evaluates `set(<expr>)`, so the above is equivalent to `set(title="Fix login bug", status="open")`.

## Design notes

* **One mechanism, three features.** The same namespace construction serves filtering, formatting, and mutation. Only the injected functions differ.
* **No parser.** Python's `eval()` handles all parsing, operator precedence, string handling, etc.
* **Composable.** Multiple mutations via `[op1(), op2()]` or `op1() and op2()`.
* **Extensible.** Adding a new function to the sandbox is a 3-line addition.
* **Familiar.** Anyone who knows Python (human or agent) can use it immediately.
* **Safe.** `__builtins__` is stripped. Only whitelisted functions are available.
