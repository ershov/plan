#!/usr/bin/env python3
"""Tests for the merge report renderer/parser (src/116-merge-report.py).

Run from the project root with:  python3 -m unittest test_merge_report

These tests exercise the REAL generated module (`plan.py`). They build real
conflicts by constructing small base/mine/theirs trees with plan.parse(...) and
plan.merge_trees(...), render them with plan.render_reject(...), then simulate a
user editing the `.reject` (keeping one side, deleting the other, deleting an
indicator, editing content, etc.) and feed it back through plan.parse_reject(...).

The round trip must preserve the (node_id, field) keys exactly as
Conflict.key(), and feeding the parsed resolutions to merge_trees(resolutions=)
must clear every conflict.
"""

import re
import textwrap
import unittest

import plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADER = """\
# Project: T {{#project}}

## Metadata {{#metadata}}

    next_id: {next_id}

## Tickets {{#tickets}}
"""


def plan_doc(next_id, tickets_md):
    body = textwrap.dedent(tickets_md)
    return plan.parse(HEADER.format(next_id=next_id) + body)


def body_of(node):
    """Dedented, stripped body text of a node."""
    return textwrap.dedent("\n".join(node.body_lines)).strip()


# Common rendering kwargs (the values the git/CLI layer supplies in Stage 3).
# User-facing side vocabulary is `to`/`from`; the engine/return values stay
# `mine`/`theirs` (so `to` <- engine 'mine', `from` <- engine 'theirs').
RENDER_KW = dict(
    plan_path="/repo/.PLAN.md",
    base_label="a1b2c3d",
    to_label="feature-x @ 9f8e7d6",
    from_label="main      @ 1234abc",
    to_branch="feature-x",
    from_branch="main",
    snapshot_dir=".git/plan-merge/{base,mine,theirs}",
    plan_version="v1.0",
    generated="2026-05-29 14:22 UTC",
)


def render(conflicts):
    return plan.render_reject(conflicts, **RENDER_KW)


# --- "user edits" the rendered text -----------------------------------------
#
# A real user opens the .reject and either deletes the side they DON'T want, or
# deletes a side's indicator line and leaves the content. These helpers rewrite
# the rendered text exactly the way such an edit would, operating block by block.

_HDR_ID_RE = re.compile(r'\bid=(\S+)')
# The rendered indicator word is user-facing (`to`/`from`); the helper logic
# below keys on the engine side names (`mine`/`theirs`) — translate here so the
# rest of the helpers (and parse_reject's return values) stay engine-internal.
_IND_RE = re.compile(r'^--- (to|from) \(.*\) ---\s*$')
_IND_TO_ENGINE = {"to": "mine", "from": "theirs"}
# The marker lines a user edit emits, keyed by engine side.
_MARKER_FOR = {
    "mine": "--- to (feature-x) ---",
    "theirs": "--- from (main) ---",
}


def _split_into_blocks(text):
    """Return (preamble, [block_text, ...]).

    Block boundaries mirror the parser: a block opens at '<<< PLAN-CONFLICT
    id=N' and closes ONLY at the matching '>>> END id=N'. Lines that merely look
    like delimiters inside a side's content stay part of the block. This makes
    the helper a faithful model of the rendered text even when a side's content
    contains delimiter-like lines.
    """
    lines = text.split("\n")
    preamble = []
    blocks = []
    i = 0
    n = len(lines)
    while i < n and not lines[i].startswith("<<< PLAN-CONFLICT"):
        preamble.append(lines[i])
        i += 1
    while i < n:
        if lines[i].startswith("<<< PLAN-CONFLICT"):
            cid = _HDR_ID_RE.search(lines[i]).group(1)
            blk = [lines[i]]
            i += 1
            while i < n:
                blk.append(lines[i])
                if lines[i].startswith(">>> END") and \
                        _HDR_ID_RE.search(lines[i]) and \
                        _HDR_ID_RE.search(lines[i]).group(1) == cid:
                    i += 1
                    break
                i += 1
            blocks.append(blk)
        else:
            i += 1
    return preamble, blocks


