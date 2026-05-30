# ---------------------------------------------------------------------------
# Merge Report (render conflicts -> .reject text; parse edits -> resolutions)
# ---------------------------------------------------------------------------
#
# Pure text: no git, no filesystem, no CLI. Concatenated after the merge engine
# (115), so it may freely use everything defined in 010-115 — in particular
# DELETED, NODE_FIELD, normalize_conflict_text(), conflict_sum() and the
# Conflict / MergeResult classes.
#
# The renderer turns a list[Conflict] into the textual `.reject` file the user
# edits; the parser reads an edited `.reject` back into a resolutions map
# {(node_id, field) -> "mine" | "theirs"} that can be fed straight to
# merge_trees(..., resolutions=...). The contract is "choice only": the user
# selects a side, never edits the content — which the parser enforces via the
# checksums recorded on each conflict header line.
#
# VOCABULARY: the user-facing `.reject` surface speaks `to`/`from` (the side
# merged into / the side merged from); the engine and the resolutions map this
# parser RETURNS keep the historical `mine`/`theirs` names. The `to`<->`mine`,
# `from`<->`theirs` mapping happens entirely inside this file, at render/parse.

import re as _re


class RejectError(Exception):
    """Raised when a `.reject` file is malformed, edited, or unresolved.

    Carries a human-readable message (and, where known, the offending conflict
    id). The CLI layer converts this to a user-facing error + exit code 2.
    """

    def __init__(self, message, conflict_id=None):
        super().__init__(message)
        self.message = message
        self.conflict_id = conflict_id


# Machine-owned line markers. The header/footer and side indicators are not to
# be hand-edited (only chosen between); these constants drive both rendering and
# parsing so the two halves cannot drift.
_REJECT_HEADER_PREFIX = "<<< PLAN-CONFLICT"
_REJECT_FOOTER_PREFIX = ">>> END"
# Precise indicator form, exactly as rendered: '--- to (<branch>) ---' /
# '--- from (<branch>) ---'. We match the rendered shape (not a bare prefix)
# so a side's CONTENT — a body conflict or a node repr that happens to contain a
# markdown rule like '--- topic' — is never mistaken for an indicator. The
# checksums on the header line remain the authoritative arbiter regardless.
# The capture group keeps the engine-internal side name so the rest of the
# parser is unchanged: `to` -> "mine", `from` -> "theirs".
_INDICATOR_RE = _re.compile(r'^--- (to|from) \(.*\) ---\s*$')

# Map the rendered user-facing side word to the engine-internal side name.
_REJECT_SIDE_TO_ENGINE = {"to": "mine", "from": "theirs"}

_HOW_TO_RESOLVE = (
    "# HOW TO RESOLVE\n"
    "#   For each block, keep exactly ONE side (--- to --- or --- from ---)\n"
    "#   and delete the other; or delete a side's indicator line and leave only\n"
    "#   its content. Do NOT edit the content — only choose a side. A side whose\n"
    "#   content is <DELETED> removes the entry. Do not edit the '#' header or\n"
    "#   the <<< / >>> lines.\n"
)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt_lines(lines):
    """Render an advisory (start, end) line range as 'a-b' (default '0-0')."""
    if not lines:
        return "0-0"
    start, end = lines
    return "%s-%s" % (start, end)


def _conflict_node_token(node_id):
    """The 'node=#<id>' token value (without the leading '#').

    Comment ids keep their full form (e.g. '7:comment:9'); ticket ids keep their
    numeric form verbatim. We emit c.node_id as-is after a leading '#'.
    """
    return str(node_id)


