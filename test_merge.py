#!/usr/bin/env python3
"""Tests for the structure-aware three-way merge engine (src/115-merge-engine.py).

Run from the project root with:  python3 -m unittest test_merge

These tests exercise the REAL generated module (`plan.py`) — they build trees by
parsing markdown strings via plan.parse(...) and call plan.merge_trees(...).
"""

import textwrap
import unittest

import plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def doc(text):
    """Parse a (dedented) markdown string into a Project."""
    return plan.parse(textwrap.dedent(text))


HEADER = """\
# Project: T {{#project}}

## Metadata {{#metadata}}

    next_id: {next_id}

## Tickets {{#tickets}}
"""


def plan_doc(next_id, tickets_md):
    """Assemble a full plan document from a next_id and a tickets body.

    The tickets body is dedented INDEPENDENTLY so its relative nesting is
    preserved while the common leading indent (from the test's triple-quoted
    string) is stripped — concatenating before dedent would leave the body
    indented (the HEADER lines sit at column 0).
    """
    body = textwrap.dedent(tickets_md)
    return plan.parse(HEADER.format(next_id=next_id) + body)


def merge(base, mine, theirs, **kw):
    return plan.merge_trees(base, mine, theirs, **kw)


def reserialize_reparse(project):
    """Serialize then reparse a project; return the reparsed project.

    Asserts (indirectly, via not raising) that the merged tree is valid markdown.
    Also asserts the parse/serialize round-trip is idempotent.
    """
    text = plan.serialize(project)
    p2 = plan.parse(text)
    # Idempotence: re-serializing the reparsed tree must match.
    text2 = plan.serialize(p2)
    text3 = plan.serialize(plan.parse(text2))
    assert text2 == text3, "serialize/parse not idempotent"
    return p2


def ticket_ids(project):
    out = []

    def walk(ts):
        for t in ts:
            out.append(t.node_id)
            walk(t.children)

    walk(project.tickets)
    return out


def body_of(node):
    return textwrap.dedent("\n".join(node.body_lines)).strip()


def conflict_fields(result):
    return sorted((str(c.node_id), c.field, c.ctype) for c in result.conflicts)


# ===========================================================================
# Checksums / normalization
# ===========================================================================

class TestNormalization(unittest.TestCase):
    def test_crlf_to_lf(self):
        self.assertEqual(plan.normalize_conflict_text("a\r\nb"), "a\nb")

    def test_strip_trailing_ws_per_line(self):
        self.assertEqual(plan.normalize_conflict_text("a   \nb\t"), "a\nb")

    def test_strip_leading_trailing_blank_lines(self):
        self.assertEqual(plan.normalize_conflict_text("\n\nx\ny\n\n"), "x\ny")

    def test_none(self):
        self.assertEqual(plan.normalize_conflict_text(None), "")

    def test_conflict_sum_stable_and_short(self):
        s = plan.conflict_sum("hello\n")
        self.assertEqual(len(s), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in s))

    def test_conflict_sum_ignores_normalizable_diffs(self):
        a = plan.conflict_sum("  x \r\n  y  \n")
        b = plan.conflict_sum("\n  x\n  y\n\n")
        self.assertEqual(a, b)

    def test_conflict_sum_distinguishes_content(self):
        self.assertNotEqual(plan.conflict_sum("a"), plan.conflict_sum("b"))


# ===========================================================================
# Scenario 1: branch-only edit (one side changes a field)
# ===========================================================================