def _block_segments(block):
    """Split one block's lines into header, mine_lines, theirs_lines, footer.

    Uses the PRECISE indicator form so a content line shaped like a markdown
    rule (or a quoted '--- theirs (x) ---') is not mistaken for an indicator —
    except the exact rendered shape, which is inherently indistinguishable and
    correctly attributed to whichever side currently owns the content stream.
    """
    header = block[0]
    footer = block[-1]
    mine_lines = []
    theirs_lines = []
    cur = None
    for ln in block[1:-1]:
        m = _IND_RE.match(ln)
        if m:
            cur = _IND_TO_ENGINE[m.group(1)]
            continue
        if cur == "mine":
            mine_lines.append(ln)
        elif cur == "theirs":
            theirs_lines.append(ln)
    return header, mine_lines, theirs_lines, footer


def edit_keep_side(text, side, keep_indicator=True):
    """Simulate the user keeping `side` and deleting the other in EVERY block.

    keep_indicator=True  -> leave the '--- side ---' marker line in place.
    keep_indicator=False -> delete BOTH indicator lines, leaving content only.
    """
    preamble, blocks = _split_into_blocks(text)
    out = list(preamble)
    for blk in blocks:
        header, mine_lines, theirs_lines, footer = _block_segments(blk)
        content = mine_lines if side == "mine" else theirs_lines
        marker = _MARKER_FOR[side]
        out.append(header)
        if keep_indicator:
            out.append(marker)
        out.extend(content)
        out.append(footer)
        out.append("")
    return "\n".join(out)


def edit_keep_both(text):
    """Leave the block untouched (both indicators + content present)."""
    return text


def edit_keep_nothing(text):
    """Delete both indicators AND all content from every block."""
    preamble, blocks = _split_into_blocks(text)
    out = list(preamble)
    for blk in blocks:
        header, _m, _t, footer = _block_segments(blk)
        out.append(header)
        out.append(footer)
        out.append("")
    return "\n".join(out)


def edit_keep_side_but_mutate(text, side):
    """Keep `side` (indicator + content) but corrupt the content with an edit."""
    preamble, blocks = _split_into_blocks(text)
    out = list(preamble)
    for blk in blocks:
        header, mine_lines, theirs_lines, footer = _block_segments(blk)
        content = list(mine_lines if side == "mine" else theirs_lines)
        marker = _MARKER_FOR[side]
        # Mutate: append a stray token to the first content line (or add one).
        if content:
            content[0] = content[0] + " EDITED-BY-USER"
        else:
            content = ["EDITED-BY-USER"]
        out.append(header)
        out.append(marker)
        out.extend(content)
        out.append(footer)
        out.append("")
    return "\n".join(out)


# --- conflict builders -------------------------------------------------------

def field_conflict():
    """A single status field conflict on ticket #1 (mine vs theirs)."""
    base = plan_doc(2, """
        * ## Ticket: Task: X {#1}

              status: open
        """)
    mine = plan_doc(2, """
        * ## Ticket: Task: X {#1}

              status: in-progress
        """)
    theirs = plan_doc(2, """
        * ## Ticket: Task: X {#1}

              status: done
        """)
    return base, mine, theirs


def modify_delete_conflict():
    """A modify/delete conflict on #2: mine deletes, theirs edits."""
    base = plan_doc(3, """
        * ## Ticket: Task: Keep {#1}

              status: open

        * ## Ticket: Task: Victim {#2}

              status: open
        """)
    mine = plan_doc(3, """
        * ## Ticket: Task: Keep {#1}

              status: open
        """)
    theirs = plan_doc(3, """
        * ## Ticket: Task: Keep {#1}

              status: open

        * ## Ticket: Task: Victim EDITED {#2}

              status: in-progress
        """)
    return base, mine, theirs


# ===========================================================================
# Rendering shape
# ===========================================================================