def render_reject(conflicts, *, plan_path, base_label, to_label, from_label,
                  to_branch, from_branch, snapshot_dir, plan_version,
                  generated=None):
    """Render conflicts into the textual `.reject` file.

    Arguments (all supplied by the git/CLI layer in Stage 3):
      conflicts     list[Conflict] (the unresolved conflicts from a MergeResult)
      plan_path     path to the plan file, for the '# Plan file' line
      base_label    e.g. 'a1b2c3d' (merge-base short hash)
      to_label      e.g. 'feature-x @ 9f8e7d6' (the `to`/canonical side; engine 'mine')
      from_label    e.g. 'main      @ 1234abc' (the `from` side; engine 'theirs')
      to_branch     branch name shown in the '--- to (<branch>) ---' marker
      from_branch   branch name shown in the '--- from (<branch>) ---' marker
      snapshot_dir  dir holding base/mine/theirs snapshots (advisory line refs)
      plan_version  the plan version string ('vX.Y') for the header
      generated     pre-formatted timestamp string; default 'now' in UTC.

    Returns the full `.reject` text. The `to` side maps to the engine's `mine`
    value (Conflict.mine_value / mine_lines) and `from` to `theirs`.
    """
    if generated is None:
        generated = _now_utc_label()

    out = []
    # --- global '#' header --------------------------------------------------
    out.append("# plan merge — conflict resolution file   "
               "(edit blocks, then: plan merge --resolve | --abort)")
    out.append("#")
    out.append("# Generated : %s · plan %s" % (generated, plan_version))
    out.append("# Plan file : %s" % plan_path)
    out.append("# Base      : %s   (merge-base)" % base_label)
    out.append("# To        : %s   -> written into the plan file "
               "(conflicts default to this side)" % to_label)
    out.append("# From      : %s" % from_label)
    out.append("# Snapshots : %s   (line numbers below refer to to/from)"
               % snapshot_dir)
    out.append("# Conflicts : %d" % len(conflicts))
    out.append("#")
    out.append(_HOW_TO_RESOLVE.rstrip("\n"))
    out.append("")

    # --- one block per conflict --------------------------------------------
    for c in conflicts:
        out.append(_render_block(c, to_branch, from_branch))
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"


def _render_block(c, to_branch, from_branch):
    """Render a single conflict block (header + both sides + footer).

    `to` is the engine's `mine` side, `from` is `theirs`.
    """
    parts = []
    header = "%s id=%s type=%s node=#%s" % (
        _REJECT_HEADER_PREFIX, c.id, c.ctype, _conflict_node_token(c.node_id))
    # field=<name> is included for field/text; OMITTED for modify-delete (the
    # parser infers field=NODE_FIELD from type=modify-delete).
    if c.ctype != "modify-delete":
        header += " field=%s" % c.field
    header += " to.lines=%s from.lines=%s to.sum=%s from.sum=%s" % (
        _fmt_lines(c.mine_lines), _fmt_lines(c.theirs_lines),
        conflict_sum(c.mine_value), conflict_sum(c.theirs_value))
    parts.append(header)

    parts.append("--- to (%s) ---" % to_branch)
    parts.append(_render_side_value(c.mine_value))
    parts.append("--- from (%s) ---" % from_branch)
    parts.append(_render_side_value(c.theirs_value))
    parts.append("%s id=%s" % (_REJECT_FOOTER_PREFIX, c.id))
    return "\n".join(parts)


def _render_side_value(value):
    """Render a side's value as block content.

    `value` is already a render-ready string (scalar, multiline body, or node
    repr) or the DELETED sentinel. We emit it verbatim; an empty/absent value
    becomes a single empty line so the block shape is preserved.
    """
    if value is None:
        return ""
    return value


