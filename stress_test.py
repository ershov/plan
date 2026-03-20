#!/usr/bin/env python3
"""Stress test for plan.py — generates a bash script that exercises the CLI.

Usage: python3 stress_test.py <seed> <num_operations>

The generated bash script creates a temp plan file, runs a sequence of
randomized plan.py operations against it, and checks for errors.
"""

import random
import sys


ESTIMATES = ["1h", "2h", "3h", "4h", "5h"]
STATUSES_OPEN = ["open", "in-progress", "planned"]
STATUSES_CLOSED = ["done", "closed", "won't do", "duplicate", "invalid"]
LINK_TYPES = ["blocked", "blocking", "related", "derived", "caused"]

VERBS = ["fix", "add", "update", "refactor", "test", "deploy", "review",
         "optimize", "implement", "design", "document", "remove", "cleanup",
         "migrate", "validate", "setup", "configure", "enable", "disable",
         "check", "verify", "monitor", "debug", "profile", "benchmark"]

NOUNS = ["login", "auth", "API", "database", "cache", "UI", "form",
         "button", "page", "endpoint", "service", "module", "config",
         "build", "pipeline", "test", "schema", "model", "query",
         "handler", "router", "middleware", "logger", "worker", "queue"]

BODY_TEXTS = [
    "This needs attention soon.",
    "Low priority but important.",
    "Blocking other work.",
    "Needs review before merge.",
    "Follow up on previous discussion.",
    "See related ticket for context.",
    "Consider edge cases.",
    "Performance impact is unknown.",
    "Requires testing on staging.",
    "Documentation update needed.",
]

COMMENT_TEXTS = [
    "Looks good to me.",
    "Need more details here.",
    "Working on this now.",
    "Fixed in latest commit.",
    "Can we revisit this?",
    "Agreed, lets proceed.",
    "Not sure about this approach.",
    "Tests are passing now.",
    "Blocked by upstream issue.",
    "Will address in next sprint.",
]


def esc(s):
    """Shell-escape a string using single quotes."""
    return "'" + s.replace("'", "'\\''") + "'"


def q(id_val, rng=None):
    """Quote an id as a ticket target, randomly picking an alias form.

    The four forms are: '#N', 'id #N', 'N', 'id N'.
    If rng is None, always uses '#N' (for command arguments like move).
    """
    if rng is None:
        return f"'#{id_val}'"
    form = rng.choice(["hash", "id_hash", "bare", "id_bare"])
    if form == "hash":
        return f"'#{id_val}'"
    elif form == "id_hash":
        return f"id '#{id_val}'"
    elif form == "bare":
        return str(id_val)
    else:
        return f"id {id_val}"


class State:
    """Tracks simulated plan file state for generating valid operations."""

    def __init__(self):
        self.next_id = 1
        self.alive = []
        self.deleted = set()
        self.statuses = {}
        self.parents = {}
        self.comment_counts = {}
        self.project_sections = []  # user-created sections (metadata/tickets are builtin)

    def pick(self, rng):
        if not self.alive:
            return None
        return rng.choice(self.alive)

    def pick2(self, rng):
        if len(self.alive) < 2:
            return None, None
        return rng.sample(self.alive, 2)

    def add_ticket(self, parent=0):
        tid = self.next_id
        self.next_id += 1
        self.alive.append(tid)
        self.statuses[tid] = "open"
        self.parents[tid] = parent
        self.comment_counts[tid] = 0
        return tid

    def _descendants(self, tid, _seen=None):
        """Find all descendants of tid recursively."""
        if _seen is None:
            _seen = set()
        desc = []
        for cid in list(self.alive):
            if self.parents.get(cid) == tid and cid not in _seen:
                _seen.add(cid)
                desc.append(cid)
                desc.extend(self._descendants(cid, _seen))
        return desc

    def remove_ticket(self, tid):
        to_remove = [tid] + self._descendants(tid)
        for rid in to_remove:
            if rid in self.alive:
                self.alive.remove(rid)
                self.deleted.add(rid)

    def move_ticket(self, tid, new_parent):
        self.parents[tid] = new_parent


