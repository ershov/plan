# ---------------------------------------------------------------------------
# Merge Engine (structure-aware three-way merge)
# ---------------------------------------------------------------------------
#
# Pure engine: no git, no filesystem, no CLI. Operates on in-memory Project
# trees produced by parse(). It is concatenated into plan.py after the data
# model (040), utils (030), bulk (070), serialize (080), rank (100) and link
# (110) modules, so it may freely use the names they define.

import hashlib as _hashlib

# Sentinel: a side that removed (deleted) a node.
DELETED = "<DELETED>"

# Sentinel field name for a whole-node (modify/delete) conflict.
NODE_FIELD = "<node>"

# Auto-maintained timestamp attrs. These are NEVER allowed to conflict: a
# co-edit of any field would otherwise make `updated` diverge and spuriously
# conflict. They are excluded from conflict detection (and from the
# modify-vs-delete "was it edited" test) and merged by rule instead:
#   updated -> latest of base/mine/theirs
#   created -> earliest of base/mine/theirs (normally base)
TIMESTAMP_ATTRS = ("updated", "created")


def normalize_conflict_text(text):
    """Normalize text for checksum/identity comparison.

    - CRLF -> LF
    - strip trailing whitespace on each line
    - strip leading and trailing blank lines
    """
    if text is None:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[start:end])


def conflict_sum(text):
    """First 8 hex chars of sha256(normalize_conflict_text(text))."""
    norm = normalize_conflict_text(text)
    return _hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


class Conflict:
    """A single merge conflict.

    Fields mirror the design's "Conflict model" section.
    """

    def __init__(self, id, node_id, node_kind, field, ctype,
                 base_value, mine_value, theirs_value,
                 mine_lines=None, theirs_lines=None):
        self.id = id
        self.node_id = node_id          # stable id string, e.g. "12" / "7:comment:9"
        self.node_kind = node_kind      # "ticket" | "comment"
        self.field = field              # "title"/"status"/<attr>/"body"/"parent"/NODE_FIELD
        self.ctype = ctype              # "field" | "text" | "modify-delete"
        self.base_value = base_value    # str | None
        self.mine_value = mine_value    # str | None (DELETED sentinel for removal)
        self.theirs_value = theirs_value
        self.mine_lines = mine_lines    # (start, end) | None (advisory)
        self.theirs_lines = theirs_lines

    def key(self):
        """Resolution key: (node_id, field)."""
        return (str(self.node_id), self.field)

    def __repr__(self):
        return (f"Conflict(id={self.id}, node={self.node_id!r}, "
                f"field={self.field!r}, ctype={self.ctype!r})")


class MergeResult:
    """Result of merge_trees()."""

    def __init__(self, project, conflicts, renumber_map):
        self.project = project              # valid merged Project (mine defaults)
        self.conflicts = conflicts          # list[Conflict]
        self.renumber_map = renumber_map    # {old_int_id: new_int_id} on renumbered side


# ---------------------------------------------------------------------------
# Helpers: extracting comparable field values from nodes
# ---------------------------------------------------------------------------

def _ticket_index(project):
    """Map str(id) -> Ticket for every ticket in the project (recursive)."""
    out = {}

    def walk(tickets):
        for t in tickets:
            out[str(t.node_id)] = t
            walk(t.children)

    if project is not None:
        walk(project.tickets)
    return out


def _comment_index(project):
    """Map comment-id -> (Comment, owning Ticket) for all comments (recursive)."""
    out = {}

    def walk_comments(comments, ticket):
        for c in comments:
            out[str(c.node_id)] = (c, ticket)
            walk_comments(c.children, ticket)

    def walk_tickets(tickets):
        for t in tickets:
            if t.comments is not None:
                walk_comments(t.comments.comments, t)
            walk_tickets(t.children)

    if project is not None:
        walk_tickets(project.tickets)
    return out


def _body_text(node):
    """Position-independent body text of a ticket/comment (dedented)."""
    return textwrap.dedent("\n".join(node.body_lines))


def _parent_id_of(ticket):
    """Stable parent id string, or None for a top-level ticket."""
    p = ticket.parent
    if p is not None and isinstance(p, Ticket):
        return str(p.node_id)
    return None


def _ticket_scalar_fields(ticket, include_timestamps=True):
    """Return the comparable scalar field map for a ticket.

    Keys: 'title', 'type' + every attr key. `links` is treated as a normal attr
    (we compare its serialized string field-by-field like any other attr).
    When include_timestamps is False, the auto-maintained timestamp attrs are
    omitted so they never participate in conflict detection.
    """
    fields = {
        "title": ticket.title,
        "type": ticket.ticket_type,
    }
    for k, v in ticket.attrs.items():
        if k == "move":
            continue
        if not include_timestamps and k in TIMESTAMP_ATTRS:
            continue
        fields[k] = v
    return fields


def _merge_timestamp(key, bv, mv, tv):
    """Merge a timestamp attr by rule. Returns the chosen value, or None.

    `updated` -> the latest (max) of the present values; `created` -> the
    earliest (min). Values use the fixed 'YYYY-MM-DD HH:MM:SS TZ' format, which
    sorts chronologically as plain strings.
    """
    present = [v for v in (bv, mv, tv) if v is not None]
    if not present:
        return None
    if key == "updated":
        return max(present)
    # created (or any other timestamp attr) -> earliest
    return min(present)