def _now_utc_label():
    """'YYYY-MM-DD HH:MM UTC' for the Generated header (best effort)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------

# Header field extractors. The header line is machine-owned; we read the tokens
# we care about and tolerate the advisory line-range tokens.
_HDR_ID = _re.compile(r'\bid=(\S+)')
_HDR_TYPE = _re.compile(r'\btype=(\S+)')
_HDR_NODE = _re.compile(r'\bnode=#(\S+)')
_HDR_FIELD = _re.compile(r'\bfield=(\S+)')
# The header tokens are user-facing (`to.sum`/`from.sum`); the dict keys below
# stay `mine_sum`/`theirs_sum` (engine-internal) so the resolver is unchanged.
_HDR_TO_SUM = _re.compile(r'\bto\.sum=(\S+)')
_HDR_FROM_SUM = _re.compile(r'\bfrom\.sum=(\S+)')


def _parse_header(line):
    """Parse a '<<< PLAN-CONFLICT ...' header into a dict of fields.

    Returns {'id', 'type', 'node_id', 'field', 'mine_sum', 'theirs_sum'}.
    The header tokens are the user-facing `to.sum`/`from.sum`; the dict keys
    remain engine-internal (`mine_sum` <- to.sum, `theirs_sum` <- from.sum).
    `field` defaults to NODE_FIELD when type=modify-delete (it is omitted from
    the rendered header for that type).
    """
    def need(rx, name):
        m = rx.search(line)
        if not m:
            raise RejectError("malformed conflict header (missing %s): %s"
                              % (name, line.strip()))
        return m.group(1)

    cid = need(_HDR_ID, "id")
    ctype = need(_HDR_TYPE, "type")
    node_id = need(_HDR_NODE, "node")
    mine_sum = need(_HDR_TO_SUM, "to.sum")
    theirs_sum = need(_HDR_FROM_SUM, "from.sum")

    fm = _HDR_FIELD.search(line)
    if fm:
        field = fm.group(1)
    elif ctype == "modify-delete":
        field = NODE_FIELD
    else:
        raise RejectError("malformed conflict header (missing field): %s"
                          % line.strip(), conflict_id=cid)

    return {
        "id": cid,
        "type": ctype,
        "node_id": node_id,
        "field": field,
        "mine_sum": mine_sum,
        "theirs_sum": theirs_sum,
    }


def _footer_id(line):
    """If `line` is a '>>> END id=N' footer, return N (str); else None."""
    if not line.startswith(_REJECT_FOOTER_PREFIX):
        return None
    m = _re.search(r'\bid=(\S+)', line)
    return m.group(1) if m else ""


def _split_blocks(text):
    """Yield (header_dict, body_lines) for each conflict block in `text`.

    body_lines are the raw lines strictly between the '<<<' header and the
    matching '>>> END id=N' footer (markers and content intermixed; not yet
    classified). Lines outside blocks (the '#' header, blank separators) are
    ignored.

    The footer is ANCHORED to the block's own id: only '>>> END id=N' (the same
    N as the opening header) closes the block. A '>>> END id=M' (M != N) or a
    nested '<<< PLAN-CONFLICT ...' that appears while a block is open is treated
    as ordinary body content — a side's content can legitimately contain such
    delimiter-like lines (a body/text conflict, or a node repr quoting git
    output). The header checksums are the final arbiter of correctness.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith(_REJECT_HEADER_PREFIX):
            header = _parse_header(line)
            cid = header["id"]
            body = []
            i += 1
            closed = False
            while i < n:
                fid = _footer_id(lines[i])
                if fid is not None and fid == cid:
                    # Our own terminator.
                    closed = True
                    i += 1
                    break
                # Any other footer (id mismatch) or a stray opening header that
                # appears before our terminator is just content of this block.
                body.append(lines[i])
                i += 1
            if not closed:
                raise RejectError(
                    "unterminated conflict block (missing '>>> END id=%s')" % cid,
                    conflict_id=cid)
            yield header, body
        else:
            i += 1


def _indicator_side(line):
    """If `line` is exactly a rendered side indicator, return 'mine'/'theirs'.

    Recognition is precise (the full '--- to (<branch>) ---' shape), so a
    side's content containing a markdown rule or quoted delimiter is NEVER
    mistaken for an indicator. The rendered word is user-facing (`to`/`from`);
    we translate it to the engine-internal side ('mine'/'theirs') so the rest of
    the parser — and the resolutions map it produces — stays engine-internal.
    """
    m = _INDICATOR_RE.match(line)
    return _REJECT_SIDE_TO_ENGINE[m.group(1)] if m else None


def _has_content(text):
    """True if normalized text is non-empty."""
    return normalize_conflict_text(text) != ""


def _match_side(text, mine_sum, theirs_sum):
    """Return 'mine'/'theirs' if conflict_sum(text) matches a side, else None.

    Returns 'mine' when both sums are equal (the two sides are byte-identical
    after normalization, so the choice is immaterial — mine is the in-tree
    default).
    """
    if not _has_content(text):
        return None
    csum = conflict_sum(text)
    m = (csum == mine_sum)
    t = (csum == theirs_sum)
    if m:                  # also covers m and t (identical sides)
        return "mine"
    if t:
        return "theirs"
    return None


def _indicator_positions(body_lines):
    """Return the indices of body lines that are precise side indicators,
    paired with their side: [(index, 'mine'|'theirs'), ...]."""
    out = []
    for idx, ln in enumerate(body_lines):
        side = _indicator_side(ln)
        if side is not None:
            out.append((idx, side))
    return out