def gen_title(rng):
    return f"{rng.choice(VERBS)} {rng.choice(NOUNS)} {rng.choice(NOUNS)}"


# ---------------------------------------------------------------------------
# Operation generators — each returns (description, cmd_args_string) or None
# ---------------------------------------------------------------------------

def op_create(rng, st):
    title = gen_title(rng)
    estimate = rng.choice(ESTIMATES)
    parent = 0
    if st.alive and rng.random() < 0.4:
        parent = st.pick(rng)
    # Sometimes include text in create expression
    if rng.random() < 0.3:
        text = rng.choice(BODY_TEXTS)
        expr = f'title="{title}", estimate="{estimate}", text="{text}"'
    else:
        expr = f'title="{title}", estimate="{estimate}"'
    if parent == 0:
        cmd = f'create {esc(expr)}'
    else:
        parent_arg = rng.choice([f"'#{parent}'", str(parent)])
        cmd = f'create {parent_arg} {esc(expr)}'
    st.add_ticket(parent)
    return ("create", cmd)


def op_list(rng, st):
    variant = rng.choice(["top", "recursive", "children", "query", "ready",
                          "title_search", "format"])
    if variant == "top":
        return ("list", "list")
    elif variant == "recursive":
        return ("list-r", "list -r")
    elif variant == "children":
        tid = st.pick(rng)
        if tid is None:
            return ("list", "list")
        return ("list-children", f"list {q(tid)}")
    elif variant == "query":
        status = rng.choice(STATUSES_OPEN + STATUSES_CLOSED)
        return ("list-query", f"list -q {esc(f'status == {repr(status)}')}")
    elif variant == "ready":
        return ("list-ready", "list ready")
    elif variant == "title_search":
        word = rng.choice(["fix", "add", "API", "test", "login", "build"])
        return ("list-title", f"list --title {esc(word)}")
    elif variant == "format":
        fmt = 'f"{indent}#{id} [{status}] {title}"'
        return ("list-format", f"list --format {esc(fmt)}")