def _max_used_id(base, mine, theirs):
    """Highest integer ticket id used across the three projects (0 if none)."""
    hi = 0
    for p in (base, mine, theirs):
        if p is None:
            continue
        for tid in _ticket_index(p):
            try:
                hi = max(hi, int(tid))
            except (ValueError, TypeError):
                pass
    return hi


# ---------------------------------------------------------------------------
# Reference rewriting (reuse of the bulk substitution approach)
# ---------------------------------------------------------------------------

def _rewrite_id_mentions(text, id_map):
    """Rewrite '#N' mentions in free text, word-boundary safe.

    Mirrors src/070-bulk.py::_substitute_bulk_text: each old id is replaced by
    its new id only when not followed by another id-character, so '#4' inside
    '#42' is never touched. Replacements happen against the original ids in one
    pass per id using non-overlapping placeholders to avoid chained rewrites
    (e.g. 4->5 then 5->6 must not turn an original #4 into #6).
    """
    if not id_map:
        return text
    # Two-phase substitution with unique sentinels to prevent re-substitution.
    sentinels = {}
    result = text
    for i, (old, new) in enumerate(id_map.items()):
        sentinel = "\x00MERGEID%d\x00" % i
        sentinels[sentinel] = "#%d" % new
        result = re.sub(r'#%d(?![a-zA-Z0-9_-])' % old,
                        sentinel, result)
    for sentinel, real in sentinels.items():
        result = result.replace(sentinel, real)
    return result


def _rewrite_body_lines(node, id_map):
    """Rewrite #N mentions across a node's body_lines in place."""
    if not id_map or not node.body_lines:
        return
    new_lines = []
    changed = False
    for line in node.body_lines:
        rewritten = _rewrite_id_mentions(line, id_map)
        if rewritten != line:
            changed = True
        new_lines.append(rewritten)
    if changed:
        node.body_lines = new_lines
        node.dirty = True


def _rewrite_links_attr(ticket, id_map):
    """Rewrite both-direction link targets in a ticket's links attr."""
    raw = ticket.get_attr("links", "")
    if not raw:
        return
    links = _parse_links(raw)
    changed = False
    for ltype, ids in links.items():
        new_ids = []
        for tid in ids:
            if tid in id_map:
                new_ids.append(id_map[tid])
                changed = True
            else:
                new_ids.append(tid)
        links[ltype] = new_ids
    if changed:
        ticket.set_attr("links", _serialize_links(links))


def _renumber_side(project, id_map):
    """Apply an old->new ticket-id remapping to an entire project in place.

    Rewrites: ticket node_ids, parent nesting (parent ids follow automatically
    via the object graph; only node_id needs changing), comment container and
    comment ids whose ticket was renumbered, links attrs in both directions,
    and #N mentions in body and comment text.
    """
    if not id_map:
        return

    # 1. Rewrite ticket node_ids and their comment subtree ids.
    def renumber_ticket(t):
        old = t.node_id
        if old in id_map:
            new = id_map[old]
            t.node_id = new
            t.dirty = True
            # comment container + comment ids carry the ticket id prefix
            if t.comments is not None:
                _retarget_comment_ids(t.comments, old, new)
        for child in t.children:
            renumber_ticket(child)

    def walk(tickets):
        for t in tickets:
            renumber_ticket(t)

    walk(project.tickets)

    # 2. Rewrite links (both directions) and #N body mentions on EVERY ticket,
    #    because a renumbered ticket may be referenced from anywhere.
    def walk_rewrite(tickets):
        for t in tickets:
            _rewrite_links_attr(t, id_map)
            _rewrite_body_lines(t, id_map)
            if t.comments is not None:
                _rewrite_comment_bodies(t.comments, id_map)
            walk_rewrite(t.children)

    walk_rewrite(project.tickets)

    # 3. Rebuild id_map registration.
    _reindex(project)


def _retarget_comment_ids(comments_node, old_tid, new_tid):
    """When a ticket is renumbered old_tid->new_tid, update its comment ids."""
    old_prefix = "%s:comment:" % old_tid
    new_prefix = "%s:comment:" % new_tid
    if comments_node.node_id == "%s:comments" % old_tid:
        comments_node.node_id = "%s:comments" % new_tid
        comments_node.dirty = True

    def walk(comments):
        for c in comments:
            if isinstance(c.node_id, str) and c.node_id.startswith(old_prefix):
                c.node_id = new_prefix + c.node_id[len(old_prefix):]
                c.dirty = True
            walk(c.children)

    walk(comments_node.comments)


def _rewrite_comment_bodies(comments_node, id_map):
    """Rewrite #N mentions in all comment titles/bodies under a container."""
    def walk(comments):
        for c in comments:
            new_title = _rewrite_id_mentions(c.title, id_map)
            if new_title != c.title:
                c.title = new_title
                c.dirty = True
            _rewrite_body_lines(c, id_map)
            walk(c.children)

    walk(comments_node.comments)