class TestRenderShape(unittest.TestCase):
    def test_global_header_present(self):
        base, mine, theirs = field_conflict()
        r = plan.merge_trees(base, mine, theirs)
        text = render(r.conflicts)
        self.assertIn("# plan merge", text)
        self.assertIn("# Generated : 2026-05-29 14:22 UTC", text)
        self.assertIn("# Plan file : /repo/.PLAN.md", text)
        self.assertIn("# Base      : a1b2c3d", text)
        self.assertIn("# To        : feature-x @ 9f8e7d6", text)
        self.assertIn("# From      : main      @ 1234abc", text)
        self.assertIn("# Snapshots : .git/plan-merge/{base,mine,theirs}", text)
        self.assertIn("# Conflicts : 1", text)
        self.assertIn("# HOW TO RESOLVE", text)
        self.assertIn("keep exactly ONE side", text)
        self.assertIn("<DELETED> removes the entry", text)

    def test_field_block_includes_field_and_sums(self):
        base, mine, theirs = field_conflict()
        r = plan.merge_trees(base, mine, theirs)
        c = r.conflicts[0]
        text = render(r.conflicts)
        self.assertIn("<<< PLAN-CONFLICT id=%s type=field node=#1 field=status"
                      % c.id, text)
        self.assertIn("to.sum=%s" % plan.conflict_sum(c.mine_value), text)
        self.assertIn("from.sum=%s" % plan.conflict_sum(c.theirs_value), text)
        self.assertIn("--- to (feature-x) ---", text)
        self.assertIn("--- from (main) ---", text)
        self.assertIn(">>> END id=%s" % c.id, text)
        # advisory line ranges default to 0-0 (Stage 3 populates them).
        self.assertIn("to.lines=0-0 from.lines=0-0", text)

    def test_modify_delete_block_omits_field(self):
        base, mine, theirs = modify_delete_conflict()
        r = plan.merge_trees(base, mine, theirs)
        c = r.conflicts[0]
        self.assertEqual(c.ctype, "modify-delete")
        text = render(r.conflicts)
        # No 'field=' token on a modify-delete header.
        hdr = [ln for ln in text.split("\n") if ln.startswith("<<< PLAN-CONFLICT")][0]
        self.assertIn("type=modify-delete", hdr)
        self.assertNotIn("field=", hdr)
        self.assertIn("node=#2", hdr)
        # The deleted (mine) side is rendered as the DELETED sentinel.
        self.assertIn(plan.DELETED, text)

    def test_advisory_lines_rendered_when_set(self):
        base, mine, theirs = field_conflict()
        r = plan.merge_trees(base, mine, theirs)
        c = r.conflicts[0]
        c.mine_lines = (210, 210)
        c.theirs_lines = (198, 199)
        text = render(r.conflicts)
        self.assertIn("to.lines=210-210 from.lines=198-199", text)


# ===========================================================================
# Round trip — keep mine / keep theirs, indicator kept vs deleted
# ===========================================================================

class TestRoundTripField(unittest.TestCase):
    def setUp(self):
        self.base, self.mine, self.theirs = field_conflict()
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)
        self.c = self.r.conflicts[0]
        self.text = render(self.r.conflicts)

    def _assert_resolves(self, edited, expected_side):
        res = plan.parse_reject(edited)
        self.assertEqual(res, {self.c.key(): expected_side})
        # The key must equal Conflict.key() exactly.
        self.assertIn(self.c.key(), res)
        # Feeding it back clears the conflict.
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        return r2

    def test_keep_mine_indicator_kept(self):
        edited = edit_keep_side(self.text, "mine", keep_indicator=True)
        r2 = self._assert_resolves(edited, "mine")
        self.assertEqual(r2.project.lookup(1).get_attr("status"), "in-progress")

    def test_keep_theirs_indicator_kept(self):
        edited = edit_keep_side(self.text, "theirs", keep_indicator=True)
        r2 = self._assert_resolves(edited, "theirs")
        self.assertEqual(r2.project.lookup(1).get_attr("status"), "done")

    def test_keep_mine_content_only(self):
        edited = edit_keep_side(self.text, "mine", keep_indicator=False)
        r2 = self._assert_resolves(edited, "mine")
        self.assertEqual(r2.project.lookup(1).get_attr("status"), "in-progress")

    def test_keep_theirs_content_only(self):
        edited = edit_keep_side(self.text, "theirs", keep_indicator=False)
        r2 = self._assert_resolves(edited, "theirs")
        self.assertEqual(r2.project.lookup(1).get_attr("status"), "done")


# ===========================================================================
# Round trip — modify/delete (<DELETED> side chosen)
# ===========================================================================

