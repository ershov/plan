# plan CLI — Agent Cheat Sheet

## File Discovery

```bash
plan -f path/to/file.md list    # Explicit file
export PLAN_MD=path/to/file.md  # Environment variable
# Auto-discovers .PLAN.md at git root or walking up from cwd
```

## Reading

```bash
plan list                              # Top-level tickets
plan list ready                        # Open tickets with no open blockers
plan list order                        # Tickets in execution order
plan -r list                           # All tickets recursively
plan 5                                 # Ticket #5 content (title, attrs, body)
plan 5 -r                              # Ticket #5 and all descendants (tree view)
plan 5 list                            # Children of ticket #5
plan 'status=="open"' list              # Filter by query
plan -r list --format 'f"{indent}#{id} [{status}] {title}"'  # Custom format
plan -r list -n 10                     # Limit to first 10
plan 5 attr assignee                   # Get single attribute
plan 5 comment                         # List comments on ticket #5
plan project                           # Show project-level sections
plan project description               # Show project description
```

## Creating

```bash
plan create 'title="Fix login bug"'                          # Basic ticket
plan create 'title="Fix login", status="open"'               # With attributes
plan create 5 'title="Sub-task"'                              # Child of #5
echo 'title="From stdin"' | plan create -                     # From stdin
```

## Updating

```bash
plan 5 status in-progress              # Set status
plan 1 2 3 status planned              # Bulk status
plan 5 close                           # Close (status=done)
plan 5 close fixed                     # Close with resolution
plan 5 ~ 'set(assignee="alice")'      # Set attribute via DSL
plan 5 ~ 'set(status="in-progress", assignee="alice")'  # Multiple attrs
plan 5 ~ 'add(text="Extra detail")'   # Append to body
plan 5 ~ 'add(comment="Review note")' # Add comment via DSL
plan 5 link blocked 3                  # Add dependency link
plan 5 unlink blocked 3               # Remove dependency link
plan 5 ~ 'delete("estimate")'         # Remove attribute
plan 5 comment add "Needs review"      # Add comment
plan 5 add "Another paragraph"         # Append to body text
```

## Organizing

```bash
plan 5 move 3                          # Move #5 under #3 (reparent)
plan 5 move before 7                   # Move #5 before sibling #7
plan 5 move first                      # Move to top of siblings
plan 5 move after 3                    # Position after #3
plan del 5                             # Delete ticket (no children)
plan 5 -r del                          # Delete ticket and all descendants
plan 5 6 7 close                       # Apply verb to multiple tickets
plan 5 status done ";" 6 status in-progress  # Multiple commands in one call
```

## Validation

```bash
plan check                             # Validate document structure
plan fix                               # Auto-repair structural issues
plan resolve                           # Resolve git merge conflicts
```

## DSL Quick Reference

```
# Filter: evaluated per-ticket, truthy = include (-q is implicit)
plan 'status == "open"' list
plan 'assignee == "alice"' list
plan 'status == "open" and assignee != ""' list
plan '"bug" in title.lower()' list

# Format (--format): evaluated per-ticket, result printed
plan -r list --format 'f"{indent}#{id} [{status}] {title}"'

# Mutators (mod/~): modify ticket attributes
plan 5 ~ 'set(key=val, ...)'          # Set attributes
plan 5 ~ 'add(text="...", comment="...", links="blocked:#3")'  # Append
plan 5 ~ 'delete("attr_name")'        # Remove attribute
plan 5 ~ 'link("blocked", 3)'         # Add link with mirror
plan 5 ~ 'unlink("blocked", 3)'       # Remove link with mirror

# Available in expressions: id, title, text, status, assignee,
#   parent, children, links, plus any custom attributes.
# Builtins: len, any, all, min, max, sorted, int, str, float
```

## Statuses

Open statuses (considered "in progress"): `open`, `in-progress`, `planned`, `assigned`

Closed statuses: any other string (convention: `done`, `fixed`, `wontfix`, `duplicate`)

## Link Types

`blocked`/`blocking`, `related`/`related`, `derived`/`derived-from`, `caused`/`caused-by`

Links are mirrored automatically: linking #5 as `blocked` by #3 also adds `blocking:#5` to #3.