def _resolve_block(header, body_lines):
    """Determine the chosen side ('mine' | 'theirs', engine-internal) for one block.

    Choice-only is enforced by the recorded checksums: the kept content MUST
    `conflict_sum`-match exactly one side. Because a side's CONTENT can itself
    contain delimiter-like lines (a body/text conflict, a node repr quoting git
    output, a markdown rule), we let the checksums — not line scanning — be the
    arbiter:

      1. Build a small set of candidate "kept content" strings and accept the
         first that checksum-matches a side. The candidates cover the two ways a
         user keeps a single side:
           (a) the whole body verbatim       -> "content-only" keep;
           (b) the body minus a single leading indicator line -> "indicator kept".
         The rendered form always places exactly one indicator immediately
         before its content, so (a)/(b) reconstruct the exact side value even if
         that value contains interior delimiter-like lines.
      2. If NO candidate matches, fall back to indicator analysis to choose the
         RIGHT diagnostic:
           - both indicators present, each owning content -> "keep only one side"
           - nothing kept at all                          -> "not resolved"
           - otherwise                                    -> "edited/unrecognized"
    """
    cid = header["id"]
    mine_sum = header["mine_sum"]
    theirs_sum = header["theirs_sum"]

    # --- 1. Checksum-arbitrated candidates. --------------------------------
    candidates = []
    whole = "\n".join(body_lines)
    candidates.append(whole)
    # Strip a single LEADING indicator line (the only place the renderer emits
    # one for a kept side). Skip any blank lines that may precede it.
    j = 0
    while j < len(body_lines) and body_lines[j].strip() == "":
        j += 1
    if j < len(body_lines) and _indicator_side(body_lines[j]) is not None:
        candidates.append("\n".join(body_lines[j + 1:]))
    # Last resort: drop EVERY recognized indicator line. Tried only after the
    # genuine forms above, so a side whose content contains an indicator-shaped
    # line is already resolved verbatim; this only rescues odd layouts (e.g.
    # content left before/around an emptied marker).
    indicators = _indicator_positions(body_lines)
    if indicators:
        ind_idx = {idx for idx, _s in indicators}
        candidates.append(
            "\n".join(ln for i, ln in enumerate(body_lines) if i not in ind_idx))

    for cand in candidates:
        side = _match_side(cand, mine_sum, theirs_sum)
        if side is not None:
            return side

    # --- 2. No checksum match -> choose the right diagnostic. --------------
    # Does a recognized 'mine' indicator AND a 'theirs' indicator each own
    # non-empty trailing content? (Approximate, only for diagnostics.)
    mine_has = _indicator_owns_content(body_lines, indicators, "mine")
    theirs_has = _indicator_owns_content(body_lines, indicators, "theirs")
    if mine_has and theirs_has:
        raise RejectError(
            "keep only one side (conflict #%s)" % cid, conflict_id=cid)

    if not _has_content(whole):
        raise RejectError(
            "conflict #%s not resolved" % cid, conflict_id=cid)

    raise RejectError(
        "unrecognized/edited content; only side selection is allowed "
        "(conflict #%s)" % cid, conflict_id=cid)


def _indicator_owns_content(body_lines, indicators, want_side):
    """True if a `want_side` indicator is followed by any non-blank content
    before the next indicator. Used only to pick the 'keep only one side'
    diagnostic when no checksum candidate matched."""
    for k, (idx, side) in enumerate(indicators):
        if side != want_side:
            continue
        end = indicators[k + 1][0] if k + 1 < len(indicators) else len(body_lines)
        for ln in body_lines[idx + 1:end]:
            if ln.strip() != "":
                return True
    return False


def parse_reject(text):
    """Parse an edited `.reject` file into a resolutions map.

    Returns {(node_id, field) -> "mine" | "theirs"} (engine-internal side
    names; the user-facing `to`/`from` selection is translated here), with keys
    shaped exactly like Conflict.key() so the map can be passed to
    merge_trees(..., resolutions=...).

    Raises RejectError (with the offending conflict id where known) on any
    malformed, edited, ambiguous or unresolved block. All problems are collected
    and reported together where practical.
    """
    resolutions = {}
    errors = []
    for header, body in _split_blocks(text):
        try:
            side = _resolve_block(header, body)
        except RejectError as exc:
            errors.append(exc)
            continue
        key = (str(header["node_id"]), header["field"])
        resolutions[key] = side

    if errors:
        if len(errors) == 1:
            raise errors[0]
        msg = "; ".join(e.message for e in errors)
        raise RejectError(msg, conflict_id=errors[0].conflict_id)

    return resolutions