def _reindex(project):
    """Rebuild project.id_map from the current tree."""
    project.id_map = {}
    project.register(project)
    for sid, sec in project.sections.items():
        project.register(sec)

    def walk(tickets):
        for t in tickets:
            project.register(t)
            if t.comments is not None:
                project.register(t.comments)

                def walk_comments(comments):
                    for c in comments:
                        project.register(c)
                        walk_comments(c.children)

                walk_comments(t.comments.comments)
            walk(t.children)

    walk(project.tickets)


# ---------------------------------------------------------------------------
# Collision detection + renumber planning
# ---------------------------------------------------------------------------

def _plan_ticket_renumber(base, mine, theirs, renumber, hi):
    """Decide which colliding new ticket ids on the renumber side get reassigned.

    An independent-creation collision: a ticket id that is ABSENT from base but
    present in BOTH mine and theirs. The renumber side's copy gets a fresh id.

    Returns id_map ({old_int_id: new_int_id}).
    """
    base_idx = _ticket_index(base)
    mine_idx = _ticket_index(mine)
    theirs_idx = _ticket_index(theirs)

    side_idx = theirs_idx if renumber == "theirs" else mine_idx
    other_idx = mine_idx if renumber == "theirs" else theirs_idx

    id_map = {}
    counter = hi + 1
    # Deterministic order: ascending numeric id.
    colliding = []
    for sid in side_idx:
        if sid in base_idx:
            continue
        if sid in other_idx:
            try:
                colliding.append(int(sid))
            except (ValueError, TypeError):
                pass
    for old in sorted(colliding):
        id_map[old] = counter
        counter += 1
    return id_map


def _plan_comment_renumber(base, mine, theirs, renumber):
    """Decide which colliding new comment ids on the renumber side get bumped.

    A comment-id collision: a comment id ABSENT from base but present in BOTH
    sides on the SAME surviving ticket. We renumber the renumber side's comment
    to a fresh per-ticket number above the high-water mark of that ticket's
    comment numbers across both sides (+base).

    Returns {old_comment_id_str: new_comment_id_str}.
    """
    base_c = _comment_index(base)
    mine_c = _comment_index(mine)
    theirs_c = _comment_index(theirs)

    side_c = theirs_c if renumber == "theirs" else mine_c
    other_c = mine_c if renumber == "theirs" else theirs_c

    # Group colliding comment ids by their (original) ticket id.
    def parse_cid(cid):
        # "T:comment:N" -> (T_str, N_int) or None
        m = re.match(r'^(.+):comment:(\d+)$', cid)
        if not m:
            return None
        return m.group(1), int(m.group(2))

    colliding = []  # list of (ticket_str, n_int, old_cid)
    for cid in side_c:
        if cid in base_c:
            continue
        if cid in other_c:
            parsed = parse_cid(cid)
            if parsed:
                colliding.append((parsed[0], parsed[1], cid))

    if not colliding:
        return {}

    # Per-ticket high-water mark of comment numbers across all three trees.
    def hw_for_ticket(tstr):
        hw = 0
        for idx in (base_c, mine_c, theirs_c):
            for cid in idx:
                p = parse_cid(cid)
                if p and p[0] == tstr:
                    hw = max(hw, p[1])
        return hw

    cmap = {}
    counters = {}
    for tstr, n, old_cid in sorted(colliding, key=lambda x: (x[0], x[1])):
        if tstr not in counters:
            counters[tstr] = hw_for_ticket(tstr) + 1
        new_n = counters[tstr]
        counters[tstr] += 1
        cmap[old_cid] = "%s:comment:%d" % (tstr, new_n)
    return cmap


def _apply_comment_renumber(project, comment_id_map):
    """Apply a comment-id remapping (string->string) to a project in place."""
    if not comment_id_map:
        return
    cidx = _comment_index(project)
    for old_cid, new_cid in comment_id_map.items():
        entry = cidx.get(old_cid)
        if entry is not None:
            comment, _ticket = entry
            comment.node_id = new_cid
            comment.dirty = True
    _reindex(project)


# ---------------------------------------------------------------------------
# Three-way field merge
# ---------------------------------------------------------------------------

def _three_way_field(base_val, mine_val, theirs_val):
    """Resolve a single scalar field. Returns ('value', v) or ('conflict',).

    Values are strings or None (absent). Comparison is on normalized text only
    for deciding equality of present values; the returned value is the raw one.
    """
    bn = None if base_val is None else normalize_conflict_text(base_val)
    mn = None if mine_val is None else normalize_conflict_text(mine_val)
    tn = None if theirs_val is None else normalize_conflict_text(theirs_val)

    if mn == tn:
        # Same on both sides (covers identical change and no-change).
        return ("value", mine_val)
    # They differ. Did exactly one side change relative to base?
    mine_changed = (mn != bn)
    theirs_changed = (tn != bn)
    if mine_changed and not theirs_changed:
        return ("value", mine_val)
    if theirs_changed and not mine_changed:
        return ("value", theirs_val)
    # Both changed differently -> conflict.
    return ("conflict",)


# ---------------------------------------------------------------------------
# Building the merged tree
# ---------------------------------------------------------------------------