def op_get(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    return ("get", f"{q(tid, rng)} get")


def op_status(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    if rng.random() < 0.5:
        s = rng.choice(STATUSES_OPEN)
    else:
        s = rng.choice(STATUSES_CLOSED)
    st.statuses[tid] = s
    return ("status", f"{q(tid, rng)} status {esc(s)}")


def op_close(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    res = rng.choice(STATUSES_CLOSED)
    st.statuses[tid] = res
    return ("close", f"{q(tid, rng)} close {esc(res)}")


def op_mod(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    action = rng.choice(["set_estimate", "set_status", "set_assignee",
                          "delete_attr", "set_multi"])
    if action == "set_estimate":
        p = rng.choice(ESTIMATES)
        return ("mod-estimate", f"{q(tid, rng)} mod {esc(f'set(estimate={repr(p)})')}")
    elif action == "set_status":
        s = rng.choice(STATUSES_OPEN)
        st.statuses[tid] = s
        return ("mod-status", f"{q(tid, rng)} mod {esc(f'set(status={repr(s)})')}")
    elif action == "set_assignee":
        name = rng.choice(["alice", "bob", "charlie", "diana"])
        return ("mod-assignee", f"{q(tid, rng)} mod {esc(f'set(assignee={repr(name)})')}")
    elif action == "delete_attr":
        attr = rng.choice(["assignee", "estimate"])
        return ("mod-delete", f"{q(tid, rng)} mod {esc(f'delete({repr(attr)})')}")
    elif action == "set_multi":
        p = rng.choice(ESTIMATES)
        s = rng.choice(STATUSES_OPEN)
        st.statuses[tid] = s
        return ("mod-multi", f"{q(tid, rng)} mod {esc(f'[set(estimate={repr(p)}), set(status={repr(s)})]')}")


def op_add_body(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(BODY_TEXTS)
    return ("add-body", f"{q(tid, rng)} add {esc(text)}")


def op_comment_add(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(COMMENT_TEXTS)
    st.comment_counts[tid] = st.comment_counts.get(tid, 0) + 1
    return ("comment-add", f"{q(tid, rng)} comment add {esc(text)}")


def op_comment_get(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    return ("comment-get", f"{q(tid, rng)} comment get")


def op_attr_get(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    attr = rng.choice(["estimate", "status", "assignee", "links"])
    return ("attr-get", f"{q(tid, rng)} attr {attr} get")


def op_attr_replace(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    attr = rng.choice(["estimate", "assignee"])
    if attr == "estimate":
        val = rng.choice(ESTIMATES)
    else:
        val = rng.choice(["alice", "bob", "charlie"])
    return ("attr-replace", f"{q(tid, rng)} attr {attr} replace --force {esc(val)}")


def op_link(rng, st):
    a, b = st.pick2(rng)
    if a is None:
        return None
    lt = rng.choice(LINK_TYPES)
    return ("link", f"{q(a, rng)} attr links add {esc(f'{lt}:#{b}')}")


def op_reorder(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    action = rng.choice(["first", "last", "before", "after"])
    if action in ("first", "last"):
        return ("move-" + action, f"{q(tid, rng)} move {action}")
    other = st.pick(rng)
    if other is None or other == tid:
        return ("move-first", f"{q(tid, rng)} move first")
    return ("move-" + action, f"{q(tid, rng)} move {action} {q(other)}")


def op_move(rng, st):
    a, b = st.pick2(rng)
    if a is None:
        return None
    action = rng.choice(["to", "before", "after"])
    if action == "to":
        target = rng.choice([0, b])
        st.move_ticket(a, target)
        return ("move-to", f"{q(a, rng)} move {q(target)}")
    # For before/after, the parent becomes the same as b's parent
    st.move_ticket(a, st.parents.get(b, 0))
    return ("move-" + action, f"{q(a, rng)} move {action} {q(b)}")


def op_del(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    st.remove_ticket(tid)
    return ("del", f"-r {q(tid, rng)} del")


def op_check(rng, st):
    return ("check", "check")


def op_fix(rng, st):
    return ("fix", "fix")


def op_multi_get(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 4), len(st.alive)))
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-get", f"{id_args} get")


def op_semicolon(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    p = rng.choice(ESTIMATES)
    return ("semicolon", f"{q(tid, rng)} mod {esc(f'set(estimate={repr(p)})')} ';' {q(tid, rng)} attr estimate get")


SECTION_NAMES = ["description", "roles", "goals", "risks", "notes"]

SECTION_TEXTS = [
    "This section describes the overall approach.",
    "Key stakeholders are identified here.",
    "The primary goal is to deliver on time.",
    "Risks include scope creep and dependencies.",
    "Remember to update docs before release.",
    "See the related design document.",
    "Consider backwards compatibility.",
    "Performance targets must be met.",
]


def op_project_list(rng, st):
    return ("project-list", "project")


def op_project_get(rng, st):
    section = rng.choice(["metadata"] + st.project_sections)
    return ("project-get", f"project {section} get")


def op_project_add(rng, st):
    if not st.project_sections:
        return op_project_new_section(rng, st)
    section = rng.choice(st.project_sections)
    text = rng.choice(SECTION_TEXTS)
    return ("project-add", f"project {section} add {esc(text)}")


def op_project_replace(rng, st):
    if not st.project_sections:
        return op_project_new_section(rng, st)
    section = rng.choice(st.project_sections)
    text = rng.choice(SECTION_TEXTS)
    return ("project-replace", f"project {section} replace --force {esc(text)}")


def op_project_new_section(rng, st):
    available = [s for s in SECTION_NAMES if s not in st.project_sections]
    if not available:
        return op_project_add(rng, st)
    section = rng.choice(available)
    text = rng.choice(SECTION_TEXTS)
    st.project_sections.append(section)
    return ("project-new", f"project {section} add {esc(text)}")


def op_help(rng, st):
    variant = rng.choice(["bare", "command"])
    if variant == "bare":
        alias = rng.choice(["help", "h"])
        return ("help", alias)
    cmd = rng.choice(["list", "create", "mod", "move", "attr",
                       "comment", "status", "close", "check", "fix",
                       "edit", "help", "dsl", "+", "~", "h"])
    return ("help-cmd", f"help {cmd}")


def op_replace_body(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(BODY_TEXTS)
    return ("replace-body", f"{q(tid, rng)} replace --force {esc(text)}")


def op_comment_del(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    st.comment_counts[tid] = 0
    return ("comment-del", f"{q(tid, rng)} comment del")


def op_attr_del(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    attr = rng.choice(["estimate", "assignee", "links"])
    return ("attr-del", f"{q(tid, rng)} attr {attr} del")


def op_list_text(rng, st):
    word = rng.choice(["attention", "blocking", "review", "edge", "staging",
                        "priority", "context", "unknown"])
    return ("list-text", f"list --text {esc(word)}")


def op_list_attr(rng, st):
    expr = rng.choice(["estimate<=\"2h\"", "estimate>=\"3h\"", "status==\"open\"",
                        "estimate==\"1h\""])
    return ("list-attr", f"list --attr {esc(expr)}")


def op_list_self(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return ("list-self", "list --self")
    return ("list-self", f"list {q(tid)} --self")


def op_list_n(rng, st):
    n = rng.randint(1, 5)
    return ("list-n", f"list -n {n}")


def op_create_quiet(rng, st):
    title = gen_title(rng)
    estimate = rng.choice(ESTIMATES)
    expr = f'title="{title}", estimate="{estimate}"'
    st.add_ticket(0)
    return ("create-quiet", f"create --quiet {esc(expr)}")


def op_alias_add(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(BODY_TEXTS)
    return ("alias-add", f"{q(tid, rng)} + {esc(text)}")


def op_alias_mod(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    p = rng.choice(ESTIMATES)
    return ("alias-mod", f"{q(tid, rng)} ~ {esc(f'set(estimate={repr(p)})')}")


EDIT_TEXTS = [
    "Updated via editor.",
    "Revised description.",
    "New content from edit.",
    "Reworked plan details.",
    "First line.\n\nThird line after blank.",
    "Paragraph one.\nParagraph two.",
]


def op_edit(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    mode = rng.choice(["append", "replace-body", "prepend-body"])
    text = rng.choice(EDIT_TEXTS)
    return ("edit", f"{q(tid, rng)} edit", mode, text)


def op_edit_recursive(rng, st):
    tid = st.pick(rng)
    if tid is None:
        return None
    mode = rng.choice(["append", "replace-body", "prepend-body"])
    text = rng.choice(EDIT_TEXTS)
    return ("edit-r", f"-r {q(tid, rng)} edit", mode, text)


def op_recursive_mod(rng, st):
    """Recursively mod a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    p = rng.choice(ESTIMATES)
    return ("r-mod", f"{q(tid, rng)} -r mod {esc(f'set(estimate={repr(p)})')}")


def op_recursive_status(rng, st):
    """Recursively set status on a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    s = rng.choice(STATUSES_OPEN)
    # Update tracked status for tid and all descendants
    for d in [tid] + st._descendants(tid):
        st.statuses[d] = s
    return ("r-status", f"{q(tid, rng)} -r status {esc(s)}")


def op_recursive_close(rng, st):
    """Recursively close a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    res = rng.choice(STATUSES_CLOSED)
    for d in [tid] + st._descendants(tid):
        st.statuses[d] = res
    return ("r-close", f"{q(tid, rng)} -r close {esc(res)}")


def op_recursive_add(rng, st):
    """Recursively add body text to a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(BODY_TEXTS)
    return ("r-add", f"{q(tid, rng)} -r add {esc(text)}")


def op_recursive_replace(rng, st):
    """Recursively replace body text on a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(BODY_TEXTS)
    return ("r-replace", f"{q(tid, rng)} -r replace --force {esc(text)}")


def op_recursive_comment_add(rng, st):
    """Recursively add comment to a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    text = rng.choice(COMMENT_TEXTS)
    for d in [tid] + st._descendants(tid):
        st.comment_counts[d] = st.comment_counts.get(d, 0) + 1
    return ("r-comment-add", f"{q(tid, rng)} -r comment add {esc(text)}")


def op_recursive_attr_replace(rng, st):
    """Recursively set attribute on a ticket and all descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    p = rng.choice(ESTIMATES)
    return ("r-attr-replace", f"{q(tid, rng)} -r attr estimate replace --force {esc(p)}")


def op_recursive_get(rng, st):
    """Get -r -q: recursively get filtered descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    status = rng.choice(STATUSES_OPEN + STATUSES_CLOSED)
    return ("r-q-get", f"{q(tid, rng)} -r -q {esc(f'status == {repr(status)}')} get")


def op_q_filter_close(rng, st):
    """Recursively close only matching descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    res = rng.choice(STATUSES_CLOSED)
    # We can't track exactly which descendants match, just update tid's status
    # for tracking (the filter may or may not match it)
    status_expr = 'status == "open"'
    return ("r-q-close", f"{q(tid, rng)} -r -q {esc(status_expr)} close {esc(res)}")


def op_q_filter_del(rng, st):
    """Recursively delete only matching descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    # Delete closed descendants only — can't easily track state, so just run it
    status_expr = 'status == "done"'
    return ("r-q-del", f"{q(tid, rng)} -r -q {esc(status_expr)} del")


def op_q_filter_mod(rng, st):
    """Recursively mod only matching descendants."""
    tid = st.pick(rng)
    if tid is None:
        return None
    p = rng.choice(ESTIMATES)
    status = rng.choice(STATUSES_OPEN)
    return ("r-q-mod", f"{q(tid, rng)} -r -q {esc(f'status == {repr(status)}')} mod {esc(f'set(estimate={repr(p)})')}")


CONFLICT_VARIANTS = [
    # Attribute conflict: both sides changed estimate/status with timestamps
    {
        "label": "attr",
        "ours": [
            "  estimate: {e1}",
            "  status: in-progress",
            "  updated: 2025-01-15T10:00:00Z",
        ],
        "theirs": [
            "  estimate: {e2}",
            "  status: open",
            "  updated: 2025-01-15T11:00:00Z",
        ],
    },
    # Body text conflict: both sides edited description
    {
        "label": "body",
        "ours": ["  This is the original description."],
        "theirs": ["  This is a revised description."],
    },
    # Mixed: one side adds a line, other changes existing
    {
        "label": "mixed",
        "ours": [
            "  assignee: alice",
            "  estimate: {e1}",
        ],
        "theirs": [
            "  assignee: bob",
            "  estimate: {e2}",
            "  updated: 2025-02-01T09:00:00Z",
        ],
    },
]


def _make_conflict_block(rng):
    """Generate a conflict marker block with randomized content."""
    variant = rng.choice(CONFLICT_VARIANTS)
    e1 = rng.choice(ESTIMATES)
    e2 = rng.choice([e for e in ESTIMATES if e != e1] or ESTIMATES)
    branch_ours = rng.choice(["main", "master", "HEAD"])
    branch_theirs = rng.choice(["feature/update", "fix/patch", "dev"])

    ours = [line.format(e1=e1, e2=e2) for line in variant["ours"]]
    theirs = [line.format(e1=e1, e2=e2) for line in variant["theirs"]]

    lines = [f"<<<<<<< {branch_ours}"]
    lines.extend(ours)
    lines.append("=======")
    lines.extend(theirs)
    lines.append(f">>>>>>> {branch_theirs}")
    return variant["label"], lines


def op_resolve(rng, st):
    if not st.alive:
        return None

    # Pick a random ticket to inject the conflict after
    tid = st.pick(rng)
    num_conflicts = rng.randint(1, 3)

    # Build the injection: a sed script that inserts conflict markers
    # after the first occurrence of {#<tid>} in the plan file.
    all_blocks = []
    labels = []
    for _ in range(num_conflicts):
        label, block = _make_conflict_block(rng)
        labels.append(label)
        all_blocks.extend(block)

    # Escape for sed 'a\' append: backslash-escape backslashes and ampersands
    sed_text = "\\n".join(all_blocks)
    # Build raw bash: inject conflict markers then run resolve then check
    bash_lines = [
        f'# inject {num_conflicts} conflict(s) ({",".join(labels)}) near #{tid}',
        f"CONFLICT_BLOCK=$(cat <<'CONFLICT_EOF'",
    ]
    bash_lines.extend(all_blocks)
    bash_lines.append("CONFLICT_EOF")
    bash_lines.append(")")
    # Append conflict block near end of file (safer than targeting a specific line)
    bash_lines.append(
        'PLAN_CONTENT=$(cat "$PLAN_FILE")'
    )
    bash_lines.append(
        'printf "%s\\n%s\\n" "$PLAN_CONTENT" "$CONFLICT_BLOCK" > "$PLAN_FILE"'
    )

    return ("resolve", "resolve", "raw", bash_lines)


def op_project_del(rng, st):
    if not st.project_sections:
        return None
    section = rng.choice(st.project_sections)
    st.project_sections.remove(section)
    return ("project-del", f"project {section} del")


def op_multi_status(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    s = rng.choice(STATUSES_OPEN)
    for tid in ids:
        st.statuses[tid] = s
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-status", f"{id_args} status {esc(s)}")


def op_multi_close(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    res = rng.choice(STATUSES_CLOSED)
    for tid in ids:
        st.statuses[tid] = res
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-close", f"{id_args} close {esc(res)}")


def op_multi_mod(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    p = rng.choice(ESTIMATES)
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-mod", f"{id_args} mod {esc(f'set(estimate={repr(p)})')}")


def op_multi_add_body(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    text = rng.choice(BODY_TEXTS)
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-add", f"{id_args} add {esc(text)}")


def op_multi_del(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    for tid in ids:
        st.remove_ticket(tid)
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-del", f"-r {id_args} del")


def op_multi_comment_add(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    text = rng.choice(COMMENT_TEXTS)
    for tid in ids:
        st.comment_counts[tid] = st.comment_counts.get(tid, 0) + 1
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-comment-add", f"{id_args} comment add {esc(text)}")


def op_multi_replace_body(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    text = rng.choice(BODY_TEXTS)
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-replace", f"{id_args} replace --force {esc(text)}")


def op_multi_attr_replace(rng, st):
    if len(st.alive) < 2:
        return None
    ids = rng.sample(st.alive, min(rng.randint(2, 3), len(st.alive)))
    p = rng.choice(ESTIMATES)
    id_args = " ".join(q(tid, rng) for tid in ids)
    return ("multi-attr-replace", f"{id_args} attr estimate replace --force {esc(p)}")


def op_semicolon_varied(rng, st):
    """Varied semicolon chains beyond the basic mod+get."""
    if len(st.alive) < 2:
        return None
    a, b = st.pick2(rng)
    variant = rng.choice(["status_get", "add_comment", "close_list", "mod_mod"])
    if variant == "status_get":
        s = rng.choice(STATUSES_OPEN)
        st.statuses[a] = s
        return ("semi-status-get",
                f"{q(a, rng)} status {esc(s)} ';' {q(a, rng)} get")
    elif variant == "add_comment":
        text = rng.choice(BODY_TEXTS)
        ctext = rng.choice(COMMENT_TEXTS)
        st.comment_counts[a] = st.comment_counts.get(a, 0) + 1
        return ("semi-add-comment",
                f"{q(a, rng)} add {esc(text)} ';' {q(a, rng)} comment add {esc(ctext)}")
    elif variant == "close_list":
        res = rng.choice(STATUSES_CLOSED)
        st.statuses[a] = res
        return ("semi-close-list",
                f"{q(a, rng)} close {esc(res)} ';' list")
    elif variant == "mod_mod":
        p1 = rng.choice(ESTIMATES)
        p2 = rng.choice(ESTIMATES)
        return ("semi-mod-mod",
                f"{q(a, rng)} mod {esc(f'set(estimate={repr(p1)})')} ';' {q(b, rng)} mod {esc(f'set(estimate={repr(p2)})')}")


def op_create_and_list(rng, st):
    title = gen_title(rng)
    estimate = rng.choice(ESTIMATES)
    expr = f'title="{title}", estimate="{estimate}"'
    st.add_ticket(0)
    return ("create+list", f"create {esc(expr)} ';' list")


# Weighted operation table
OPERATIONS = [
    (op_create,          20),
    (op_list,            10),
    (op_get,              8),
    (op_status,           8),
    (op_close,            5),
    (op_mod,             10),
    (op_add_body,         5),
    (op_comment_add,      8),
    (op_comment_get,      4),
    (op_attr_get,         5),
    (op_attr_replace,     5),
    (op_link,             5),
    (op_reorder,          6),
    (op_move,             5),
    (op_del,              3),
    (op_check,               3),
    (op_fix,                 2),
    (op_multi_get,           3),
    (op_multi_status,        3),
    (op_multi_close,         2),
    (op_multi_mod,           3),
    (op_multi_add_body,      2),
    (op_multi_del,           2),
    (op_multi_comment_add,   2),
    (op_multi_replace_body,  2),
    (op_multi_attr_replace,  2),
    (op_semicolon,           3),
    (op_semicolon_varied,    3),
    (op_create_and_list,     2),
    (op_project_list,        3),
    (op_project_get,         3),
    (op_project_add,         3),
    (op_project_replace,     2),
    (op_project_new_section, 2),
    (op_project_del,         2),
    (op_help,                3),
    (op_replace_body,        3),
    (op_comment_del,         2),
    (op_attr_del,            3),
    (op_list_text,           3),
    (op_list_attr,           3),
    (op_list_self,           2),
    (op_list_n,              3),
    (op_create_quiet,        3),
    (op_alias_add,           3),
    (op_alias_mod,           3),
    (op_edit,                3),
    (op_edit_recursive,      3),
    (op_resolve,             3),
    (op_recursive_mod,       3),
    (op_recursive_status,    3),
    (op_recursive_close,     2),
    (op_recursive_add,       2),
    (op_recursive_replace,   2),
    (op_recursive_comment_add, 2),
    (op_recursive_attr_replace, 2),
    (op_recursive_get,       2),
    (op_q_filter_close,      2),
    (op_q_filter_del,        2),
    (op_q_filter_mod,        2),
]


def build_weighted_table():
    table = []
    for func, weight in OPERATIONS:
        table.extend([func] * weight)
    return table


BASH_HEADER = r'''#!/usr/bin/env bash
# Auto-generated stress test for plan.py
# Seed: {seed}, Operations: {num_ops}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAN_PY="$SCRIPT_DIR/plan.py"
TEST_EDIT="$SCRIPT_DIR/test_edit.py"
TMPDIR_BASE=$(mktemp -d)
PLAN_FILE="$TMPDIR_BASE/stress_test.md"
export PLAN_MD="$PLAN_FILE"
PASS=0
FAIL=0
WARN=0
ERRORS=""

cleanup() {{
    rm -rf "$TMPDIR_BASE"
}}
trap cleanup EXIT

run_plan() {{
    local desc="$1"
    shift
    local stderr_file="$TMPDIR_BASE/stderr.tmp"
    if python3 "$PLAN_PY" "$@" > /dev/null 2>"$stderr_file"; then
        PASS=$((PASS + 1))
    else
        local rc=$?
        local stderr_content
        stderr_content=$(cat "$stderr_file")
        # Distinguish clean errors (Error:) from crashes (tracebacks)
        if echo "$stderr_content" | grep -q "^Traceback\|^  File "; then
            FAIL=$((FAIL + 1))
            ERRORS="${{ERRORS}}CRASH [op ${{PASS}}+${{FAIL}}+${{WARN}}]: ${{desc}}\n  exit=${{rc}} stderr: ${{stderr_content}}\n"
        elif echo "$stderr_content" | grep -q "^Error:"; then
            WARN=$((WARN + 1))
        else
            FAIL=$((FAIL + 1))
            ERRORS="${{ERRORS}}FAIL [op ${{PASS}}+${{FAIL}}+${{WARN}}]: ${{desc}}\n  exit=${{rc}} stderr: ${{stderr_content}}\n"
        fi
    fi
}}

'''

BASH_FOOTER = r'''echo "========================="
echo "Stress test complete"
echo "Seed: {seed}, Operations: {num_ops}"
echo "Passed: $PASS / Warned: $WARN / Failed: $FAIL"
if [ -n "$ERRORS" ]; then
    echo ""
    echo "Failures:"
    echo -e "$ERRORS"
fi
echo "========================="

# Validate final file state
if [ -f "$PLAN_FILE" ]; then
    echo "Final file check:"
    if python3 "$PLAN_PY" check > /dev/null 2>&1; then
        echo "  File check: PASS"
    else
        echo "  File check: FAIL"
        FAIL=$((FAIL + 1))
    fi
fi

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
'''


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <seed> <num_operations>", file=sys.stderr)
        sys.exit(1)

    seed = int(sys.argv[1])
    num_ops = int(sys.argv[2])
    rng = random.Random(seed)
    st = State()
    weighted = build_weighted_table()

    # Generate operations
    generated = []

    for _ in range(num_ops):
        func = rng.choice(weighted)
        result = func(rng, st)
        if result is not None:
            generated.append(result)

    # Ensure at least one ticket exists at the start
    if not generated or generated[0][0] != "create":
        title = gen_title(rng)
        expr = f'title="{title}", estimate="3h"'
        generated.insert(0, ("create-bootstrap", f"create {esc(expr)}"))

    # Output
    print(BASH_HEADER.format(seed=seed, num_ops=num_ops))

    for idx, entry in enumerate(generated, 1):
        desc = entry[0]
        cmd = entry[1]
        if len(entry) >= 3 and entry[2] == "raw":
            # Raw bash block: (desc, cmd, "raw", bash_lines)
            bash_lines = entry[3]
            print(f"# Op {idx}: {desc}")
            for line in bash_lines:
                print(line)
            print(f'run_plan "{idx}:{desc}" {cmd}')
        elif len(entry) == 4:
            # Edit operation: (desc, cmd, mode, text)
            mode = entry[2]
            text = entry[3]
            print(f"# Op {idx}: {desc}")
            print(f'EDITOR="$TEST_EDIT" EDIT_MODE={mode} EDIT_CONTENT={esc(text)} run_plan "{idx}:{desc}" {cmd}')
        else:
            print(f"# Op {idx}: {desc}")
            print(f'run_plan "{idx}:{desc}" {cmd}')
        print()

    print(BASH_FOOTER.format(seed=seed, num_ops=num_ops))


if __name__ == "__main__":
    main()
