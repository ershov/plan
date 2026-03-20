# Selectors and Filters

Queries are classified by return type:

- **Selector** (returns `list`, `set`, or `int`): adds those ticket IDs to the
  target set.  Selectors union — each one contributes more tickets.
- **Filter** (returns `bool`): narrows the current target set.  If no targets
  exist yet, the filter runs against all tickets.

Non-numeric arguments are treated as implicit `-q` queries, so these are
equivalent:

    plan -q is_open list
    plan is_open list

Queries are processed sequentially — selectors add, filters narrow:

    plan is_open 'tag == "b"' list   # is_open → {1,3,4}, then tag=="b" → {4}
    plan 'children_of(1)' list       # selector: returns [2] → shows #2

## Tree used in examples

```
#1 Alpha (open, tag="a")
  #2 Beta (closed, tag="b")
    #3 Gamma (open, tag="a")
#4 Delta (open, tag="b")
```

## `list` verb

Bare `plan list` shows all tickets.  Output always includes tree-depth
indentation.  Targets are shown in tree-walk order.

| Invocation | Mechanism | Result |
|---|---|---|
| `plan list` | all tickets | #1, #2, #3, #4 |
| `plan 1 list` | single ID → ticket itself | #1 |
| `plan 2 3 list` | multiple IDs → those tickets | #2, #3 |
| `plan is_open list` | filter → matching tickets | #1, #3, #4 |
| `plan 'tag=="b"' list` | filter on custom attr | #2, #4 |
| `plan is_open 'tag=="b"' list` | two filters → AND | #4 |
| `plan 1 is_open list` | ID + matching filter | #1 |
| `plan 2 is_open list` | closed ID + open filter → empty | (none) |
| `plan 2 'tag=="b"' list` | ID + matching filter | #2 |
| `plan 'children_of(1)' list` | selector → those IDs | #2 |
| `plan -r list` | all tickets recursively | #1, #2, #3, #4 |
| `plan 1 -r list` | ID + recursive → self and descendants | #1, #2, #3 |
| `plan is_open -r list` | filter + recursive → selected + descendants | #1, #2, #3, #4 |

## `get` verb

| Invocation | Mechanism | Result |
|---|---|---|
| `plan get` | no targets | error: requires a ticket ID |
| `plan 1` | single ID → default verb=get | Alpha |
| `plan 2 3 get` | multiple IDs → each shown | Beta, Gamma |
| `plan is_open get` | filter → each match shown | Alpha, Gamma, Delta |
| `plan 'tag=="b"' get` | filter on custom attr | Beta, Delta |
| `plan 1 'tag=="b"' get` | ID + non-matching filter | error (empty) |
| `plan 1 is_open get` | ID + matching filter | Alpha |
| `plan 1 -r` | ID + recursive → **tree-view** rendering | Alpha, Beta, Gamma as tree |
| `plan is_open -r get` | filter + recursive → **individual** rendering | all four individually |

`ID -r` without a query renders the subtree as a single block (tree-view).
Query + `-r` renders each ticket individually — tree-view only makes sense
for a single scoped subtree.

## Default verb

The default verb is always `get`.

| Invocation | Default verb |
|---|---|
| `plan 1` | `get` |
| `plan is_open` | `get` |
| `plan 1 is_open` | `get` |

## Subtree filtering

To filter within a subtree, use `is_descendant_of()`:

    plan 'is_descendant_of(1)' list              # descendants of #1
    plan 'is_descendant_of(1) and is_open' list   # open descendants of #1

## DSL functions

| Expression | Returns | Type | Description |
|---|---|---|---|
| `parent` | `int` | — | Parent ticket ID, or `0` for root tickets |
| `parent == 0` | `bool` | filter | True for root-level tickets |
| `parent_of(N)` | `int` | selector | Parent ID of ticket #N (0 if root) |
| `is_descendant_of(P)` | `bool` | filter | True if current ticket is under #P |
| `is_descendant_of(P, C)` | `bool` | filter | True if #C is under #P |
| `is_descendant_of(0)` | `bool` | filter | True for all tickets (0 = virtual root) |
| `children_of(N)` | `list[int]` | selector | Child ticket IDs of #N (0 = top-level) |
| `children_of(N, True)` | `list[int]` | selector | All descendant IDs recursively |