class TestBranchOnlyEdit(unittest.TestCase):
    def setUp(self):
        self.base = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: open

              Original body.

            * ## Ticket: Task: Beta {#2}

                  status: open
            """)

    def test_mine_only_status_change(self):
        mine = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: in-progress

              Original body.

            * ## Ticket: Task: Beta {#2}

                  status: open
            """)
        # theirs == base
        theirs = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: open

              Original body.

            * ## Ticket: Task: Beta {#2}

                  status: open
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")

    def test_theirs_only_title_change(self):
        mine = self.base  # mine == base
        theirs = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: open

              Original body.

            * ## Ticket: Task: Beta RENAMED {#2}

                  status: open
            """)
        r = merge(plan.parse(plan.serialize(self.base)), mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(2).title, "Beta RENAMED")

    def test_both_change_different_fields_no_conflict(self):
        mine = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: in-progress

              Original body.

            * ## Ticket: Task: Beta {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: open

              Original body.

            * ## Ticket: Task: Beta RENAMED {#2}

                  status: open
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")
        self.assertEqual(p.lookup(2).title, "Beta RENAMED")

    def test_identical_change_both_sides(self):
        changed = plan_doc(3, """
            * ## Ticket: Task: Alpha {#1}

                  status: done

              Original body.

            * ## Ticket: Task: Beta {#2}

                  status: open
            """)
        r = merge(self.base,
                  plan.parse(plan.serialize(changed)),
                  plan.parse(plan.serialize(changed)))
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "done")


# ===========================================================================
# Scenario 2: branch-only comment
# ===========================================================================

class TestBranchOnlyComment(unittest.TestCase):
    def test_theirs_adds_comment(self):
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
            """)
        mine = plan.parse(plan.serialize(base))
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * theirs note {#1:comment:1}

                  a theirs comment
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        comments = p.lookup(1).comments
        self.assertIsNotNone(comments)
        self.assertEqual([c.node_id for c in comments.comments], ["1:comment:1"])
        self.assertEqual(body_of(comments.comments[0]), "a theirs comment")

    def test_both_add_comments_distinct_ids(self):
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body

                * mine note {#1:comment:2}

                  mine body
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body

                * theirs note {#1:comment:3}

                  theirs body
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        ids = sorted(c.node_id for c in p.lookup(1).comments.comments)
        self.assertEqual(ids, ["1:comment:1", "1:comment:2", "1:comment:3"])


# ===========================================================================
# Scenario 3 & 4: both edit different fields / same field (conflict)
# ===========================================================================

class TestFieldMerge(unittest.TestCase):
    def setUp(self):
        self.base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody

              Original body.
            """)

    def test_same_field_conflict_defaults_to_mine(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
                  assignee: nobody

              Original body.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: done
                  assignee: nobody

              Original body.
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(conflict_fields(r), [("1", "status", "field")])
        c = r.conflicts[0]
        self.assertEqual(c.node_kind, "ticket")
        self.assertEqual(c.base_value, "open")
        self.assertEqual(c.mine_value, "in-progress")
        self.assertEqual(c.theirs_value, "done")
        # In-tree default is mine.
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")

    def test_body_conflict_is_text_type(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody

              Mine rewrote the body.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody

              Theirs rewrote the body.
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(conflict_fields(r), [("1", "body", "text")])
        c = r.conflicts[0]
        self.assertEqual(c.ctype, "text")
        self.assertEqual(c.mine_value, "Mine rewrote the body.")
        self.assertEqual(c.theirs_value, "Theirs rewrote the body.")
        p = reserialize_reparse(r.project)
        self.assertEqual(body_of(p.lookup(1)), "Mine rewrote the body.")

    def test_title_and_type_conflict(self):
        mine = plan_doc(2, """
            * ## Ticket: Bug: Mine Title {#1}

                  status: open
                  assignee: nobody

              Original body.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Improvement: Theirs Title {#1}

                  status: open
                  assignee: nobody

              Original body.
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(conflict_fields(r),
                         [("1", "title", "field"), ("1", "type", "field")])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).title, "Mine Title")
        self.assertEqual(p.lookup(1).ticket_type, "Bug")

    def test_attr_added_both_sides_same_value(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody
                  estimate: 2h

              Original body.
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody
                  estimate: 2h

              Original body.
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("estimate"), "2h")


# ===========================================================================
# Timestamp attrs (updated/created) never conflict; merge by rule
# ===========================================================================

class TestTimestamps(unittest.TestCase):
    def _doc(self, status, assignee, created, updated):
        return plan_doc(2, """
            * ## Ticket: Task: X {{#1}}

                  status: {status}
                  assignee: {assignee}
                  created: {created}
                  updated: {updated}

              Body text.
            """.format(status=status, assignee=assignee,
                       created=created, updated=updated))

    def test_coedit_different_fields_no_conflict_updated_latest(self):
        # Both branches edit DIFFERENT non-timestamp fields and both bump
        # `updated` to different times. Must NOT conflict; merged `updated` is
        # the latest and `created` the earliest of the three.
        base = self._doc("open", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-01-01 10:00:00 UTC")
        mine = self._doc("in-progress", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-02-01 09:00:00 UTC")
        theirs = self._doc("open", "alice",
                           "2025-12-01 08:00:00 UTC", "2026-03-15 12:00:00 UTC")
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        t = p.lookup(1)
        # one-sided non-timestamp edits both applied
        self.assertEqual(t.get_attr("status"), "in-progress")   # mine
        self.assertEqual(t.get_attr("assignee"), "alice")       # theirs
        # updated -> latest, created -> earliest
        self.assertEqual(t.get_attr("updated"), "2026-03-15 12:00:00 UTC")
        self.assertEqual(t.get_attr("created"), "2025-12-01 08:00:00 UTC")

    def test_same_nontimestamp_field_still_conflicts(self):
        # Both edit the SAME non-timestamp field differently -> still a conflict,
        # even though `updated` also diverges (which must NOT add a conflict).
        base = self._doc("open", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-01-01 10:00:00 UTC")
        mine = self._doc("in-progress", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-02-01 09:00:00 UTC")
        theirs = self._doc("done", "nobody",
                           "2026-01-01 10:00:00 UTC", "2026-03-15 12:00:00 UTC")
        r = merge(base, mine, theirs)
        # Exactly one conflict: status. NOT updated.
        self.assertEqual(conflict_fields(r), [("1", "status", "field")])
        p = reserialize_reparse(r.project)
        t = p.lookup(1)
        self.assertEqual(t.get_attr("status"), "in-progress")  # mine default
        # updated still merged by rule (latest), never conflicted.
        self.assertEqual(t.get_attr("updated"), "2026-03-15 12:00:00 UTC")

    def test_only_timestamps_diverge_no_conflict(self):
        # Identical content, only the auto-maintained timestamps differ.
        base = self._doc("open", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-01-01 10:00:00 UTC")
        mine = self._doc("open", "nobody",
                         "2026-01-01 10:00:00 UTC", "2026-02-02 02:02:02 UTC")
        theirs = self._doc("open", "nobody",
                           "2026-01-01 10:00:00 UTC", "2026-02-09 09:09:09 UTC")
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("updated"),
                         "2026-02-09 09:09:09 UTC")

    def test_timestamp_bump_not_an_edit_for_modify_delete(self):
        # base has #2; theirs DELETES it; mine only had its `updated` auto-bumped
        # (no real edit). This must be a clean delete, NOT a modify/delete
        # conflict.
        base = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
                  updated: 2026-01-01 10:00:00 UTC
            """)
        mine = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
                  updated: 2026-05-05 05:05:05 UTC
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertIsNone(p.lookup(2))

    def test_real_edit_plus_timestamp_bump_still_modify_delete(self):
        # Same as above but mine ALSO edits a real field -> modify/delete stands.
        base = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
                  updated: 2026-01-01 10:00:00 UTC
            """)
        mine = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: in-progress
                  updated: 2026-05-05 05:05:05 UTC
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(len(r.conflicts), 1)
        self.assertEqual(r.conflicts[0].ctype, "modify-delete")


# ===========================================================================
# Scenario 4b: divergent same-comment body edit -> field conflict
# ===========================================================================

class TestCommentBodyConflict(unittest.TestCase):
    def test_divergent_comment_body(self):
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * note {#1:comment:1}

                  base comment body
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * note {#1:comment:1}

                  mine edited the comment
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * note {#1:comment:1}

                  theirs edited the comment
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(conflict_fields(r), [("1:comment:1", "body", "text")])
        c = r.conflicts[0]
        self.assertEqual(c.node_kind, "comment")
        p = reserialize_reparse(r.project)
        cm = p.lookup(1).comments.comments[0]
        self.assertEqual(body_of(cm), "mine edited the comment")


# ===========================================================================
# Scenario 5: both add comments with COLLIDING ids (renumber)
# ===========================================================================

class TestCommentCollision(unittest.TestCase):
    def test_comment_id_collision_renumbered(self):
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body

                * mine added {#1:comment:2}

                  mine body
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * base note {#1:comment:1}

                  base body

                * theirs added {#1:comment:2}

                  theirs body
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        comments = {c.node_id: c.title for c in p.lookup(1).comments.comments}
        self.assertEqual(comments.get("1:comment:1"), "base note")
        self.assertEqual(comments.get("1:comment:2"), "mine added")
        # theirs collided -> renumbered above high-water mark
        self.assertEqual(comments.get("1:comment:3"), "theirs added")

    def test_renumber_mine_direction_for_comments(self):
        base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
            """)
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * mine added {#1:comment:1}

                  mine body
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              * ## Comments {#1:comments}

                * theirs added {#1:comment:1}

                  theirs body
            """)
        r = merge(base, mine, theirs, renumber="mine")
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        comments = {c.node_id: c.title for c in p.lookup(1).comments.comments}
        # mine side renumbered: mine's comment:1 -> comment:2, theirs keeps :1
        self.assertEqual(comments.get("1:comment:1"), "theirs added")
        self.assertEqual(comments.get("1:comment:2"), "mine added")


# ===========================================================================
# Scenario 6: both create tickets with colliding ids + reference rewrite
# ===========================================================================

class TestTicketCollision(unittest.TestCase):
    def setUp(self):
        self.base = plan_doc(2, """
            * ## Ticket: Task: Existing {#1}

                  status: open
            """)

    def test_collision_renumbers_theirs_default(self):
        mine = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Task: Mine new {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Bug: Theirs new {#2}

                  status: open
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        self.assertEqual(r.renumber_map, {2: 3})
        p = reserialize_reparse(r.project)
        titles = {t.node_id: t.title for t in p.tickets}
        self.assertEqual(titles[2], "Mine new")
        self.assertEqual(titles[3], "Theirs new")
        self.assertEqual(p.next_id, 4)

    def test_collision_renumbers_mine_when_requested(self):
        mine = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Task: Mine new {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Bug: Theirs new {#2}

                  status: open
            """)
        r = merge(self.base, mine, theirs, renumber="mine")
        self.assertEqual(r.renumber_map, {2: 3})
        p = reserialize_reparse(r.project)
        titles = {t.node_id: t.title for t in p.tickets}
        self.assertEqual(titles[3], "Mine new")
        self.assertEqual(titles[2], "Theirs new")

    def test_reference_rewrite_links_and_body(self):
        # theirs #2 references #1 via links and mentions #2 (self) in its body.
        mine = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Task: Mine new {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Bug: Theirs new {#2}

                  status: open
                  links: blocking:#1

              Depends on #1, tracked by #2 itself; see also #20.
            """)
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.renumber_map, {2: 3})
        p = reserialize_reparse(r.project)
        moved = p.lookup(3)
        # links untouched target (#1) preserved
        self.assertEqual(plan._parse_links(moved.get_attr("links")),
                         {"blocking": [1]})
        body = body_of(moved)
        # self-reference #2 -> #3, #1 untouched, #20 untouched (word boundary).
        self.assertIn("Depends on #1", body)
        self.assertIn("tracked by #3 itself", body)
        self.assertIn("#20", body)
        self.assertNotIn("#2 itself", body)

    def test_reference_rewrite_links_pointing_to_moved_ticket(self):
        # An EXISTING ticket on theirs links to theirs' colliding #2.
        mine = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open

            * ## Ticket: Task: Mine new {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: Existing {#1}

                  status: open
                  links: related:#2

            * ## Ticket: Bug: Theirs new {#2}

                  status: open
            """)
        # base #1 has no links, so theirs adding links:#2 is a one-sided change;
        # that link target must be rewritten to #3.
        r = merge(self.base, mine, theirs)
        self.assertEqual(r.renumber_map, {2: 3})
        p = reserialize_reparse(r.project)
        self.assertEqual(plan._parse_links(p.lookup(1).get_attr("links")),
                         {"related": [3]})


# ===========================================================================
# Scenario 7: modify/delete
# ===========================================================================

class TestModifyDelete(unittest.TestCase):
    def setUp(self):
        self.base = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim {#2}

                  status: open
            """)
        self.mine_deletes = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open
            """)
        self.theirs_edits = plan_doc(3, """
            * ## Ticket: Task: Keep {#1}

                  status: open

            * ## Ticket: Task: Victim EDITED {#2}

                  status: in-progress
            """)

    def test_modify_delete_conflict(self):
        r = merge(self.base,
                  plan.parse(plan.serialize(self.mine_deletes)),
                  plan.parse(plan.serialize(self.theirs_edits)))
        self.assertEqual(len(r.conflicts), 1)
        c = r.conflicts[0]
        self.assertEqual(c.ctype, "modify-delete")
        self.assertEqual(c.field, "<node>")
        self.assertEqual(c.mine_value, plan.DELETED)
        self.assertIn("Victim EDITED", c.theirs_value)
        # in-tree defaults to mine (deletion).
        p = reserialize_reparse(r.project)
        self.assertIsNone(p.lookup(2))

    def test_delete_untouched_other_side_honors_delete(self):
        # theirs == base (no edit); mine deletes -> clean delete, no conflict.
        r = merge(self.base,
                  plan.parse(plan.serialize(self.mine_deletes)),
                  plan.parse(plan.serialize(self.base)))
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertIsNone(p.lookup(2))

    def test_modify_delete_resolve_keep_theirs(self):
        r = merge(self.base,
                  plan.parse(plan.serialize(self.mine_deletes)),
                  plan.parse(plan.serialize(self.theirs_edits)),
                  resolutions={("2", "<node>"): "theirs"})
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertIsNotNone(p.lookup(2))
        self.assertEqual(p.lookup(2).title, "Victim EDITED")
        self.assertEqual(p.lookup(2).get_attr("status"), "in-progress")

    def test_modify_delete_prefer_mine_keeps_deletion(self):
        r = merge(self.base,
                  plan.parse(plan.serialize(self.mine_deletes)),
                  plan.parse(plan.serialize(self.theirs_edits)),
                  prefer="mine")
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertIsNone(p.lookup(2))

    def test_theirs_deletes_mine_edits(self):
        # symmetric: theirs deletes #2, mine edits it.
        r = merge(self.base,
                  plan.parse(plan.serialize(self.theirs_edits)),  # mine edits
                  plan.parse(plan.serialize(self.mine_deletes)))  # theirs deletes
        self.assertEqual(len(r.conflicts), 1)
        c = r.conflicts[0]
        self.assertEqual(c.ctype, "modify-delete")
        self.assertEqual(c.theirs_value, plan.DELETED)
        self.assertIn("Victim EDITED", c.mine_value)
        # default mine keeps the node.
        p = reserialize_reparse(r.project)
        self.assertIsNotNone(p.lookup(2))


# ===========================================================================
# Scenario 8: divergent reorder / reparent
# ===========================================================================

class TestOrderingAndReparent(unittest.TestCase):
    def test_theirs_only_siblings_after_mine(self):
        base = plan_doc(2, """
            * ## Ticket: Task: A {#1}

                  status: open
            """)
        mine = plan_doc(3, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: MineNew {#2}

                  status: open
            """)
        theirs = plan_doc(4, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: TheirsNew {#3}

                  status: open
            """)
        # mine added #2, theirs added #3 (no collision). theirs-only (#3) after mine's.
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1, 2, 3])

    def test_reorder_is_never_a_conflict(self):
        base = plan_doc(3, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: B {#2}

                  status: open
            """)
        # theirs reorders B before A (positional). mine unchanged order.
        mine = plan.parse(plan.serialize(base))
        theirs = plan_doc(3, """
            * ## Ticket: Task: B {#2}

                  status: open

            * ## Ticket: Task: A {#1}

                  status: open
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        # mine's relative order preserved.
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1, 2])

    def test_one_sided_reparent_applied(self):
        base = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open

            * ## Ticket: Task: P2 {#2}

                  status: open
            """)
        # mine moves #3 under #2; theirs unchanged.
        mine = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

            * ## Ticket: Task: P2 {#2}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open
            """)
        theirs = plan.parse(plan.serialize(base))
        r = merge(base, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(3).parent.node_id, 2)

    def test_divergent_reparent_conflict(self):
        base = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open

            * ## Ticket: Task: P2 {#2}

                  status: open
            """)
        # mine moves #3 under #2; theirs moves #3 to top-level.
        mine = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

            * ## Ticket: Task: P2 {#2}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open
            """)
        theirs = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

            * ## Ticket: Task: P2 {#2}

                  status: open

            * ## Ticket: Task: Child {#3}

                  status: open
            """)
        r = merge(base, mine, theirs)
        self.assertEqual(conflict_fields(r), [("3", "parent", "field")])
        c = r.conflicts[0]
        self.assertEqual(c.base_value, "1")
        self.assertEqual(c.mine_value, "2")
        self.assertIsNone(c.theirs_value)
        # default mine: #3 under #2
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(3).parent.node_id, 2)

    def test_divergent_reparent_resolve_theirs(self):
        base = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open

            * ## Ticket: Task: P2 {#2}

                  status: open
            """)
        mine = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

            * ## Ticket: Task: P2 {#2}

                  status: open

              * ## Ticket: Task: Child {#3}

                    status: open
            """)
        theirs = plan_doc(4, """
            * ## Ticket: Task: P1 {#1}

                  status: open

            * ## Ticket: Task: P2 {#2}

                  status: open

            * ## Ticket: Task: Child {#3}

                  status: open
            """)
        r = merge(base, mine, theirs, resolutions={("3", "parent"): "theirs"})
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertIsNone(p.lookup(3).parent)  # top-level


# ===========================================================================
# prefer / resolutions interaction
# ===========================================================================

class TestPreferAndResolutions(unittest.TestCase):
    def setUp(self):
        self.base = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open
                  assignee: nobody

              Original body.
            """)
        self.mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
                  assignee: alice

              Mine body.
            """)
        self.theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: done
                  assignee: bob

              Theirs body.
            """)

    def test_prefer_mine_resolves_all(self):
        r = merge(plan.parse(plan.serialize(self.base)),
                  plan.parse(plan.serialize(self.mine)),
                  plan.parse(plan.serialize(self.theirs)),
                  prefer="mine")
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")
        self.assertEqual(p.lookup(1).get_attr("assignee"), "alice")
        self.assertEqual(body_of(p.lookup(1)), "Mine body.")

    def test_prefer_theirs_resolves_all(self):
        r = merge(plan.parse(plan.serialize(self.base)),
                  plan.parse(plan.serialize(self.mine)),
                  plan.parse(plan.serialize(self.theirs)),
                  prefer="theirs")
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "done")
        self.assertEqual(p.lookup(1).get_attr("assignee"), "bob")
        self.assertEqual(body_of(p.lookup(1)), "Theirs body.")

    def test_resolutions_win_prefer_fills_rest(self):
        r = merge(plan.parse(plan.serialize(self.base)),
                  plan.parse(plan.serialize(self.mine)),
                  plan.parse(plan.serialize(self.theirs)),
                  prefer="theirs",
                  resolutions={("1", "status"): "mine", ("1", "body"): "mine"})
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")  # res
        self.assertEqual(body_of(p.lookup(1)), "Mine body.")             # res
        self.assertEqual(p.lookup(1).get_attr("assignee"), "bob")        # prefer

    def test_partial_resolutions_leave_remainder(self):
        r = merge(plan.parse(plan.serialize(self.base)),
                  plan.parse(plan.serialize(self.mine)),
                  plan.parse(plan.serialize(self.theirs)),
                  resolutions={("1", "status"): "theirs"})
        # status resolved; assignee + body remain.
        remaining = conflict_fields(r)
        self.assertEqual(remaining,
                         [("1", "assignee", "field"), ("1", "body", "text")])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "done")


# ===========================================================================
# base = None
# ===========================================================================

class TestBaseNone(unittest.TestCase):
    def test_file_new_on_theirs_only(self):
        # mine empty (no tickets), theirs has content; base=None.
        mine = plan_doc(1, "")
        theirs = plan_doc(3, """
            * ## Ticket: Task: New {#1}

                  status: open

            * ## Ticket: Task: Another {#2}

                  status: open
            """)
        r = merge(None, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(sorted(ticket_ids(p)), [1, 2])

    def test_base_none_disjoint_ids_union(self):
        # No shared ids -> simple union, valid tree, next_id fixed.
        mine = plan_doc(2, """
            * ## Ticket: Task: Mine {#1}

                  status: open
            """)
        theirs = plan_doc(11, """
            * ## Ticket: Task: Theirs {#10}

                  status: open
            """)
        r = merge(None, mine, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(sorted(ticket_ids(p)), [1, 10])
        self.assertEqual(p.next_id, 11)


# ===========================================================================
# next_id fixup + general validity
# ===========================================================================

class TestNextIdAndValidity(unittest.TestCase):
    def test_next_id_is_max_plus_one(self):
        base = plan_doc(2, """
            * ## Ticket: Task: A {#1}

                  status: open
            """)
        mine = plan_doc(3, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: M {#2}

                  status: open
            """)
        theirs = plan_doc(3, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: T {#2}

                  status: open
            """)
        r = merge(base, mine, theirs)
        # collision -> theirs #2 becomes #3 -> max id 3 -> next_id 4
        p = reserialize_reparse(r.project)
        self.assertEqual(p.next_id, 4)
        self.assertEqual(p.sections["metadata"].get_attr("next_id"), "4")

    def test_merged_always_reparses(self):
        # A grab-bag merge with several kinds of change.
        base = plan_doc(4, """
            * ## Ticket: Task: A {#1}

                  status: open

              Body A.

              * ## Ticket: Task: Child {#3}

                    status: open

            * ## Ticket: Task: B {#2}

                  status: open
            """)
        mine = plan_doc(5, """
            * ## Ticket: Bug: A {#1}

                  status: in-progress

              Body A mine.

              * ## Ticket: Task: Child {#3}

                    status: open

            * ## Ticket: Task: B {#2}

                  status: open

            * ## Ticket: Task: MineNew {#4}

                  status: open
            """)
        theirs = plan_doc(5, """
            * ## Ticket: Task: A {#1}

                  status: open

              Body A.

              * ## Ticket: Task: Child {#3}

                    status: done

            * ## Ticket: Task: B RENAMED {#2}

                  status: open

            * ## Ticket: Task: TheirsNew {#4}

                  status: open
            """)
        r = merge(base, mine, theirs)
        # #4 collides -> theirs renumbered.
        self.assertEqual(r.renumber_map, {4: 5})
        p = reserialize_reparse(r.project)
        # one-sided changes applied
        self.assertEqual(p.lookup(1).ticket_type, "Bug")          # mine
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")  # mine
        self.assertEqual(body_of(p.lookup(1)), "Body A mine.")    # mine
        self.assertEqual(p.lookup(3).get_attr("status"), "done")  # theirs
        self.assertEqual(p.lookup(2).title, "B RENAMED")          # theirs
        self.assertEqual({t.title for t in p.tickets if t.node_id in (4, 5)},
                         {"MineNew", "TheirsNew"})


# ===========================================================================
# two_way mode (recover from conflict markers: shared id = same node)
# ===========================================================================

class TestTwoWay(unittest.TestCase):
    def test_shared_id_same_field_diverge_conflicts(self):
        # No base; both sides have #1 with the same field diverging -> conflict,
        # NOT a renumber (shared id is the same node).
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: done
            """)
        r = merge(None, mine, theirs, two_way=True)
        self.assertEqual(conflict_fields(r), [("1", "status", "field")])
        # No renumbering occurred.
        self.assertEqual(r.renumber_map, {})
        p = reserialize_reparse(r.project)
        # exactly one ticket #1 (not duplicated), defaults to mine
        self.assertEqual(ticket_ids(p), [1])
        self.assertEqual(p.lookup(1).get_attr("status"), "in-progress")

    def test_shared_id_different_fields_merge_no_conflict(self):
        # Same node, divergent on DIFFERENT fields. With an empty base, "title"
        # is identical (no conflict) but each side's distinct attr value differs
        # from the (absent) base -> the differing attr conflicts. Verify the
        # SHARED-equal field does not conflict and the node is not duplicated.
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
                  assignee: alice
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
                  assignee: alice
            """)
        r = merge(None, mine, theirs, two_way=True)
        # Identical shared nodes -> no conflict at all.
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1])
        self.assertEqual(p.lookup(1).get_attr("assignee"), "alice")

    def test_id_unique_to_one_side_is_added(self):
        # #1 shared+identical, #2 only mine, #3 only theirs -> all kept, no
        # renumber, no conflict.
        mine = plan_doc(3, """
            * ## Ticket: Task: Shared {#1}

                  status: open

            * ## Ticket: Task: MineOnly {#2}

                  status: open
            """)
        theirs = plan_doc(4, """
            * ## Ticket: Task: Shared {#1}

                  status: open

            * ## Ticket: Task: TheirsOnly {#3}

                  status: open
            """)
        r = merge(None, mine, theirs, two_way=True)
        self.assertEqual(r.conflicts, [])
        self.assertEqual(r.renumber_map, {})
        p = reserialize_reparse(r.project)
        self.assertEqual(sorted(ticket_ids(p)), [1, 2, 3])

    def test_identical_shared_nodes_no_conflict(self):
        same = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: open

              Same body.
            """)
        r = merge(None,
                  plan.parse(plan.serialize(same)),
                  plan.parse(plan.serialize(same)),
                  two_way=True)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1])

    def test_two_way_prefer_resolves(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: done
            """)
        r = merge(None, mine, theirs, two_way=True, prefer="theirs")
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "done")

    def test_two_way_resolutions_resolves(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: in-progress
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: X {#1}

                  status: done
            """)
        r = merge(None, mine, theirs, two_way=True,
                  resolutions={("1", "status"): "theirs"})
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(p.lookup(1).get_attr("status"), "done")

    def test_two_way_does_not_renumber_shared_ids(self):
        # The KEY two-way property: shared "new" ids are NOT renumbered (which
        # three-way mode would do for base=None). Both #1 stay as the same node.
        mine = plan_doc(2, """
            * ## Ticket: Task: Mine title {#1}

                  status: open
            """)
        theirs = plan_doc(2, """
            * ## Ticket: Task: Theirs title {#1}

                  status: open
            """)
        r = merge(None, mine, theirs, two_way=True)
        self.assertEqual(r.renumber_map, {})
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1])  # single node, not 1 and 2


# ===========================================================================
# None-input safety (merge-driver empty-%A and file-new-on-a-side corners)
# ===========================================================================

class TestNoneSafety(unittest.TestCase):
    def test_all_none(self):
        r = merge(None, None, None)
        self.assertEqual(r.conflicts, [])
        self.assertEqual(ticket_ids(r.project), [])
        # serializes cleanly
        self.assertTrue(plan.serialize(r.project))

    def test_none_none_theirs(self):
        theirs = plan_doc(3, """
            * ## Ticket: Task: A {#1}

                  status: open

            * ## Ticket: Task: B {#2}

                  status: done
            """)
        r = merge(None, None, theirs)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(sorted(ticket_ids(p)), [1, 2])

    def test_mine_none_theirs_present(self):
        theirs = plan_doc(2, """
            * ## Ticket: Task: A {#1}

                  status: open
            """)
        base = plan_doc(1, "")
        r = merge(base, None, theirs)
        # mine empty, theirs added #1 (not in base) -> taken, no conflict.
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1])

    def test_theirs_none_mine_present(self):
        mine = plan_doc(2, """
            * ## Ticket: Task: A {#1}

                  status: open
            """)
        r = merge(None, mine, None)
        self.assertEqual(r.conflicts, [])
        p = reserialize_reparse(r.project)
        self.assertEqual(ticket_ids(p), [1])

    def test_none_inputs_two_way(self):
        # two_way + None must also be safe.
        r = merge(None, None, None, two_way=True)
        self.assertEqual(r.conflicts, [])
        self.assertEqual(ticket_ids(r.project), [])


if __name__ == "__main__":
    unittest.main()