def _empty_project():
    p = Project()
    _bootstrap_project(p)
    return p


def merge_trees(base, mine, theirs, *, renumber="theirs",
                prefer=None, resolutions=None, two_way=False):
    """Structure-aware three-way merge of three Project trees.

    Returns a MergeResult. The merged project always uses the MINE value at any
    conflict so it serializes to a usable file even before resolution.

    two_way mode (used when reconciling from raw git conflict markers, where
    there is no common ancestor): a shared ID means *the same diverged node*,
    NOT an independent-creation collision. In this mode:
      - collision renumbering is SKIPPED entirely (no `renumber` behavior);
      - the base is empty, so a shared ID is field-merged with an empty base
        and any divergence conflicts (field/text); timestamps still merge by
        rule and never conflict;
      - an ID present on only one side is simply added (taken);
      - there are no modify/delete conflicts (no base to detect deletion).

    None-robustness: any of base/mine/theirs may be None and is treated as an
    empty Project (covers the merge-driver's empty-%A and file-new-on-a-side
    cases without crashing).
    """
    if renumber not in ("mine", "theirs"):
        raise ValueError("renumber must be 'mine' or 'theirs'")
    resolutions = resolutions or {}

    # None-robustness: substitute empty projects for any missing tree.
    if mine is None:
        mine = _empty_project()
    if theirs is None:
        theirs = _empty_project()
    # In two_way mode there is no meaningful base: force an empty one so shared
    # IDs are treated as the same node diverging from nothing.
    if two_way or base is None:
        base = _empty_project()

    # ----- Step 2: plan + apply collision renumbering on the renumber side. ---
    # Skipped entirely in two_way mode (shared IDs are the same node).
    ticket_id_map = {}
    if not two_way:
        hi = _max_used_id(base, mine, theirs)
        side_proj = theirs if renumber == "theirs" else mine

        ticket_id_map = _plan_ticket_renumber(base, mine, theirs, renumber, hi)
        if ticket_id_map:
            _renumber_side(side_proj, ticket_id_map)

        comment_id_map = _plan_comment_renumber(base, mine, theirs, renumber)
        if comment_id_map:
            _apply_comment_renumber(side_proj, comment_id_map)

    # Re-index everything after renumbering.
    base_idx = _ticket_index(base)
    mine_idx = _ticket_index(mine)
    theirs_idx = _ticket_index(theirs)

    conflicts = []
    counter = [1]

    def next_id():
        v = counter[0]
        counter[0] += 1
        return v

    # ----- Build the merged project as a fresh tree. ----------------------
    # We start from mine's structure (we are on mine's branch) and weave in
    # theirs-only nodes. Conflicts default to mine in-tree.
    merged = _build_skeleton(mine)

    # Resolve each ticket and stage its merged field set + presence decision.
    # We mutate the merged tree (copied from mine) in place. New theirs-only
    # tickets get appended.
    merged_idx = _ticket_index(merged)

    def record_field_conflict(node_id, node_kind, field, ctype,
                              base_v, mine_v, theirs_v):
        c = Conflict(next_id(), str(node_id), node_kind, field, ctype,
                     base_v, mine_v, theirs_v)
        conflicts.append(c)
        return c

    # --- Pass A: tickets present in mine (merge fields with base/theirs). ---
    for tid in mine_idx:
        m_t = mine_idx[tid]
        b_t = base_idx.get(tid)
        th_t = theirs_idx.get(tid)
        merged_t = merged_idx[tid]

        if th_t is None:
            # Not on theirs side.
            if b_t is not None:
                # Was in base, theirs deleted it. Did mine edit it?
                if _ticket_changed(b_t, m_t):
                    record_field_conflict(tid, "ticket", NODE_FIELD,
                                          "modify-delete",
                                          _node_repr(b_t), _node_repr(m_t),
                                          DELETED)
                    # Default to mine (keep node) in-tree.
                # else: theirs deleted, mine untouched -> honor delete.
                else:
                    _mark_for_deletion(merged_t)
            # else: mine-only new ticket -> keep as is.
            continue

        # Present on both mine and theirs (maybe base too).
        _merge_ticket_fields(b_t, m_t, th_t, merged_t,
                             record_field_conflict)
        _merge_comments(b_t, m_t, th_t, merged_t,
                        record_field_conflict, next_id)

    # --- Pass B: tickets present in theirs but NOT mine. -----------------
    for tid in theirs_idx:
        if tid in mine_idx:
            continue
        th_t = theirs_idx[tid]
        b_t = base_idx.get(tid)
        if b_t is not None:
            # Was in base, mine deleted it. Did theirs edit it?
            if _ticket_changed(b_t, th_t):
                record_field_conflict(tid, "ticket", NODE_FIELD,
                                      "modify-delete",
                                      _node_repr(b_t), DELETED,
                                      _node_repr(th_t))
                # Default to mine's decision (deletion) in-tree: do not add.
            # else: mine deleted, theirs untouched -> honor delete (skip).
            continue
        # theirs-only NEW ticket -> add it to the merged tree, placed after
        # mine's siblings under the same parent.
        _graft_theirs_ticket(th_t, theirs_idx, merged, merged_idx)

    # Remove tickets marked for deletion.
    _apply_deletions(merged)

    # ----- Apply prefer / resolutions to conflicts. -----------------------
    remaining = _resolve_conflicts(merged, conflicts, prefer, resolutions,
                                   mine_idx, theirs_idx, base_idx)

    # ----- Step 6: ensure tree is serializable; reindex. ------------------
    _finalize_ranks(merged)
    _reindex(merged)

    # ----- Step 7: next_id fixup. -----------------------------------------
    _fix_next_id(merged)

    return MergeResult(merged, remaining, ticket_id_map)