class TestRoundTripModifyDelete(unittest.TestCase):
    def setUp(self):
        self.base, self.mine, self.theirs = modify_delete_conflict()
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)
        self.c = self.r.conflicts[0]
        self.text = render(self.r.conflicts)

    def test_keep_theirs_restores_node(self):
        # theirs edited the node -> keeping theirs restores #2.
        edited = edit_keep_side(self.text, "theirs", keep_indicator=True)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "theirs"})
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        self.assertIsNotNone(r2.project.lookup(2))
        self.assertEqual(r2.project.lookup(2).title, "Victim EDITED")

    def test_keep_mine_deleted_side_removes_node(self):
        # mine's side is <DELETED>; keeping it (content-only path: content is the
        # DELETED sentinel string) removes #2.
        edited = edit_keep_side(self.text, "mine", keep_indicator=True)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "mine"})
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        self.assertIsNone(r2.project.lookup(2))

    def test_deleted_side_content_only_matches_by_checksum(self):
        # No indicators; the kept content is the <DELETED> sentinel -> mine.
        edited = edit_keep_side(self.text, "mine", keep_indicator=False)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "mine"})


# ===========================================================================
# Validation branches
# ===========================================================================

class TestValidation(unittest.TestCase):
    def setUp(self):
        self.base, self.mine, self.theirs = field_conflict()
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)
        self.c = self.r.conflicts[0]
        self.text = render(self.r.conflicts)

    def test_edited_content_raises(self):
        edited = edit_keep_side_but_mutate(self.text, "mine")
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(edited)
        self.assertEqual(ctx.exception.conflict_id, str(self.c.id))
        self.assertIn("edited", ctx.exception.message)

    def test_both_sides_kept_raises(self):
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(edit_keep_both(self.text))
        self.assertEqual(ctx.exception.conflict_id, str(self.c.id))
        self.assertIn("keep only one side", ctx.exception.message)

    def test_nothing_kept_raises(self):
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(edit_keep_nothing(self.text))
        self.assertEqual(ctx.exception.conflict_id, str(self.c.id))
        self.assertIn("not resolved", ctx.exception.message)

    def test_content_only_matching_neither_raises(self):
        # No indicators, content present but matches neither sum.
        _preamble, blocks = _split_into_blocks(self.text)
        header = blocks[0][0]
        footer = blocks[0][-1]
        edited = "%s\nsomething totally different\n%s\n" % (header, footer)
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(edited)
        self.assertIn("unrecognized", ctx.exception.message)

    def test_unterminated_block_raises(self):
        bad = ("<<< PLAN-CONFLICT id=9 type=field node=#1 field=status "
               "to.lines=0-0 from.lines=0-0 to.sum=aaaaaaaa "
               "from.sum=bbbbbbbb\n"
               "--- to (x) ---\nfoo\n")  # no '>>> END'
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(bad)
        self.assertIn("unterminated", ctx.exception.message)

    def test_malformed_header_missing_sum_raises(self):
        bad = ("<<< PLAN-CONFLICT id=9 type=field node=#1 field=status\n"
               "--- to (x) ---\nfoo\n>>> END id=9\n")
        with self.assertRaises(plan.RejectError):
            plan.parse_reject(bad)

    def test_empty_surviving_indicator_ignored_other_content_matches(self):
        # User deleted theirs entirely AND blanked the content under the mine
        # marker, but pasted mine's content with no marker (e.g. moved it above
        # the marker). The empty surviving indicator must not hijack the block;
        # the unattributed content resolves by checksum -> mine.
        header, mine_lines, theirs_lines, footer = _block_segments(
            _split_into_blocks(self.text)[1][0])
        edited = "\n".join([header] + mine_lines
                           + ["--- to (feature-x) ---", footer]) + "\n"
        res = plan.parse_reject(edited)
        self.assertEqual(res, {self.c.key(): "mine"})


# ===========================================================================
# Mixed: a field conflict AND a modify-delete conflict in one file
# ===========================================================================