# ---------------------------------------------------------------------------
# Skeleton / cloning
# ---------------------------------------------------------------------------

def _build_skeleton(mine):
    """Deep-copy mine into the merged base tree we will mutate."""
    merged = copy.deepcopy(mine)
    _reindex(merged)
    return merged


def _node_repr(ticket):
    """A human-readable single-string repr of a ticket for modify-delete."""
    out = []
    bullet, content_indent, attr_indent = _ticket_indents(ticket)
    out.append("%s## Ticket: %s: %s {#%s}" %
               (bullet, ticket.ticket_type, ticket.title, ticket.node_id))
    for k, v in ticket.attrs.items():
        if k == "move":
            continue
        out.append("%s%s: %s" % (attr_indent, k, v))
    for bl in ticket.body_lines:
        out.append(bl)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Per-ticket field merge
# ---------------------------------------------------------------------------

def _ticket_changed(a, b):
    """True if any scalar/body/parent field differs between two ticket states.

    Timestamp attrs are excluded: an auto-bumped `updated` must not count as an
    edit for the modify-vs-delete decision.
    """
    fa = _ticket_scalar_fields(a, include_timestamps=False)
    fb = _ticket_scalar_fields(b, include_timestamps=False)
    keys = set(fa) | set(fb)
    for k in keys:
        if normalize_conflict_text(fa.get(k)) != normalize_conflict_text(fb.get(k)):
            return True
    if normalize_conflict_text(_body_text(a)) != normalize_conflict_text(_body_text(b)):
        return True
    if _parent_id_of(a) != _parent_id_of(b):
        return True
    return False


def _merge_ticket_fields(b_t, m_t, th_t, merged_t, record_conflict):
    """Field-by-field three-way merge writing results onto merged_t."""
    b_fields = _ticket_scalar_fields(b_t) if b_t is not None else {}
    m_fields = _ticket_scalar_fields(m_t)
    th_fields = _ticket_scalar_fields(th_t)

    all_keys = set(b_fields) | set(m_fields) | set(th_fields)

    # Decide the final attr set. title/type are stored on the object directly.
    final_attrs = {}
    # Preserve mine's attr ordering, then append theirs-only keys.
    ordered_keys = []
    for k in m_t.attrs:
        if k == "move":
            continue
        if k in ("title", "type"):
            continue
        ordered_keys.append(k)
    for k in th_t.attrs:
        if k == "move":
            continue
        if k in ("title", "type"):
            continue
        if k not in ordered_keys:
            ordered_keys.append(k)
    # base-only keys (deleted on both) won't appear; that's fine.

    for k in all_keys:
        bv = b_fields.get(k)
        mv = m_fields.get(k)
        tv = th_fields.get(k)
        # Timestamp attrs never conflict: merge by rule.
        if k in TIMESTAMP_ATTRS:
            merged_ts = _merge_timestamp(k, bv, mv, tv)
            if merged_ts is not None:
                final_attrs[k] = merged_ts
            continue
        outcome = _three_way_field(bv, mv, tv)
        if k == "title":
            if outcome[0] == "value":
                merged_t.title = outcome[1] if outcome[1] is not None else ""
            else:
                record_conflict(m_t.node_id, "ticket", "title", "field",
                                bv, mv, tv)
                merged_t.title = mv if mv is not None else ""
            continue
        if k == "type":
            if outcome[0] == "value":
                merged_t.ticket_type = outcome[1] if outcome[1] is not None else m_t.ticket_type
            else:
                record_conflict(m_t.node_id, "ticket", "type", "field",
                                bv, mv, tv)
                merged_t.ticket_type = mv if mv is not None else m_t.ticket_type
            continue
        # Regular attr.
        if outcome[0] == "value":
            if outcome[1] is not None:
                final_attrs[k] = outcome[1]
            # None means the attr is deleted on the winning side -> drop it.
        else:
            record_conflict(m_t.node_id, "ticket", k, "field", bv, mv, tv)
            # default to mine; if mine absent, keep absent.
            if mv is not None:
                final_attrs[k] = mv

    # Write attrs back in the chosen order.
    new_attrs = {}
    for k in ordered_keys:
        if k in final_attrs:
            new_attrs[k] = final_attrs[k]
    # Any key present in final_attrs but not ordered (shouldn't happen) appended.
    for k in final_attrs:
        if k not in new_attrs:
            new_attrs[k] = final_attrs[k]
    merged_t.attrs = new_attrs
    merged_t.dirty = True

    # --- body (multiline -> text conflict). ---
    b_body = _body_text(b_t) if b_t is not None else None
    m_body = _body_text(m_t)
    th_body = _body_text(th_t)
    outcome = _three_way_field(b_body, m_body, th_body)
    if outcome[0] == "value":
        _set_body_from_text(merged_t, outcome[1])
    else:
        record_conflict(m_t.node_id, "ticket", "body", "text",
                        b_body, m_body, th_body)
        _set_body_from_text(merged_t, m_body)

    # --- parent (reparent) -> field conflict. ---
    b_par = _parent_id_of(b_t) if b_t is not None else None
    m_par = _parent_id_of(m_t)
    th_par = _parent_id_of(th_t)
    outcome = _three_way_field(b_par, m_par, th_par)
    if outcome[0] == "conflict":
        record_conflict(m_t.node_id, "ticket", "parent", "field",
                        b_par, m_par, th_par)
        # default to mine: merged already mirrors mine's structure.
    # Non-conflict parent moves: merged mirrors mine's structure already; if
    # theirs is the winning change we honor it via reparent below.
    elif outcome[0] == "value":
        winner = outcome[1]
        if winner != m_par:
            _reparent_in_merged(merged_t, winner)


def _set_body_from_text(node, text):
    """Set a node's body_lines from dedented text, re-indenting to its level."""
    if text is None or text == "":
        node.body_lines = []
        node.dirty = True
        return
    indent = " " * (node.indent_level + 2)
    lines = text.split("\n")
    node.body_lines = [(indent + ln) if ln.strip() else "" for ln in lines]
    node.dirty = True


def _reparent_in_merged(merged_t, new_parent_id):
    """Reparent merged_t to new_parent_id (or None) within the merged project."""
    # Find the merged project root via walking up is not available; we rely on
    # the caller having merged_t inside `merged`. We resolve parent by id_map at
    # finalize. For simplicity we re-attach using the existing reparent helper
    # if we can find the project; but merged_t.parent chain gives us access.
    # We attach a pending marker; actual relocation done in _finalize_reparents.
    merged_t._pending_parent = new_parent_id


# ---------------------------------------------------------------------------
# Comments merge (union by id)
# ---------------------------------------------------------------------------

def _merge_comments(b_t, m_t, th_t, merged_t, record_conflict, next_id):
    """Union-by-id comment merge; divergent same-comment body -> field conflict.

    Comments are merged into merged_t.comments (which is mine's copy). Theirs-only
    comments are appended after mine's. Body edits diverging -> conflict.
    """
    b_comments = _flatten_comments(b_t) if b_t is not None else {}
    m_comments = _flatten_comments(m_t)
    th_comments = _flatten_comments(th_t)
    merged_comments = _flatten_comments(merged_t)

    # Merge bodies for comments present on both mine and theirs.
    for cid, (m_c, _mp) in m_comments.items():
        if cid not in th_comments:
            continue
        th_c = th_comments[cid][0]
        b_c = b_comments.get(cid, (None,))[0]
        b_body = _body_text(b_c) if b_c is not None else None
        m_body = _body_text(m_c)
        th_body = _body_text(th_c)
        b_title = b_c.title if b_c is not None else None
        # Title merge.
        t_out = _three_way_field(b_title, m_c.title, th_c.title)
        merged_c = merged_comments.get(cid, (None,))[0]
        if merged_c is None:
            continue
        if t_out[0] == "value":
            merged_c.title = t_out[1] if t_out[1] is not None else merged_c.title
        else:
            record_conflict(cid, "comment", "title", "field",
                            b_title, m_c.title, th_c.title)
            merged_c.title = m_c.title
        # Body merge.
        out = _three_way_field(b_body, m_body, th_body)
        if out[0] == "value":
            _set_body_from_text(merged_c, out[1])
        else:
            record_conflict(cid, "comment", "body", "text",
                            b_body, m_body, th_body)
            _set_body_from_text(merged_c, m_body)

    # Add theirs-only comments (append after mine's at the top level).
    if merged_t.comments is None and th_t.comments is not None:
        # mine had no comments; clone theirs container into merged.
        merged_t.comments = copy.deepcopy(th_t.comments)
        merged_t.comments.dirty = True
        return

    if th_t.comments is None:
        return

    merged_top = merged_t.comments
    existing_ids = set(merged_comments.keys())
    for th_c in th_t.comments.comments:
        if str(th_c.node_id) not in existing_ids:
            clone = copy.deepcopy(th_c)
            _reindent_comment(clone, merged_top.indent_level + 2)
            merged_top.comments.append(clone)
            merged_top.dirty = True
        else:
            # Append theirs-only nested replies under matching comments.
            _merge_nested_comment_children(
                _find_comment(merged_top.comments, str(th_c.node_id)),
                th_c, existing_ids)


def _merge_nested_comment_children(merged_c, th_c, existing_ids):
    """Append theirs-only reply children recursively under a merged comment."""
    if merged_c is None:
        return
    for th_child in th_c.children:
        if str(th_child.node_id) not in existing_ids:
            clone = copy.deepcopy(th_child)
            _reindent_comment(clone, merged_c.indent_level + 2)
            merged_c.children.append(clone)
            merged_c.dirty = True
            existing_ids.add(str(th_child.node_id))
        else:
            child_merged = _find_comment(merged_c.children,
                                         str(th_child.node_id))
            _merge_nested_comment_children(child_merged, th_child, existing_ids)