class TestMixedConflicts(unittest.TestCase):
    def setUp(self):
        # #1 status field conflict; #2 modify/delete (mine deletes, theirs edits).
        self.base = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
            """)
        self.mine = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
            """)
        self.theirs = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: done

            * ## Ticket: Task: Victim EDITED {#2}

                  status: in-progress
            """)
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)

    def test_two_conflicts_rendered(self):
        ctypes = sorted(c.ctype for c in self.r.conflicts)
        self.assertEqual(ctypes, ["field", "modify-delete"])
        text = render(self.r.conflicts)
        self.assertIn("# Conflicts : 2", text)
        self.assertEqual(text.count("<<< PLAN-CONFLICT"), 2)

    def test_resolve_field_mine_modify_delete_theirs(self):
        text = render(self.r.conflicts)
        # Keep theirs in every block (resolves #1->theirs status=done,
        # #2->theirs restores the edited node).
        edited = edit_keep_side(text, "theirs", keep_indicator=True)
        res = plan.parse_reject(edited)
        expected = {c.key(): "theirs" for c in self.r.conflicts}
        self.assertEqual(res, expected)
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        self.assertEqual(r2.project.lookup(1).get_attr("status"), "done")
        self.assertIsNotNone(r2.project.lookup(2))
        self.assertEqual(r2.project.lookup(2).title, "Victim EDITED")

    def test_keys_match_conflict_keys(self):
        text = render(self.r.conflicts)
        edited = edit_keep_side(text, "mine", keep_indicator=True)
        res = plan.parse_reject(edited)
        self.assertEqual(set(res.keys()),
                         {c.key() for c in self.r.conflicts})


# ===========================================================================
# Multi-error reporting
# ===========================================================================

class TestMultiError(unittest.TestCase):
    def test_collects_all_problems(self):
        # Two blocks each unresolvable (nothing kept) -> a combined message.
        base = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: open

            * ## Ticket: Task: Y {#2}

                  status: open
            """)
        mine = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: in-progress

            * ## Ticket: Task: Y {#2}

                  status: in-progress
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: X {#1}

                  status: done

            * ## Ticket: Task: Y {#2}

                  status: done
            """)
        r = plan.merge_trees(base, mine, theirs)
        self.assertEqual(len(r.conflicts), 2)
        text = render(r.conflicts)
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(edit_keep_nothing(text))
        # Both ids referenced in the combined message.
        msg = ctx.exception.message
        self.assertIn("#%s" % r.conflicts[0].id, msg)
        self.assertIn("#%s" % r.conflicts[1].id, msg)


# ===========================================================================
# Marker-like content inside a side's value (the delimiter-robustness bug)
# ===========================================================================

class TestMarkerLikeContent(unittest.TestCase):
    """A side's content can legitimately contain lines that look like the
    machine markers (a body/text conflict, or a node repr quoting git output).
    Footer anchoring + checksum-arbitrated side detection must keep the round
    trip correct for BOTH sides, indicator kept AND content-only."""

    def _body_conflict_with_delimiters(self):
        # Each side's body contains: a markdown rule '--- ... ---' (NOT the exact
        # indicator shape), a '>>> END id=99' line, and a '<<< PLAN-CONFLICT'
        # line. A naive parser would truncate the block or a side at these.
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Original body.
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Mine wrote a tricky body.

              --- a markdown rule ---

              >>> END id=99

              <<< PLAN-CONFLICT id=42 not a real header

              Tail of mine.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Theirs alternative body.

              ------

              >>> END id=7

              Tail of theirs.
            """)
        return base, mine, theirs

    def setUp(self):
        self.base, self.mine, self.theirs = self._body_conflict_with_delimiters()
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)
        self.assertEqual(len(self.r.conflicts), 1)
        self.c = self.r.conflicts[0]
        self.assertEqual(self.c.ctype, "text")
        self.text = render(self.r.conflicts)

    def test_block_not_truncated_by_inner_end_marker(self):
        # The rendered block must still parse as ONE block: the '>>> END id=99'
        # and '>>> END id=7' inside content must NOT close it; only the real
        # '>>> END id=<conflict id>' does. Keeping both sides -> "keep only one".
        with self.assertRaises(plan.RejectError) as ctx:
            plan.parse_reject(self.text)
        self.assertEqual(ctx.exception.conflict_id, str(self.c.id))
        self.assertIn("keep only one side", ctx.exception.message)

    def _assert_round_trip(self, side, keep_indicator):
        edited = edit_keep_side(self.text, side, keep_indicator=keep_indicator)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {self.c.key(): side})
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        return r2

    def test_keep_mine_indicator_kept(self):
        r2 = self._assert_round_trip("mine", keep_indicator=True)
        self.assertIn("Tail of mine.", body_of(r2.project.lookup(1)))
        self.assertIn(">>> END id=99", body_of(r2.project.lookup(1)))

    def test_keep_mine_content_only(self):
        r2 = self._assert_round_trip("mine", keep_indicator=False)
        self.assertIn("<<< PLAN-CONFLICT id=42", body_of(r2.project.lookup(1)))

    def test_keep_theirs_indicator_kept(self):
        r2 = self._assert_round_trip("theirs", keep_indicator=True)
        self.assertIn("Theirs alternative body.", body_of(r2.project.lookup(1)))
        self.assertIn(">>> END id=7", body_of(r2.project.lookup(1)))

    def test_keep_theirs_content_only(self):
        r2 = self._assert_round_trip("theirs", keep_indicator=False)
        self.assertIn("Tail of theirs.", body_of(r2.project.lookup(1)))

    def test_exact_indicator_shape_inside_content(self):
        # The hardest case: the `from` side's body literally contains a line in
        # the EXACT rendered indicator shape '--- from (x) ---'. We build the
        # edited text by hand (the helper, like any line scanner, cannot
        # faithfully round-trip an exact-shape line in content). The parser must
        # still resolve via the checksum candidates.
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Original.
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Mine body.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Theirs body line.

              --- from (not really) ---
            """)
        r = plan.merge_trees(base, mine, theirs)
        c = r.conflicts[0]
        theirs_val = c.theirs_value
        self.assertIn("--- from (not really) ---", theirs_val)
        hdr = ("<<< PLAN-CONFLICT id=%s type=text node=#1 field=body "
               "to.lines=0-0 from.lines=0-0 to.sum=%s from.sum=%s"
               % (c.id, plan.conflict_sum(c.mine_value),
                  plan.conflict_sum(theirs_val)))
        # keep `from` (engine 'theirs'), indicator kept
        kept_ind = "%s\n--- from (main) ---\n%s\n>>> END id=%s\n" % (
            hdr, theirs_val, c.id)
        self.assertEqual(plan.parse_reject(kept_ind), {c.key(): "theirs"})
        # keep `from`, content only
        content_only = "%s\n%s\n>>> END id=%s\n" % (hdr, theirs_val, c.id)
        self.assertEqual(plan.parse_reject(content_only), {c.key(): "theirs"})


class TestModifyDeleteMarkerLikeBody(unittest.TestCase):
    """A modify-delete node repr whose ticket body contains a '---' rule must
    round-trip (the kept side's repr contains a delimiter-like line)."""

    def setUp(self):
        self.base = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
            """)
        self.mine = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open
            """)
        self.theirs = plan_doc(3, """
            * ## Ticket: Task: Victim EDITED {#2}

                  status: in-progress

              First paragraph.

              ---

              Second paragraph after a rule.
            """)
        # Ensure theirs keeps #1 too so only #2 is modify/delete.
        self.theirs = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim EDITED {#2}

                  status: in-progress

              First paragraph.

              ---

              Second paragraph after a rule.
            """)
        self.r = plan.merge_trees(self.base, self.mine, self.theirs)
        self.c = self.r.conflicts[0]
        self.assertEqual(self.c.ctype, "modify-delete")
        self.assertIn("---", self.c.theirs_value)
        self.text = render(self.r.conflicts)

    def test_keep_theirs_node_with_rule_in_body(self):
        edited = edit_keep_side(self.text, "theirs", keep_indicator=True)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "theirs"})
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertEqual(r2.conflicts, [])
        self.assertIsNotNone(r2.project.lookup(2))
        self.assertIn("Second paragraph", body_of(r2.project.lookup(2)))

    def test_keep_theirs_content_only(self):
        edited = edit_keep_side(self.text, "theirs", keep_indicator=False)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "theirs"})

    def test_keep_mine_deleted_side(self):
        edited = edit_keep_side(self.text, "mine", keep_indicator=True)
        res = plan.parse_reject(edited)
        self.assertEqual(res, {("2", plan.NODE_FIELD): "mine"})
        r2 = plan.merge_trees(self.base, self.mine, self.theirs, resolutions=res)
        self.assertIsNone(r2.project.lookup(2))


if __name__ == "__main__":
    unittest.main()