def _find_comment(comments, cid):
    for c in comments:
        if str(c.node_id) == cid:
            return c
    return None


def _reindent_comment(comment, indent_level):
    """Re-indent a cloned comment subtree to a new base indent level."""
    delta = indent_level - comment.indent_level
    if delta == 0:
        return

    def walk(c, lvl):
        old_body_indent = c.indent_level + 2
        c.indent_level = lvl
        new_body_indent = lvl + 2
        if c.body_lines:
            dedented = textwrap.dedent("\n".join(c.body_lines)).split("\n")
            prefix = " " * new_body_indent
            c.body_lines = [(prefix + ln) if ln.strip() else "" for ln in dedented]
        c.dirty = True
        for child in c.children:
            walk(child, lvl + 2)

    walk(comment, indent_level)


def _flatten_comments(ticket):
    """Map comment-id -> (Comment, parent-Comment-or-None) for a ticket."""
    out = {}
    if ticket is None or ticket.comments is None:
        return out

    def walk(comments, parent):
        for c in comments:
            out[str(c.node_id)] = (c, parent)
            walk(c.children, c)

    walk(ticket.comments.comments, None)
    return out


# ---------------------------------------------------------------------------
# Grafting theirs-only tickets
# ---------------------------------------------------------------------------

def _graft_theirs_ticket(th_t, theirs_idx, merged, merged_idx):
    """Insert a theirs-only ticket subtree into merged, after mine's siblings."""
    # Skip if already grafted (a parent graft pulls children with it).
    if str(th_t.node_id) in merged_idx:
        return
    parent_id = _parent_id_of(th_t)

    clone = copy.deepcopy(th_t)
    # Detach children that are NOT theirs-only-relative-to-merged? No: a
    # theirs-only ticket's whole subtree is theirs-only by construction unless a
    # child id already exists in mine (rare divergent structure). Handle by
    # pruning children that already exist in merged.
    _prune_existing(clone, merged_idx)

    if parent_id is None or parent_id not in merged_idx:
        # Top-level (or parent also theirs-only and not yet present): place at
        # end of top-level list.
        clone.parent = None
        _reindent_ticket(clone, 0)
        clone._rank = _rank_after_all(merged.tickets)
        merged.tickets.append(clone)
    else:
        parent = merged_idx[parent_id]
        clone.parent = parent
        _reindent_ticket(clone, parent.indent_level + 2)
        clone._rank = _rank_after_all(parent.children)
        parent.children.append(clone)
        parent.dirty = True
    clone.dirty = True
    # Register the new subtree in merged_idx.
    _register_subtree(clone, merged_idx)


def _prune_existing(clone, merged_idx):
    """Remove children of clone whose ids already exist in merged."""
    clone.children = [c for c in clone.children
                      if str(c.node_id) not in merged_idx]
    for c in clone.children:
        _prune_existing(c, merged_idx)


def _register_subtree(ticket, merged_idx):
    merged_idx[str(ticket.node_id)] = ticket
    for c in ticket.children:
        _register_subtree(c, merged_idx)


def _reindent_ticket(ticket, indent_level):
    """Re-indent a ticket subtree (and body/comments) to a new base level."""
    old = ticket.indent_level
    if old == indent_level:
        # Still need to recurse in case caller changed nothing but children off.
        pass
    ticket.indent_level = indent_level
    # Re-indent body.
    if ticket.body_lines:
        dedented = textwrap.dedent("\n".join(ticket.body_lines)).split("\n")
        prefix = " " * (indent_level + 2)
        ticket.body_lines = [(prefix + ln) if ln.strip() else "" for ln in dedented]
    # Re-indent comments.
    if ticket.comments is not None:
        _reindent_comment_container(ticket.comments, indent_level + 2)
    ticket.dirty = True
    for child in ticket.children:
        _reindent_ticket(child, indent_level + 2)


def _reindent_comment_container(container, indent_level):
    container.indent_level = indent_level
    container.dirty = True
    for c in container.comments:
        _reindent_comment(c, indent_level + 2)


def _rank_after_all(siblings):
    """Rank that sorts after all current siblings."""
    if not siblings:
        return 0.0
    return max(_get_rank(s) for s in siblings) + 1.0


# ---------------------------------------------------------------------------
# Deletions / reparents finalization
# ---------------------------------------------------------------------------

def _mark_for_deletion(ticket):
    ticket._delete = True


def _apply_deletions(merged):
    """Remove tickets marked with _delete from the merged tree."""
    def filter_list(tickets):
        kept = []
        for t in tickets:
            if getattr(t, "_delete", False):
                continue
            t.children = filter_list(t.children)
            kept.append(t)
        return kept

    merged.tickets = filter_list(merged.tickets)


def _finalize_reparents(merged):
    """Apply pending reparent relocations recorded during field merge."""
    pending = []

    def collect(tickets):
        for t in tickets:
            if hasattr(t, "_pending_parent"):
                pending.append((t, t._pending_parent))
            collect(t.children)

    collect(merged.tickets)
    if not pending:
        return
    idx = _ticket_index(merged)
    for ticket, new_parent_id in pending:
        del ticket._pending_parent
        new_parent = idx.get(new_parent_id) if new_parent_id is not None else None
        if new_parent_id is not None and new_parent is None:
            continue  # target gone; leave in place
        # Avoid cycles: don't reparent under own descendant.
        if new_parent is not None and _is_descendant(new_parent, ticket):
            continue
        _reparent_ticket(ticket, new_parent, merged)


def _is_descendant(candidate, ancestor):
    """True if candidate is ancestor or within ancestor's subtree."""
    if candidate is ancestor:
        return True
    for c in ancestor.children:
        if _is_descendant(candidate, c):
            return True
    return False


def _finalize_ranks(merged):
    """Apply pending reparents, then normalize ranks to positional ints."""
    _finalize_reparents(merged)

    def renorm(tickets):
        ordered = sort_by_rank(tickets)
        for i, t in enumerate(ordered):
            t._rank = float(i)
        # rebuild list in sorted order so serialization is stable
        tickets[:] = ordered
        for t in tickets:
            renorm(t.children)

    renorm(merged.tickets)


# ---------------------------------------------------------------------------
# Conflict resolution (prefer / resolutions)
# ---------------------------------------------------------------------------

def _resolve_conflicts(merged, conflicts, prefer, resolutions,
                       mine_idx, theirs_idx, base_idx):
    """Resolve conflicts via resolutions (per-key) then prefer (fill rest).

    Returns the list of conflicts that remain UNRESOLVED.
    """
    if prefer is None and not resolutions:
        return conflicts

    remaining = []
    for c in conflicts:
        side = None
        rkey = c.key()
        if rkey in resolutions:
            side = resolutions[rkey]
        elif prefer is not None:
            side = prefer
        if side is None:
            remaining.append(c)
            continue
        _apply_resolution(merged, c, side, mine_idx, theirs_idx, base_idx)
    return remaining


def _apply_resolution(merged, c, side, mine_idx, theirs_idx, base_idx):
    """Apply the chosen side for a single conflict onto the merged tree."""
    merged_idx = _ticket_index(merged)

    if c.ctype == "modify-delete":
        # mine_value / theirs_value: one is DELETED, other is node repr.
        mine_deleted = (c.mine_value == DELETED)
        theirs_deleted = (c.theirs_value == DELETED)
        keep = None
        if side == "mine":
            keep = not mine_deleted
        else:
            keep = not theirs_deleted
        merged_t = merged_idx.get(str(c.node_id))
        if keep:
            # Ensure node present with the kept side's content.
            if merged_t is None:
                src_idx = mine_idx if side == "mine" else theirs_idx
                src = src_idx.get(str(c.node_id))
                if src is not None:
                    _graft_theirs_ticket(src, src_idx, merged, merged_idx)
            else:
                # If kept side is theirs, overwrite mine's content with theirs.
                if side == "theirs":
                    src = theirs_idx.get(str(c.node_id))
                    if src is not None:
                        _copy_ticket_content(src, merged_t)
        else:
            if merged_t is not None:
                _mark_for_deletion(merged_t)
                _apply_deletions(merged)
        return

    # Field / text conflict: pick the chosen side's value.
    chosen = c.mine_value if side == "mine" else c.theirs_value

    if c.node_kind == "comment":
        cidx = _comment_index(merged)
        entry = cidx.get(str(c.node_id))
        if entry is None:
            return
        comment = entry[0]
        if c.field == "body":
            _set_body_from_text(comment, chosen)
        elif c.field == "title":
            comment.title = chosen if chosen is not None else comment.title
        return

    merged_t = merged_idx.get(str(c.node_id))
    if merged_t is None:
        return
    if c.field == "title":
        merged_t.title = chosen if chosen is not None else ""
    elif c.field == "type":
        merged_t.ticket_type = chosen if chosen is not None else merged_t.ticket_type
    elif c.field == "body":
        _set_body_from_text(merged_t, chosen)
    elif c.field == "parent":
        if chosen != _parent_id_of(merged_t):
            _reparent_in_merged(merged_t, chosen)
            _finalize_reparents(merged)
    else:
        # attr
        if chosen is None:
            merged_t.del_attr(c.field)
        else:
            merged_t.set_attr(c.field, chosen)
    merged_t.dirty = True


def _copy_ticket_content(src, dst):
    """Copy scalar fields, attrs, body from src ticket onto dst (in place)."""
    dst.title = src.title
    dst.ticket_type = src.ticket_type
    dst.attrs = dict(src.attrs)
    _set_body_from_text(dst, _body_text(src))
    dst.dirty = True


# ---------------------------------------------------------------------------
# next_id fixup
# ---------------------------------------------------------------------------

def _fix_next_id(merged):
    """Set ## Metadata next_id to max(all used ticket ids) + 1."""
    hi = 0
    for tid in _ticket_index(merged):
        try:
            hi = max(hi, int(tid))
        except (ValueError, TypeError):
            pass
    new_next = hi + 1
    merged.next_id = new_next
    if "metadata" in merged.sections:
        merged.sections["metadata"].set_attr("next_id", str(new_next))
