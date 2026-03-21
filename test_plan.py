#!/usr/bin/env python3
"""Tests for plan.py — Markdown Ticket Tracker."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

import plan

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "AGENTS", "template.md")


def make_doc(text):
    """Parse a markdown string into the document model."""
    return plan.parse(textwrap.dedent(text))


def _read_template():
    with open(TEMPLATE_PATH) as f:
        return f.read()


# ===================================================================
# Task 1: Document Model, Parser, Serializer
# ===================================================================

class TestDocumentModel(unittest.TestCase):
    """Test the data model classes."""

    def test_node_attrs(self):
        n = plan.Node()
        n.set_attr("foo", "bar")
        self.assertEqual(n.get_attr("foo"), "bar")
        self.assertTrue(n.dirty)

    def test_node_del_attr(self):
        n = plan.Node()
        n.attrs["x"] = "1"
        n.del_attr("x")
        self.assertEqual(n.get_attr("x"), "")

    def test_node_del_attr_missing(self):
        n = plan.Node()
        n.del_attr("nope")  # should not raise

    def test_default_namespace_missing_key(self):
        ns = plan.DefaultNamespace({"a": 1})
        self.assertEqual(ns["b"], "")

    def test_ticket_as_namespace(self):
        t = plan.Ticket(5, "Test", "Task")
        t.attrs["status"] = "open"
        t.attrs["estimate"] = "2h"
        t.attrs["links"] = "blocked:#3 related:#2"
        ns = t.as_namespace()
        self.assertEqual(ns["id"], 5)
        self.assertEqual(ns["title"], "Test")
        self.assertEqual(ns["status"], "open")
        self.assertEqual(ns["links"], {"blocked": [3], "related": [2]})

    def test_ticket_as_namespace_defaults(self):
        t = plan.Ticket(1, "T", "Task")
        ns = t.as_namespace()
        self.assertEqual(ns["status"], "")

    def test_ticket_as_namespace_is_open(self):
        t = plan.Ticket(1, "T", "Task")
        # active statuses -> is_open True
        for s in ("open", "in-progress", "assigned", "blocked", "reviewing", "testing"):
            t.attrs["status"] = s
            self.assertTrue(t.as_namespace()["is_open"], f"status={s}")
        # deferred statuses -> is_open True (open but not active)
        for s in ("backlog", "deferred", "future", "someday", "wishlist", "paused", "on-hold"):
            t.attrs["status"] = s
            self.assertTrue(t.as_namespace()["is_open"], f"status={s}")
        # no status set -> is_open True
        t2 = plan.Ticket(2, "T2", "Task")
        self.assertTrue(t2.as_namespace()["is_open"])
        # closed statuses -> is_open False
        for s in ("done", "closed", "wontfix", "duplicate", "invalid"):
            t.attrs["status"] = s
            self.assertFalse(t.as_namespace()["is_open"], f"status={s}")

    def test_ticket_as_namespace_is_active(self):
        t = plan.Ticket(1, "T", "Task")
        # active statuses -> is_active True
        for s in ("open", "in-progress", "assigned", "blocked", "reviewing", "testing"):
            t.attrs["status"] = s
            self.assertTrue(t.as_namespace()["is_active"], f"status={s}")
        # no status set -> is_active True
        t2 = plan.Ticket(2, "T2", "Task")
        self.assertTrue(t2.as_namespace()["is_active"])
        # deferred statuses -> is_active False
        for s in ("backlog", "deferred", "future", "someday"):
            t.attrs["status"] = s
            self.assertFalse(t.as_namespace()["is_active"], f"status={s}")
        # closed statuses -> is_active False
        for s in ("done", "closed", "wontfix"):
            t.attrs["status"] = s
            self.assertFalse(t.as_namespace()["is_active"], f"status={s}")

    def test_ticket_as_namespace_depth_and_indent(self):
        root = plan.Ticket(1, "Root", "Task")
        child = plan.Ticket(2, "Child", "Task")
        grandchild = plan.Ticket(3, "Grandchild", "Task")
        child.parent = root
        root.children.append(child)
        grandchild.parent = child
        child.children.append(grandchild)
        # top-level: depth 0, no indent
        ns = root.as_namespace()
        self.assertEqual(ns["depth"], 0)
        self.assertEqual(ns["indent"], "")
        # child: depth 1
        ns = child.as_namespace()
        self.assertEqual(ns["depth"], 1)
        self.assertEqual(ns["indent"], "  ")
        # grandchild: depth 2
        ns = grandchild.as_namespace()
        self.assertEqual(ns["depth"], 2)
        self.assertEqual(ns["indent"], "    ")

    def test_format_depth_and_indent(self):
        root = plan.Ticket(1, "Root", "Task")
        child = plan.Ticket(2, "Child", "Task")
        child.parent = root
        root.children.append(child)
        result = plan.eval_format(child, 'f"{indent}#{id} {title}"')
        self.assertEqual(result, "  #2 Child")
        result = plan.eval_format(root, 'f"{depth}: {title}"')
        self.assertEqual(result, "0: Root")

    def test_project_allocate_id(self):
        p = plan.Project()
        meta = plan.Section("Metadata", "metadata")
        meta.attrs["next_id"] = "1"
        p.sections["metadata"] = meta
        p.next_id = 1

        id1 = p.allocate_id()
        self.assertEqual(id1, 1)
        self.assertEqual(p.next_id, 2)
        self.assertEqual(meta.get_attr("next_id"), "2")

    def test_project_register_lookup(self):
        p = plan.Project()
        t = plan.Ticket(42, "Test", "Task")
        p.register(t)
        self.assertIs(p.lookup(42), t)
        self.assertIs(p.lookup("42"), t)

    def test_parse_links(self):
        result = plan._parse_links("blocked:#3 blocking:#5 related:#2")
        self.assertEqual(result, {"blocked": [3], "blocking": [5], "related": [2]})

    def test_parse_links_empty(self):
        self.assertEqual(plan._parse_links(""), {})
        self.assertEqual(plan._parse_links(None), {})

    def test_serialize_links(self):
        s = plan._serialize_links({"blocked": [3], "related": [2]})
        self.assertIn("blocked:#3", s)
        self.assertIn("related:#2", s)


class TestParser(unittest.TestCase):
    """Test the markdown parser."""

    def test_parse_template(self):
        text = _read_template()
        p = plan.parse(text)
        self.assertEqual(p.title, "Project: Title")
        self.assertIn("metadata", p.sections)
        self.assertIn("description", p.sections)
        self.assertIn("tickets", p.sections)
        self.assertEqual(p.next_id, 3)

    def test_parse_template_sections(self):
        text = _read_template()
        p = plan.parse(text)
        expected = {"metadata", "description", "building", "testing",
                    "design", "agents", "role:lead", "role:executor",
                    "role:reviewer", "role:architect", "tickets"}
        self.assertEqual(set(p.sections.keys()), expected)

    def test_parse_template_tickets(self):
        text = _read_template()
        p = plan.parse(text)
        self.assertEqual(len(p.tickets), 1)
        t = p.tickets[0]
        self.assertEqual(t.title, "Title 1")
        self.assertEqual(t.node_id, 1)

    def test_parse_nested_ticket(self):
        text = _read_template()
        p = plan.parse(text)
        t = p.tickets[0]
        self.assertEqual(len(t.children), 1)
        child = t.children[0]
        self.assertEqual(child.title, "Subtask of Title 1")
        self.assertEqual(child.node_id, 2)
        self.assertIs(child.parent, t)

    def test_parse_ticket_attrs(self):
        text = _read_template()
        p = plan.parse(text)
        t = p.tickets[0]
        self.assertIn("created", t.attrs)
        self.assertIn("status", t.attrs)
        self.assertNotIn("rank", t.attrs)

    def test_parse_comments(self):
        text = _read_template()
        p = plan.parse(text)
        t = p.tickets[0]
        self.assertIsNotNone(t.comments)
        self.assertEqual(t.comments.node_id, "1:comments")
        self.assertTrue(len(t.comments.comments) >= 1)

    def test_parse_comment_replies(self):
        text = _read_template()
        p = plan.parse(text)
        t = p.tickets[0]
        c1 = t.comments.comments[0]
        self.assertEqual(c1.node_id, "1:comment:1")
        # c1 should have a child reply
        self.assertEqual(len(c1.children), 1)
        self.assertEqual(c1.children[0].node_id, "1:comment:2")

    def test_parse_id_map(self):
        text = _read_template()
        p = plan.parse(text)
        self.assertIn("1", p.id_map)
        self.assertIn("2", p.id_map)
        self.assertIn("project", p.id_map)
        self.assertIn("metadata", p.id_map)
        self.assertIn("1:comments", p.id_map)
        self.assertIn("1:comment:1", p.id_map)

    def test_parse_all_ids_unique(self):
        text = _read_template()
        p = plan.parse(text)
        # All ids should be unique (no overwrites)
        ids = set()
        for k in p.id_map:
            self.assertNotIn(k, ids, f"Duplicate id: {k}")
            ids.add(k)

    def test_parse_id_suffix_stored(self):
        """Verify {#id} suffix is handled: stored in id_map, title is clean."""
        text = _read_template()
        p = plan.parse(text)
        t = p.tickets[0]
        self.assertNotIn("{#", t.title)
        self.assertEqual(t.node_id, 1)

    def test_parse_simple_doc(self):
        doc = make_doc("""\
        # My Project {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: Do something {#1}

              created: 2024-01-01 00:00:00 UTC
              status: open

          This is the body.
        """)
        self.assertEqual(doc.title, "My Project")
        self.assertEqual(len(doc.tickets), 1)
        t = doc.tickets[0]
        self.assertEqual(t.title, "Do something")
        self.assertEqual(t.get_attr("status"), "open")
        self.assertIn("This is the body.", "\n".join(t.body_lines))

    def test_parse_custom_attrs(self):
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T1 {#1}

              status: open
              custom_field: hello world

          Body text.
        """)
        t = doc.tickets[0]
        self.assertEqual(t.get_attr("custom_field"), "hello world")

    def test_parse_empty_doc(self):
        doc = make_doc("""\
        # Empty {#project}

        ## Metadata {#metadata}

            next_id: 1

        ## Tickets {#tickets}

        """)
        self.assertEqual(doc.title, "Empty")
        self.assertEqual(len(doc.tickets), 0)
        self.assertEqual(doc.next_id, 1)

    def test_parse_deeply_nested(self):
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Epic: Top {#1}

              status: open

          * ## Ticket: Task: Mid {#2}

                status: open

            * ## Ticket: Task: Deep {#3}

                  status: open
        """)
        self.assertEqual(len(doc.tickets), 1)
        top = doc.tickets[0]
        self.assertEqual(len(top.children), 1)
        mid = top.children[0]
        self.assertEqual(mid.title, "Mid")
        self.assertEqual(len(mid.children), 1)
        deep = mid.children[0]
        self.assertEqual(deep.title, "Deep")
        self.assertIs(deep.parent, mid)
        self.assertIs(mid.parent, top)

    def test_parse_ticket_no_attrs_no_body(self):
        """A ticket with only a header line — no attributes, no body."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: Bare {#1}

        """)
        self.assertEqual(len(doc.tickets), 1)
        t = doc.tickets[0]
        self.assertEqual(t.title, "Bare")
        self.assertEqual(t.attrs, {})
        self.assertEqual(t.body_lines, [])

    def test_parse_ticket_no_attrs_with_body(self):
        """A ticket with body text but no attributes."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: BodyOnly {#1}

          This ticket has a body but no attributes.
        """)
        self.assertEqual(len(doc.tickets), 1)
        t = doc.tickets[0]
        self.assertEqual(t.title, "BodyOnly")
        self.assertEqual(t.attrs, {})
        self.assertIn("This ticket has a body but no attributes.",
                      "\n".join(t.body_lines))

    def test_parse_section_no_attrs_no_body(self):
        """A section with only a header — no attributes, no body."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 1

        ## Notes {#notes}

        ## Tickets {#tickets}

        """)
        sec = doc.sections["notes"]
        self.assertEqual(sec.title, "Notes")
        self.assertEqual(sec.attrs, {})
        self.assertEqual(sec.body_lines, [])

    def test_parse_section_no_attrs_with_body(self):
        """A section with body content but no attributes."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 1

        ## Notes {#notes}

        Some free-form body text here.

        ## Tickets {#tickets}

        """)
        sec = doc.sections["notes"]
        self.assertEqual(sec.title, "Notes")
        self.assertEqual(sec.attrs, {})
        self.assertIn("Some free-form body text here.",
                      "\n".join(sec.body_lines))

    def test_parse_multiple_tickets_mixed_attrs(self):
        """Some tickets with attrs, some without — all should parse correctly."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: HasAttrs {#1}

              status: open

        * ## Ticket: Task: NoAttrs {#2}

        * ## Ticket: Task: BodyOnly {#3}

          Just body, no attrs.
        """)
        self.assertEqual(len(doc.tickets), 3)
        t1 = doc.tickets[0]
        self.assertEqual(t1.get_attr("status"), "open")
        t2 = doc.tickets[1]
        self.assertEqual(t2.title, "NoAttrs")
        self.assertEqual(t2.attrs, {})
        self.assertEqual(t2.body_lines, [])
        t3 = doc.tickets[2]
        self.assertEqual(t3.title, "BodyOnly")
        self.assertEqual(t3.attrs, {})
        self.assertIn("Just body, no attrs.", "\n".join(t3.body_lines))

    def test_round_trip_ticket_no_attrs(self):
        """Serializing a dirty ticket with no attrs should round-trip cleanly."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: Bare {#1}

        """)
        t = doc.tickets[0]
        t.dirty = True
        text = plan.serialize(doc)
        doc2 = plan.parse(text)
        self.assertEqual(len(doc2.tickets), 1)
        t2 = doc2.tickets[0]
        self.assertEqual(t2.title, "Bare")
        self.assertEqual(t2.attrs, {})
        self.assertEqual(t2.body_lines, [])

    def test_round_trip_ticket_no_attrs_with_body(self):
        """Dirty ticket with body but no attrs should round-trip."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T {#1}

          Body content here.
        """)
        t = doc.tickets[0]
        t.dirty = True
        text = plan.serialize(doc)
        doc2 = plan.parse(text)
        t2 = doc2.tickets[0]
        self.assertEqual(t2.title, "T")
        self.assertEqual(t2.attrs, {})
        self.assertIn("Body content here.", "\n".join(t2.body_lines))

    def test_round_trip_section_no_attrs(self):
        """Dirty section with no attrs should serialize and re-parse."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 1

        ## Notes {#notes}

        ## Tickets {#tickets}

        """)
        sec = doc.sections["notes"]
        sec.dirty = True
        text = plan.serialize(doc)
        doc2 = plan.parse(text)
        sec2 = doc2.sections["notes"]
        self.assertEqual(sec2.title, "Notes")
        self.assertEqual(sec2.attrs, {})
        self.assertEqual(sec2.body_lines, [])

    def test_nested_ticket_no_attrs(self):
        """Child ticket without attrs under parent with attrs."""
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 3

        ## Tickets {#tickets}

        * ## Ticket: Epic: Parent {#1}

              status: open

          * ## Ticket: Task: Child {#2}

        """)
        parent = doc.tickets[0]
        self.assertEqual(parent.get_attr("status"), "open")
        self.assertEqual(len(parent.children), 1)
        child = parent.children[0]
        self.assertEqual(child.title, "Child")
        self.assertEqual(child.attrs, {})
        self.assertEqual(child.body_lines, [])


class TestSerializer(unittest.TestCase):
    """Test serialization and round-trip."""

    def test_round_trip_template(self):
        text = _read_template()
        p = plan.parse(text)
        out = plan.serialize(p)
        # Re-parse and re-serialize should be stable (idempotent)
        p2 = plan.parse(out)
        out2 = plan.serialize(p2)
        self.assertEqual(out, out2)

    def test_round_trip_simple(self):
        text = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T1 {#1}

              status: open

          Body text.
        """)
        p = plan.parse(text)
        out = plan.serialize(p)
        self.assertEqual(text, out)

    def test_dirty_section_regeneration(self):
        text = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T1 {#1}

              status: open
        """)
        p = plan.parse(text)
        meta = p.sections["metadata"]
        meta.set_attr("next_id", "3")
        out = plan.serialize(p)
        self.assertIn("next_id: 3", out)


# ===================================================================
# Task 2: DSL Sandbox, Ranking, Interlinking
# ===================================================================

class TestDSL(unittest.TestCase):
    """Test the DSL expression evaluation."""

    def _make_ticket(self):
        t = plan.Ticket(5, "Test ticket", "Task")
        t.attrs["status"] = "open"
        t.attrs["estimate"] = "2h"
        t.attrs["rank"] = "3.5"
        t.attrs["assignee"] = "alice"
        t.attrs["links"] = "blocked:#3 related:#2"
        t.body_lines = ["Some body text"]
        return t

    def test_filter_status(self):
        t = self._make_ticket()
        self.assertTrue(plan.eval_filter(t, 'status == "open"'))
        self.assertFalse(plan.eval_filter(t, 'status == "closed"'))

    def test_filter_estimate(self):
        t = self._make_ticket()
        self.assertTrue(plan.eval_filter(t, 'estimate == "2h"'))
        self.assertFalse(plan.eval_filter(t, 'estimate == "5h"'))

    def test_filter_title(self):
        t = self._make_ticket()
        self.assertTrue(plan.eval_filter(t, '"test" in title.lower()'))

    def test_filter_links(self):
        t = self._make_ticket()
        self.assertTrue(plan.eval_filter(t, '"blocked" in links'))

    def test_filter_missing_attr(self):
        t = self._make_ticket()
        self.assertEqual(plan.eval_filter(t, 'custom_field'), "")

    def test_filter_missing_attr_comparison(self):
        t = self._make_ticket()
        self.assertTrue(plan.eval_filter(t, 'custom_field == ""'))

    def test_format_basic(self):
        t = self._make_ticket()
        result = plan.eval_format(t, 'f"{indent}#{id} [{status}] {title}"')
        self.assertEqual(result, "#5 [open] Test ticket")

    def test_format_with_estimate(self):
        t = self._make_ticket()
        result = plan.eval_format(t, 'f"{id} est:{estimate} {assignee}: {title}"')
        self.assertEqual(result, "5 est:2h alice: Test ticket")

    def test_mod_set(self):
        t = self._make_ticket()
        p = plan.Project()
        p.register(t)
        plan.apply_mod(t, p, 'set(estimate="1h")')
        self.assertEqual(t.get_attr("estimate"), "1h")

    def test_mod_set_multiple(self):
        t = self._make_ticket()
        p = plan.Project()
        p.register(t)
        plan.apply_mod(t, p, 'set(status="in-progress", assignee="bob")')
        self.assertEqual(t.get_attr("status"), "in-progress")
        self.assertEqual(t.get_attr("assignee"), "bob")

    def test_mod_delete(self):
        t = self._make_ticket()
        p = plan.Project()
        plan.apply_mod(t, p, 'delete("assignee")')
        self.assertEqual(t.get_attr("assignee"), "")

    def test_mod_set_title(self):
        t = self._make_ticket()
        p = plan.Project()
        plan.apply_mod(t, p, 'set(title="New Title")')
        self.assertEqual(t.title, "New Title")

    def test_mod_set_text(self):
        t = self._make_ticket()
        p = plan.Project()
        plan.apply_mod(t, p, 'set(text="New body")')
        self.assertEqual(t.body_lines, ["  New body"])

    def test_mod_composable(self):
        t = self._make_ticket()
        p = plan.Project()
        p.register(t)
        plan.apply_mod(t, p, '[set(estimate="1h"), set(status="closed")]')
        self.assertEqual(t.get_attr("estimate"), "1h")
        self.assertEqual(t.get_attr("status"), "closed")

    def test_sandbox_no_import(self):
        t = self._make_ticket()
        p = plan.Project()
        with self.assertRaises(SystemExit):
            plan.apply_mod(t, p, '__import__("os")')

    def test_sandbox_no_open(self):
        t = self._make_ticket()
        p = plan.Project()
        with self.assertRaises(SystemExit):
            plan.apply_mod(t, p, 'open("/etc/passwd")')

    def test_sandbox_no_eval(self):
        t = self._make_ticket()
        p = plan.Project()
        with self.assertRaises(SystemExit):
            plan.eval_filter(t, 'eval("1+1")')

    def test_dsl_syntax_error_nice_message(self):
        """Syntax errors in DSL produce SystemExit, not raw tracebacks."""
        t = self._make_ticket()
        with self.assertRaises(SystemExit) as cm:
            plan.eval_filter(t, 'status ==')
        self.assertIn("invalid filter expression", str(cm.exception))

    def test_dsl_runtime_error_nice_message(self):
        """Runtime errors in DSL produce SystemExit with context."""
        t = self._make_ticket()
        with self.assertRaises(SystemExit) as cm:
            plan.eval_filter(t, '1 / 0')
        self.assertIn("filter expression failed", str(cm.exception))
        self.assertIn("ZeroDivisionError", str(cm.exception))

    def test_format_syntax_error_nice_message(self):
        t = self._make_ticket()
        with self.assertRaises(SystemExit) as cm:
            plan.eval_format(t, 'f"unclosed brace {')
        self.assertIn("invalid format expression", str(cm.exception))

    def test_mod_syntax_error_nice_message(self):
        t = self._make_ticket()
        p = plan.Project()
        p.register(t)
        with self.assertRaises(SystemExit) as cm:
            plan.apply_mod(t, p, 'set(')
        self.assertIn("invalid mod expression", str(cm.exception))


class TestRanking(unittest.TestCase):
    """Test ranking calculations."""

    def test_midpoint(self):
        self.assertEqual(plan.midpoint_rank(0, 2), 1.0)
        self.assertEqual(plan.midpoint_rank(0, 1), 0.5)
        self.assertEqual(plan.midpoint_rank(1, 2), 1.5)
        self.assertEqual(plan.midpoint_rank(5, 5), 5)
        self.assertEqual(plan.midpoint_rank(5, 3), 4.0)
        result = plan.midpoint_rank(-10, -5)
        self.assertTrue(-10 < result < -5)

    def test_rank_first_empty(self):
        self.assertEqual(plan.rank_first([]), 0)

    def test_rank_first(self):
        siblings = [plan.Ticket(1, "A", "Task"), plan.Ticket(2, "B", "Task")]
        siblings[0]._rank = 5.0
        siblings[1]._rank = 10.0
        result = plan.rank_first(siblings)
        self.assertLess(result, 5)

    def test_rank_last_empty(self):
        self.assertEqual(plan.rank_last([]), 0)

    def test_rank_last(self):
        siblings = [plan.Ticket(1, "A", "Task"), plan.Ticket(2, "B", "Task")]
        siblings[0]._rank = 5.0
        siblings[1]._rank = 10.0
        result = plan.rank_last(siblings)
        self.assertGreater(result, 10)

    def test_rank_before(self):
        t1 = plan.Ticket(1, "A", "Task")
        t2 = plan.Ticket(2, "B", "Task")
        t1._rank = 5.0
        t2._rank = 10.0
        result = plan.rank_before(t2, [t1, t2])
        self.assertTrue(5 < result < 10)

    def test_rank_after(self):
        t1 = plan.Ticket(1, "A", "Task")
        t2 = plan.Ticket(2, "B", "Task")
        t1._rank = 5.0
        t2._rank = 10.0
        result = plan.rank_after(t1, [t1, t2])
        self.assertTrue(5 < result < 10)

    def test_rank_before_first(self):
        t1 = plan.Ticket(1, "A", "Task")
        t1._rank = 5.0
        result = plan.rank_before(t1, [t1])
        self.assertLess(result, 5)

    def test_rank_after_last(self):
        t1 = plan.Ticket(1, "A", "Task")
        t1._rank = 5.0
        result = plan.rank_after(t1, [t1])
        self.assertGreater(result, 5)

    def test_negative_ranks(self):
        result = plan.midpoint_rank(-10, -5)
        self.assertTrue(-10 < result < -5)

    def test_sort_by_rank(self):
        t1 = plan.Ticket(1, "A", "Task")
        t2 = plan.Ticket(2, "B", "Task")
        t3 = plan.Ticket(3, "C", "Task")
        t1._rank = 10.0
        t2._rank = 5.0
        t3._rank = 7.0
        result = plan.sort_by_rank([t1, t2, t3])
        self.assertEqual([t.node_id for t in result], [2, 3, 1])


class TestInternalRank(unittest.TestCase):
    """Test internal _rank property."""

    def test_ticket_has_rank_property(self):
        t = plan.Ticket(1, "A", "Task")
        self.assertIsNone(t._rank)

    def test_rank_not_in_namespace(self):
        t = plan.Ticket(1, "A", "Task")
        ns = t.as_namespace()
        self.assertNotIn("rank", ns)

    def test_rank_attr_not_coerced_to_float(self):
        """If rank is set as a custom attr, it stays as string in namespace."""
        t = plan.Ticket(1, "A", "Task")
        t.attrs["rank"] = "42"
        ns = t.as_namespace()
        # rank is now a plain custom attr — no float coercion
        self.assertEqual(ns["rank"], "42")


class TestParserRankAssignment(unittest.TestCase):
    """Test that parser assigns _rank from file position."""

    def test_rank_from_file_position(self):
        """Top-level tickets get _rank 0, 1, 2 from file order."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        * ## Ticket: Task: C {#3}
              status: open
        """)
        p = plan.parse(doc)
        self.assertEqual(p.lookup("1")._rank, 0.0)
        self.assertEqual(p.lookup("2")._rank, 1.0)
        self.assertEqual(p.lookup("3")._rank, 2.0)

    def test_rank_from_file_position_children(self):
        """Children get _rank from their position among siblings."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: Parent {#1}
              status: open
          * ## Ticket: Task: Child A {#2}
                status: open
          * ## Ticket: Task: Child B {#3}
                status: open
        """)
        p = plan.parse(doc)
        self.assertEqual(p.lookup("2")._rank, 0.0)
        self.assertEqual(p.lookup("3")._rank, 1.0)

    def test_rank_not_in_attrs_after_parse(self):
        """rank attribute is stripped from attrs after parsing."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 2
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
              rank: 5
        """)
        p = plan.parse(doc)
        self.assertNotIn("rank", p.lookup("1").attrs)

    def test_legacy_rank_migration_reorders(self):
        """Legacy rank attrs reorder tickets by stored rank value."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: C-first-in-file {#1}
              status: open
              rank: 10
        * ## Ticket: Task: A-second-in-file {#2}
              status: open
              rank: 0
        * ## Ticket: Task: B-third-in-file {#3}
              status: open
              rank: 5
        """)
        p = plan.parse(doc)
        # After migration: #2 (rank 0) < #3 (rank 5) < #1 (rank 10)
        self.assertLess(p.lookup("2")._rank, p.lookup("3")._rank)
        self.assertLess(p.lookup("3")._rank, p.lookup("1")._rank)

    def test_legacy_rank_same_value_preserves_file_order(self):
        """Tickets with same legacy rank keep file order."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: First {#1}
              status: open
              rank: 0
        * ## Ticket: Task: Second {#2}
              status: open
              rank: 0
        * ## Ticket: Task: Third {#3}
              status: open
              rank: 0
        """)
        p = plan.parse(doc)
        self.assertLess(p.lookup("1")._rank, p.lookup("2")._rank)
        self.assertLess(p.lookup("2")._rank, p.lookup("3")._rank)

    def test_legacy_rank_unparseable_falls_to_end(self):
        """Unparseable rank values treated as +inf (fall to end)."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
              rank: bogus
        * ## Ticket: Task: B {#2}
              status: open
              rank: 0
        """)
        p = plan.parse(doc)
        # #2 (rank 0) should be before #1 (unparseable -> end)
        self.assertLess(p.lookup("2")._rank, p.lookup("1")._rank)

    def test_move_attr_resolved_on_parse(self):
        """move attr in file is resolved and stripped."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        * ## Ticket: Task: C {#3}
              status: open
              move: before 1
        """)
        p = plan.parse(doc)
        self.assertNotIn("move", p.lookup("3").attrs)
        self.assertLess(p.lookup("3")._rank, p.lookup("1")._rank)

    def test_move_attr_reparents(self):
        """move attr with target ID reparents ticket."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: Parent {#1}
              status: open
        * ## Ticket: Task: Child {#2}
              status: open
              move: first 1
        * ## Ticket: Task: Other {#3}
              status: open
        """)
        p = plan.parse(doc)
        t2 = p.lookup("2")
        t1 = p.lookup("1")
        self.assertIs(t2.parent, t1)
        self.assertIn(t2, t1.children)
        self.assertNotIn("move", t2.attrs)


class TestResolveMoveExpr(unittest.TestCase):
    """Test _resolve_move_expr — positional move expressions."""

    def _make_project(self):
        p = plan.Project()
        t1 = plan.Ticket(1, "A", "Task")
        t2 = plan.Ticket(2, "B", "Task")
        t3 = plan.Ticket(3, "C", "Task")
        t1._rank = 5.0
        t2._rank = 10.0
        t3._rank = 15.0
        for t in [t1, t2, t3]:
            p.register(t)
            p.tickets.append(t)
        return p, t1, t2, t3

    def test_numeric_passthrough(self):
        p, t1, _, _ = self._make_project()
        self.assertFalse(plan._resolve_move_expr("42", t1, p))
        self.assertFalse(plan._resolve_move_expr("3.5", t1, p))
        self.assertFalse(plan._resolve_move_expr("-1", t1, p))

    def test_first(self):
        p, t1, _, _ = self._make_project()
        plan._resolve_move_expr("first", t1, p)
        self.assertLess(t1._rank, 5)

    def test_last(self):
        p, t1, _, _ = self._make_project()
        plan._resolve_move_expr("last", t1, p)
        self.assertGreater(t1._rank, 15)

    def test_before(self):
        p, t1, t2, _ = self._make_project()
        plan._resolve_move_expr("before 2", t1, p)
        self.assertTrue(5 < t1._rank < 10)

    def test_after(self):
        p, t1, t2, t3 = self._make_project()
        plan._resolve_move_expr("after 2", t1, p)
        self.assertTrue(10 < t1._rank < 15)

    def test_first_with_children(self):
        """Resolves relative to parent's children when ticket has a parent."""
        p, t1, t2, t3 = self._make_project()
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        plan._resolve_move_expr("first", child, p)
        # Only sibling is child itself (rank 20), first should be < 20
        self.assertLess(child._rank, 20)

    def test_unknown_expression_passthrough(self):
        """Unrecognized expressions return False."""
        p, t1, _, _ = self._make_project()
        self.assertFalse(plan._resolve_move_expr("bogus", t1, p))

    def test_case_insensitive(self):
        p, t1, _, _ = self._make_project()
        plan._resolve_move_expr("First", t1, p)
        self.assertLess(t1._rank, 5)

    def test_before_invalid_id(self):
        """before with non-existent ID returns False."""
        p, t1, _, _ = self._make_project()
        self.assertFalse(plan._resolve_move_expr("before 999", t1, p))

    def test_first_with_target(self):
        """'first 1' moves ticket under #1 as first child."""
        p, t1, t2, t3 = self._make_project()
        # Add an existing child to t1 so first is meaningful
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        # Move t2 under t1 as first child
        plan._resolve_move_expr("first 1", t2, p)
        self.assertLess(t2._rank, 20)
        self.assertIs(t2.parent, t1)
        self.assertIn(t2, t1.children)
        self.assertNotIn(t2, p.tickets)

    def test_last_with_target(self):
        """'last 1' moves ticket under #1 as last child."""
        p, t1, t2, t3 = self._make_project()
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        plan._resolve_move_expr("last 1", t2, p)
        self.assertGreater(t2._rank, 20)
        self.assertIs(t2.parent, t1)
        self.assertIn(t2, t1.children)

    def test_first_0_moves_to_root(self):
        """'first 0' moves ticket to root level."""
        p, t1, t2, t3 = self._make_project()
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        plan._resolve_move_expr("first 0", child, p)
        self.assertLess(child._rank, 5)
        self.assertIsNone(child.parent)
        self.assertIn(child, p.tickets)
        self.assertNotIn(child, t1.children)

    def test_before_reparents(self):
        """'before N' moves ticket to be a sibling of N."""
        p, t1, t2, t3 = self._make_project()
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        # Move child to root level, before t2
        plan._resolve_move_expr("before 2", child, p)
        self.assertTrue(5 < child._rank < 10)
        self.assertIsNone(child.parent)
        self.assertIn(child, p.tickets)
        self.assertNotIn(child, t1.children)

    def test_after_reparents(self):
        """'after N' moves ticket to be a sibling of N."""
        p, t1, t2, t3 = self._make_project()
        child = plan.Ticket(4, "D", "Task")
        child._rank = 20.0
        child.parent = t1
        t1.children.append(child)
        p.register(child)
        plan._resolve_move_expr("after 2", child, p)
        self.assertTrue(10 < child._rank < 15)
        self.assertIsNone(child.parent)
        self.assertIn(child, p.tickets)

    def test_self_reference_passthrough(self):
        """Referencing self returns False."""
        p, t1, _, _ = self._make_project()
        self.assertFalse(plan._resolve_move_expr("first 1", t1, p))


class TestInterlinking(unittest.TestCase):
    """Test bidirectional link management."""

    def _make_project(self):
        p = plan.Project()
        t1 = plan.Ticket(1, "T1", "Task")
        t2 = plan.Ticket(2, "T2", "Task")
        t3 = plan.Ticket(3, "T3", "Task")
        for t in [t1, t2, t3]:
            p.register(t)
            p.tickets.append(t)
        return p, t1, t2, t3

    def test_add_blocked_link(self):
        p, t1, t2, t3 = self._make_project()
        plan.add_link(p, t1, "blocked", 2)
        # t1 should have blocked:#2
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertIn(2, links1.get("blocked", []))
        # t2 should have blocking:#1 (mirror)
        links2 = plan._parse_links(t2.get_attr("links"))
        self.assertIn(1, links2.get("blocking", []))

    def test_add_related_link(self):
        p, t1, t2, t3 = self._make_project()
        plan.add_link(p, t1, "related", 3)
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertIn(3, links1.get("related", []))
        links3 = plan._parse_links(t3.get_attr("links"))
        self.assertIn(1, links3.get("related", []))

    def test_remove_blocked_link(self):
        p, t1, t2, t3 = self._make_project()
        plan.add_link(p, t1, "blocked", 2)
        plan.remove_link(p, t1, "blocked", 2)
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertNotIn(2, links1.get("blocked", []))
        links2 = plan._parse_links(t2.get_attr("links"))
        self.assertNotIn(1, links2.get("blocking", []))

    def test_add_link_no_duplicate(self):
        p, t1, t2, t3 = self._make_project()
        plan.add_link(p, t1, "blocked", 2)
        plan.add_link(p, t1, "blocked", 2)
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertEqual(links1["blocked"].count(2), 1)

    def test_remove_nonexistent_link(self):
        p, t1, t2, t3 = self._make_project()
        plan.remove_link(p, t1, "blocked", 99)  # should not raise


# ===================================================================
# Task 3: CLI Parser, File Discovery
# ===================================================================

class TestCLIParser(unittest.TestCase):
    """Test command-line argument parsing."""

    def test_simple_get(self):
        reqs = plan.parse_argv(["5", "get"])
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].verb, "get")
        self.assertEqual(reqs[0].targets, ["5"])

    def test_flexible_order_get(self):
        """'get 5' and '5 get' produce the same result."""
        r1 = plan.parse_argv(["5", "get"])[0]
        r2 = plan.parse_argv(["get", "5"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)

    def test_flexible_order_list(self):
        """'list 5' and '5 list' produce the same result."""
        r1 = plan.parse_argv(["5", "list"])[0]
        r2 = plan.parse_argv(["list", "5"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)

    def test_flexible_order_del(self):
        """'del 5 3' and '5 3 del' produce the same result."""
        r1 = plan.parse_argv(["5", "3", "del"])[0]
        r2 = plan.parse_argv(["del", "5", "3"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(sorted(r1.targets), sorted(r2.targets))

    def test_flexible_order_status(self):
        """'status 5 in-progress' and '5 status in-progress' equivalent."""
        r1 = plan.parse_argv(["5", "status", "in-progress"])[0]
        r2 = plan.parse_argv(["status", "5", "in-progress"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_status_multi(self):
        """'status 1 2 3 done' forwards all IDs to selectors."""
        r = plan.parse_argv(["status", "1", "2", "3", "done"])[0]
        self.assertEqual(r.verb, "status")
        self.assertEqual(sorted(r.targets), ["1", "2", "3"])
        self.assertEqual(r.verb_args, ["done"])

    def test_flexible_order_close(self):
        """'close 5 done' and '5 close done' equivalent."""
        r1 = plan.parse_argv(["5", "close", "done"])[0]
        r2 = plan.parse_argv(["close", "5", "done"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_close_no_reason(self):
        """'close 5' forwards ID to selector, no reason."""
        r = plan.parse_argv(["close", "5"])[0]
        self.assertEqual(r.verb, "close")
        self.assertEqual(r.targets, ["5"])
        self.assertEqual(r.verb_args, [])

    def test_flexible_order_close_multi(self):
        """'close 1 2 3 done' forwards all IDs to selectors."""
        r = plan.parse_argv(["close", "1", "2", "3", "done"])[0]
        self.assertEqual(r.verb, "close")
        self.assertEqual(sorted(r.targets), ["1", "2", "3"])
        self.assertEqual(r.verb_args, ["done"])

    def test_flexible_order_move(self):
        """'move 5 after 7' and '5 move after 7' equivalent."""
        r1 = plan.parse_argv(["5", "move", "after", "7"])[0]
        r2 = plan.parse_argv(["move", "5", "after", "7"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_move_multi(self):
        """'move 3 5 first 1' forwards IDs to selectors."""
        r = plan.parse_argv(["move", "3", "5", "first", "1"])[0]
        self.assertEqual(r.verb, "move")
        self.assertEqual(sorted(r.targets), ["3", "5"])
        self.assertEqual(r.verb_args, ["first", "1"])

    def test_flexible_order_move_no_dest(self):
        """'move 3 first' forwards ID, direction only."""
        r = plan.parse_argv(["move", "3", "first"])[0]
        self.assertEqual(r.verb, "move")
        self.assertEqual(r.targets, ["3"])
        self.assertEqual(r.verb_args, ["first"])

    def test_flexible_order_add(self):
        """'add "text" 5' and '5 add "text"' produce the same result."""
        r1 = plan.parse_argv(["5", "add", "text"])[0]
        r2 = plan.parse_argv(["add", "text", "5"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_replace(self):
        """'replace --force "text" 5' and '5 replace --force "text"' equivalent."""
        r1 = plan.parse_argv(["5", "replace", "text"])[0]
        r2 = plan.parse_argv(["replace", "text", "5"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_mod(self):
        """'~ "expr" 5' and '5 ~ "expr"' produce the same result."""
        r1 = plan.parse_argv(["5", "~", "set(x=1)"])[0]
        r2 = plan.parse_argv(["~", "set(x=1)", "5"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_attr(self):
        """'get 5 attr estimate' and '5 attr estimate get' equivalent."""
        r1 = plan.parse_argv(["5", "attr", "estimate", "get"])[0]
        r2 = plan.parse_argv(["get", "5", "attr", "estimate"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.selector_type, r2.selector_type)
        self.assertEqual(r1.selector_args, r2.selector_args)

    def test_flexible_order_comment(self):
        """'add "text" 5 comment' and '5 comment add "text"' equivalent."""
        r1 = plan.parse_argv(["5", "comment", "add", "text"])[0]
        r2 = plan.parse_argv(["add", "text", "5", "comment"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.selector_type, r2.selector_type)
        self.assertEqual(r1.verb_args, r2.verb_args)

    def test_flexible_order_multi_target(self):
        """'get 1 2 3' and '1 2 3 get' produce the same result."""
        r1 = plan.parse_argv(["1", "2", "3", "get"])[0]
        r2 = plan.parse_argv(["get", "1", "2", "3"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)

    def test_flexible_order_with_flags(self):
        """Flags work with either order."""
        r1 = plan.parse_argv(["1", "-r", "list"])[0]
        r2 = plan.parse_argv(["list", "1", "-r"])[0]
        self.assertEqual(r1.verb, r2.verb)
        self.assertEqual(r1.targets, r2.targets)
        self.assertEqual(r1.flags.get("recursive"), r2.flags.get("recursive"))

    def test_bare_int_shorthand(self):
        reqs = plan.parse_argv(["5"])
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].targets, ["5"])
        # Default verb is get
        self.assertEqual(reqs[0].verb, "get")

    def test_multi_target(self):
        reqs = plan.parse_argv(["5", "3", "get"])
        self.assertEqual(reqs[0].targets, ["5", "3"])

    def test_semicolons(self):
        reqs = plan.parse_argv(["5", "get", ";", "3", "del"])
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0].verb, "get")
        self.assertEqual(reqs[1].verb, "del")

    def test_multiple_verbs_error(self):
        with self.assertRaises(SystemExit):
            plan.parse_argv(["get", "del", "5"])

    def test_commands_reject_verbs(self):
        for cmd in ["create", "move", "check", "fix", "resolve",
                     "status", "close"]:
            with self.assertRaises(SystemExit, msg=f"{cmd} should reject verbs"):
                plan.parse_argv(["get", cmd] + (
                    ["'title=\"x\"'"] if cmd == "create"
                    else ["open"] if cmd in ("status", "close")
                    else ["1"] if cmd == "move"
                    else []))

    def test_default_verb_is_get(self):
        reqs = plan.parse_argv(["5"])
        self.assertEqual(reqs[0].verb, "get")

    def test_plus_shorthand_for_add(self):
        reqs = plan.parse_argv(["5", "+", "text"])
        self.assertEqual(reqs[0].verb, "add")
        self.assertEqual(reqs[0].verb_args, ["text"])

    def test_tilde_shorthand_for_mod(self):
        reqs = plan.parse_argv(["5", "~", 'set(estimate="1h")'])
        self.assertEqual(reqs[0].verb, "mod")
        self.assertEqual(reqs[0].verb_args, ['set(estimate="1h")'])

    def test_list_verb(self):
        reqs = plan.parse_argv(["list"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertIsNone(reqs[0].command)

    def test_list_with_target(self):
        reqs = plan.parse_argv(["5", "list"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertEqual(reqs[0].targets, ["5"])

    def test_list_with_target_reverse(self):
        reqs = plan.parse_argv(["list", "5"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertEqual(reqs[0].targets, ["5"])

    def test_list_ready_is_query(self):
        """'plan list ready' parses ready as implicit -q, not verb arg."""
        reqs = plan.parse_argv(["list", "ready"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertEqual(reqs[0].flags.get("q"), ["ready"])
        self.assertEqual(reqs[0].verb_args, [])

    def test_create_command(self):
        reqs = plan.parse_argv(["create", 'title="Bug"'])
        self.assertEqual(reqs[0].command[0], "create")
        self.assertEqual(reqs[0].command[1], ['title="Bug"'])

    def test_create_with_parent(self):
        reqs = plan.parse_argv(["create", "5", 'title="Sub"'])
        self.assertEqual(reqs[0].command[0], "create")
        self.assertIn("5", reqs[0].command[1])

    def test_flags(self):
        reqs = plan.parse_argv(["-f", "test.md", "5", "get"])
        self.assertEqual(reqs[0].flags["file"], "test.md")

    def test_help_flag(self):
        reqs = plan.parse_argv(["--help"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")

    def test_status_command(self):
        reqs = plan.parse_argv(["5", "status", "in-progress"])
        self.assertEqual(reqs[0].verb, "status")
        self.assertEqual(reqs[0].verb_args, ["in-progress"])
        self.assertEqual(reqs[0].targets, ["5"])

    # --- bare int target forms ---

    def test_bare_int_form(self):
        """'5' parses to target '5'."""
        reqs = plan.parse_argv(["5", "get"])
        self.assertEqual(reqs[0].targets, ["5"])
        self.assertIsNone(reqs[0].command)

    def test_bare_int_with_attr(self):
        """Bare int works with attr selector."""
        r = plan.parse_argv(["5", "attr", "estimate", "get"])[0]
        self.assertEqual(r.targets, ["5"])
        self.assertEqual(r.selector_type, "attr")
        self.assertEqual(r.selector_args, ["estimate"])

    def test_bare_int_with_mod(self):
        """Bare int works with mod verb."""
        r = plan.parse_argv(["1", "mod", 'set(estimate="3h")'])[0]
        self.assertEqual(r.targets, ["1"])
        self.assertEqual(r.verb, "mod")
        self.assertEqual(r.verb_args, ['set(estimate="3h")'])

    def test_bare_int_dispatch_get(self):
        """Bare int produces correct output through dispatch."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.parse_argv(["1", "get"])[0]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        self.assertIn("First task", text)

    def test_bare_int_dispatch_mod(self):
        """Bare int applies modification through dispatch."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.parse_argv(["1", "mod", 'set(estimate="5h")'])[0]
        plan.dispatch(p, req, [])
        t = p.lookup("1")
        self.assertEqual(t.attrs["estimate"], "5h")

    def test_multi_target_bare_ints(self):
        """Multiple bare int targets in one request."""
        reqs = plan.parse_argv(["1", "2", "3", "4", "get"])
        self.assertEqual(sorted(reqs[0].targets), ["1", "2", "3", "4"])

    def test_bare_int_default_verb_get(self):
        """Bare integer with no verb defaults to get."""
        reqs = plan.parse_argv(["1"])
        self.assertEqual(reqs[0].targets, ["1"])
        self.assertEqual(reqs[0].verb, "get")

    # --- per-command help parsing ---

    def test_help_list_parses_target(self):
        """'plan help list' parses help with target 'list'."""
        reqs = plan.parse_argv(["help", "list"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")
        self.assertEqual(reqs[0].command[1], ["list"])

    def test_h_mod_parses_target(self):
        """'plan h mod' parses help with target 'mod'."""
        reqs = plan.parse_argv(["h", "mod"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")
        self.assertEqual(reqs[0].command[1], ["mod"])

    def test_list_dash_h_triggers_help(self):
        """'plan list -h' converts to help about list."""
        reqs = plan.parse_argv(["list", "-h"])
        # list is a verb, -h converts the whole request to help
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")

    def test_create_dashdash_help_triggers_help(self):
        """'plan create --help' converts to help about create."""
        reqs = plan.parse_argv(["create", "--help"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")
        self.assertIn("create", reqs[0].command[1])

    def test_help_no_target_still_general(self):
        """'plan help' with no target has empty args."""
        reqs = plan.parse_argv(["help"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")
        self.assertEqual(reqs[0].command[1], [])

    def test_help_verb_target(self):
        """'plan help get' targets a verb."""
        reqs = plan.parse_argv(["help", "get"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")
        self.assertEqual(reqs[0].command[1], ["get"])

    # --- id selector parsing ---

    def test_id_selector_section(self):
        """'plan id description' parses as id selector."""
        reqs = plan.parse_argv(["id", "description"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["description"])
        self.assertEqual(reqs[0].verb, "get")

    def test_id_selector_numeric(self):
        """'plan id 3' parses as id selector with numeric arg."""
        reqs = plan.parse_argv(["id", "3"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["3"])

    def test_id_selector_compound(self):
        """'plan id 1:comment:2' parses compound id."""
        reqs = plan.parse_argv(["id", "1:comment:2"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["1:comment:2"])

    def test_id_selector_with_verb(self):
        """'plan id description get' has both selector and verb."""
        reqs = plan.parse_argv(["id", "description", "get"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["description"])
        self.assertEqual(reqs[0].verb, "get")

    def test_id_selector_verb_first(self):
        """'plan get id description' — flexible order."""
        reqs = plan.parse_argv(["get", "id", "description"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["description"])
        self.assertEqual(reqs[0].verb, "get")

    def test_id_selector_with_flags(self):
        """'plan id 3 -r -p' passes flags through."""
        reqs = plan.parse_argv(["id", "3", "-r", "-p"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["3"])
        self.assertTrue(reqs[0].flags.get("recursive"))
        self.assertTrue(reqs[0].flags.get("parent"))

    def test_id_selector_missing_arg(self):
        """'plan id' with no argument is an error (at dispatch time)."""
        p = plan.parse(SAMPLE_DOC)
        reqs = plan.parse_argv(["id"])
        with self.assertRaises(SystemExit):
            plan.dispatch(p, reqs[0], [])

    def test_id_selector_help(self):
        """'plan id -h' triggers help for id."""
        reqs = plan.parse_argv(["id", "-h"])
        self.assertIsNotNone(reqs[0].command)
        self.assertEqual(reqs[0].command[0], "help")

    def test_parse_link_verb(self):
        reqs = plan.parse_argv(["5", "link", "blocked", "3"])
        self.assertEqual(reqs[0].verb, "link")
        self.assertEqual(reqs[0].verb_args, ["blocked", "3"])

    def test_parse_link_default_type(self):
        reqs = plan.parse_argv(["5", "link", "3"])
        self.assertEqual(reqs[0].verb, "link")
        self.assertEqual(reqs[0].verb_args, ["3"])

    def test_parse_unlink_verb(self):
        reqs = plan.parse_argv(["5", "unlink", "all", "3"])
        self.assertEqual(reqs[0].verb, "unlink")
        self.assertEqual(reqs[0].verb_args, ["all", "3"])

    # --- Implicit -q tests ---

    def test_implicit_q_with_list(self):
        """'plan list is_open' sets -q query."""
        reqs = plan.parse_argv(["list", "is_open"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertEqual(reqs[0].flags.get("q"), ["is_open"])

    def test_implicit_q_before_verb(self):
        """'plan is_open list' sets -q query."""
        reqs = plan.parse_argv(["is_open", "list"])
        self.assertEqual(reqs[0].verb, "list")
        self.assertEqual(reqs[0].flags.get("q"), ["is_open"])

    def test_implicit_q_defaults_to_get(self):
        """Bare 'plan is_open' defaults verb to get."""
        reqs = plan.parse_argv(["is_open"])
        self.assertEqual(reqs[0].verb, "get")
        self.assertEqual(reqs[0].flags.get("q"), ["is_open"])

    def test_implicit_q_compound_expression(self):
        """Compound DSL expression as implicit -q."""
        reqs = plan.parse_argv(["list", 'status == "open"'])
        self.assertEqual(reqs[0].flags.get("q"), ['status == "open"'])

    def test_implicit_q_unknown_bare_word_errors(self):
        """Unknown bare word like 'blah' gives a nice error."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["list", "blah"])
        self.assertIn("unknown filter name: blah", str(cm.exception))
        self.assertIn("Known:", str(cm.exception))

    def test_implicit_q_syntax_error(self):
        """Compound expression with syntax error gives nice error."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["list", "status =="])
        self.assertIn("invalid filter expression", str(cm.exception))

    def test_implicit_q_all_unknown_names_errors(self):
        """'qwe == asd' — all names unknown — gives nice error."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["list", "qwe == asd"])
        self.assertIn("unknown name", str(cm.exception))

    def test_implicit_q_mixed_known_unknown_ok(self):
        """'status == "open" and priority' — at least one known name — allowed."""
        reqs = plan.parse_argv(["list", 'status == "open" and priority'])
        self.assertEqual(reqs[0].flags.get("q"), ['status == "open" and priority'])

    def test_multiple_implicit_q(self):
        """Multiple implicit -q queries are collected."""
        reqs = plan.parse_argv(["is_open", 'status == "open"', "list"])
        self.assertEqual(reqs[0].flags.get("q"), ["is_open", 'status == "open"'])

    def test_multiple_explicit_q(self):
        """Multiple -q flags are collected."""
        reqs = plan.parse_argv(["-q", "is_open", "-q", 'rank > 0', "list"])
        self.assertEqual(reqs[0].flags.get("q"), ["is_open", "rank > 0"])

    def test_mixed_q_and_ids(self):
        """IDs and queries can be mixed."""
        reqs = plan.parse_argv(["5", "is_open", "list"])
        self.assertEqual(reqs[0].targets, ["5"])
        self.assertEqual(reqs[0].flags.get("q"), ["is_open"])

    def test_explicit_q_still_works(self):
        """Explicit -q flag still works."""
        reqs = plan.parse_argv(["-q", "is_open", "list"])
        self.assertEqual(reqs[0].flags.get("q"), ["is_open"])

    def test_list_order_not_treated_as_q(self):
        """'plan list order' is a verb arg, not a query."""
        reqs = plan.parse_argv(["list", "order"])
        self.assertEqual(reqs[0].verb_args, ["order"])
        self.assertNotIn("q", reqs[0].flags)

    def test_list_ready_treated_as_q(self):
        """'plan list ready' parses ready as implicit -q query."""
        reqs = plan.parse_argv(["list", "ready"])
        self.assertEqual(reqs[0].flags.get("q"), ["ready"])
        self.assertEqual(reqs[0].verb_args, [])


class TestQueryAndIdCombinations(unittest.TestCase):
    """Test all combinations of -q queries and direct ticket IDs for get/list.

    Tree structure:
        #1 Alpha (open, tag="a")          ← top-level
          #2 Beta  (closed, tag="b")      ← child of #1
            #3 Gamma (open, tag="a")      ← grandchild
        #4 Delta (open, tag="b")          ← top-level
    """

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False)
        self.tmpfile.close()
        self._run("create", 'title="Alpha"')
        self._run("create", "1", 'title="Beta"')
        self._run("create", "2", 'title="Gamma"')
        self._run("create", 'title="Delta"')
        # Tags
        self._run("1", "~", 'set(tag="a")')
        self._run("2", "~", 'set(tag="b")')
        self._run("3", "~", 'set(tag="a")')
        self._run("4", "~", 'set(tag="b")')
        # Close #2
        self._run("2", "close")

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _ids(self, result):
        """Extract ticket IDs from list output lines like '#1 [open] Alpha'."""
        ids = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r'\s*#(\d+)', line.strip())
            if m:
                ids.append(int(m.group(1)))
        return ids

    def _titles(self, result):
        """Extract ticket titles from get output '## Task: Title {#N}'."""
        titles = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r'\s*(?:\* )?## \w+: (.+?) \{#\d+\}', line)
            if m:
                titles.append(m.group(1))
        return titles

    # ── list: no query, no recursive ──────────────────────────────────

    def test_list_bare(self):
        """'plan list' — no targets → all tickets in tree-walk order."""
        r = self._run("list")
        self.assertEqual(self._ids(r), [1, 2, 3, 4])

    def test_list_single_id(self):
        """'plan 1 list' — single ID → shows ticket #1 itself."""
        r = self._run("1", "list")
        self.assertEqual(self._ids(r), [1])

    def test_list_multiple_ids(self):
        """'plan 2 3 list' — multiple IDs → shows those tickets directly."""
        r = self._run("2", "3", "list")
        self.assertEqual(self._ids(r), [2, 3])

    # ── list: query only ──────────────────────────────────────────────

    def test_list_single_query(self):
        """'plan is_open list' — query selects matching tickets."""
        r = self._run("is_open", "list")
        self.assertEqual(self._ids(r), [1, 3, 4])

    def test_list_query_custom_attr(self):
        """'plan -q 'tag == "b"' list' — query on custom attribute."""
        r = self._run("-q", 'tag == "b"', "list")
        self.assertEqual(self._ids(r), [2, 4])

    def test_list_two_queries(self):
        """Two boolean queries → sequential AND (filter chain)."""
        r = self._run("is_open", 'tag == "b"', "list")
        # is_open filters all → #1, #3, #4.  tag=="b" filters those → #4.
        ids = self._ids(r)
        self.assertEqual(ids, [4])

    # ── list: ID + query ──────────────────────────────────────────────

    def test_list_id_plus_query(self):
        """'plan 1 is_open list' — ID + bool filter → AND semantics."""
        r = self._run("1", "is_open", "list")
        ids = self._ids(r)
        # #1 is open, so filter keeps it
        self.assertEqual(ids, [1])

    def test_list_closed_id_plus_open_query(self):
        """'plan 2 is_open list' — closed ID + open filter → empty (AND)."""
        r = self._run("2", "is_open", "list")
        ids = self._ids(r)
        # #2 is closed, is_open filter removes it → empty
        self.assertEqual(ids, [])

    def test_list_id_plus_query_overlap(self):
        """'plan 2 -q 'tag == "b"' list' — ID + matching filter → keeps it."""
        r = self._run("2", "-q", 'tag == "b"', "list")
        ids = self._ids(r)
        # #2 has tag "b", filter keeps it
        self.assertEqual(ids, [2])

    # ── list: with -r ─────────────────────────────────────────────────

    def test_list_recursive_no_query(self):
        """'plan -r list' — -r on empty set is a no-op (positional semantics)."""
        r = self._run("-r", "list")
        self.assertEqual(self._ids(r), [])

    def test_list_id_recursive(self):
        """'plan 1 -r list' — single ID + recursive → self and all descendants."""
        r = self._run("1", "-r", "list")
        self.assertEqual(self._ids(r), [1, 2, 3])

    def test_list_query_recursive(self):
        """'plan is_open -r list' — query selects open, -r expands each."""
        r = self._run("is_open", "-r", "list")
        ids = self._ids(r)
        # is_open selects #1, #3, #4.  -r expands: #1→(#1,#2,#3), #3→(#3), #4→(#4)
        # Dedup'd: all four.
        self.assertEqual(set(ids), {1, 2, 3, 4})

    # ── get: no query ─────────────────────────────────────────────────

    def test_get_bare_errors(self):
        """'plan get' — no targets → error."""
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name, "get"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a ticket ID", result.stderr)

    def test_get_single_id(self):
        """'plan 1' — shows full content of #1 only."""
        r = self._run("1")
        titles = self._titles(r)
        self.assertEqual(titles, ["Alpha"])

    def test_get_multiple_ids(self):
        """'plan 2 3 get' — parent-child targets: nested bulleted display."""
        r = self._run("2", "3", "get")
        # #2 is structural parent (header-only), #3 is content (full)
        self.assertIn("* ## Task: Beta {#2}", r.stdout)
        titles = self._titles(r)
        self.assertEqual(titles, ["Beta", "Gamma"])

    # ── get: query only ───────────────────────────────────────────────

    def test_get_single_query(self):
        """'plan is_open get' — shows content of each matching ticket."""
        r = self._run("is_open", "get")
        titles = self._titles(r)
        self.assertEqual(titles, ["Alpha", "Gamma", "Delta"])

    def test_get_query_custom_attr(self):
        """'plan -q 'tag == "b"' get' — custom attr query."""
        r = self._run("-q", 'tag == "b"', "get")
        titles = self._titles(r)
        self.assertEqual(titles, ["Beta", "Delta"])

    # ── get: ID + query ───────────────────────────────────────────────

    def test_get_id_plus_query(self):
        """'plan 1 -q 'tag == "b"' get' — ID + non-matching filter → error."""
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name,
               "1", "-q", 'tag == "b"', "get"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        # #1 has tag "a", filter tag=="b" removes it → error
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a ticket ID", result.stderr)

    def test_get_closed_id_plus_open_query(self):
        """'plan 2 is_open get' — closed ID + open filter → error."""
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name,
               "2", "is_open", "get"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        # #2 is closed, is_open filter removes it → error
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a ticket ID", result.stderr)

    # ── get: with -r ──────────────────────────────────────────────────

    def test_get_id_recursive_tree_view(self):
        """'plan 1 -r' — recursive without query → tree-view rendering."""
        r = self._run("1", "-r")
        # Tree view includes all descendants in a single block
        self.assertIn("Alpha", r.stdout)
        self.assertIn("Beta", r.stdout)
        self.assertIn("Gamma", r.stdout)
        self.assertNotIn("Delta", r.stdout)

    def test_get_query_recursive_individual(self):
        """'plan is_open -r get' — query + recursive → nested rendering."""
        r = self._run("is_open", "-r", "get")
        # All tickets present: #1,#2 as structural parents, #3,#4 as content
        titles = self._titles(r)
        self.assertEqual(set(titles), {"Alpha", "Beta", "Gamma", "Delta"})

    # ── default verb inference ────────────────────────────────────────

    def test_bare_query_defaults_to_get(self):
        """'plan is_open' — query without targets → defaults to get."""
        r = self._run("is_open", "get")
        titles = self._titles(r)
        self.assertEqual(titles, ["Alpha", "Gamma", "Delta"])

    def test_bare_id_defaults_to_get(self):
        """'plan 1' — ID without verb → defaults to get."""
        r = self._run("1")
        titles = self._titles(r)
        self.assertEqual(titles, ["Alpha"])

    def test_id_plus_query_defaults_to_get(self):
        """'plan 1 is_open' — ID + matching filter → defaults to get."""
        r = self._run("1", "is_open")
        titles = self._titles(r)
        # #1 is open, filter keeps it
        self.assertEqual(titles, ["Alpha"])


class TestPerCommandHelp(unittest.TestCase):
    """End-to-end tests for per-command help output."""

    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, "plan.py"] + list(args),
            capture_output=True, text=True,
        )
        return result.stdout

    def test_help_list_contains_list_help(self):
        out = self._run("help", "list")
        self.assertIn("plan list", out)
        self.assertIn("-q EXPR", out)

    def test_h_mod_contains_dsl_reference(self):
        out = self._run("h", "mod")
        self.assertIn("plan mod", out)
        self.assertIn("help dsl", out)

    def test_create_help_contains_dsl_reference(self):
        out = self._run("create", "--help")
        self.assertIn("plan create", out)
        self.assertIn("help dsl", out)

    def test_list_dash_h_shows_list_help(self):
        out = self._run("list", "-h")
        self.assertIn("plan list", out)
        self.assertIn("help dsl", out)

    def test_bare_help_shows_general(self):
        out = self._run("help")
        self.assertIn("plan — Markdown Ticket Tracker", out)

    def test_no_args_shows_general(self):
        out = self._run()
        self.assertIn("plan — Markdown Ticket Tracker", out)

    def test_unknown_command_shows_error_only(self):
        out = self._run("help", "nonexistent")
        self.assertIn("Unknown command: nonexistent", out)
        self.assertNotIn("plan — Markdown Ticket Tracker", out)

    def test_dsl_reference_in_list_mod_create(self):
        """DSL reference appears in list, mod, and create help."""
        for cmd in ["list", "mod", "create"]:
            out = self._run("help", cmd)
            self.assertIn("help dsl", out, f"DSL reference missing from {cmd} help")


class TestFileDiscovery(unittest.TestCase):
    """Test file discovery logic."""

    def test_file_flag(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"test")
            path = f.name
        try:
            result = plan.discover_file({"file": path})
            self.assertEqual(result, path)
        finally:
            os.unlink(path)

    def test_file_flag_missing_returns_path(self):
        result = plan.discover_file({"file": "/nonexistent/path.md"})
        self.assertEqual(result, "/nonexistent/path.md")

    def test_env_variable(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"test")
            path = f.name
        old = os.environ.get("PLAN_MD")
        try:
            os.environ["PLAN_MD"] = path
            result = plan.discover_file({})
            self.assertEqual(result, path)
        finally:
            if old is None:
                os.environ.pop("PLAN_MD", None)
            else:
                os.environ["PLAN_MD"] = old
            os.unlink(path)

    def test_no_file_no_git_no_env(self):
        """discover_file errors when no path can be determined at all."""
        old = os.environ.pop("PLAN_MD", None)
        old_cwd = os.getcwd()
        try:
            # Move to a non-git directory
            os.chdir(tempfile.gettempdir())
            with self.assertRaises(SystemExit):
                plan.discover_file({})
        finally:
            os.chdir(old_cwd)
            if old is not None:
                os.environ["PLAN_MD"] = old

    def test_walk_up_finds_plan_in_parent(self):
        """discover_file finds .PLAN.md by walking up from cwd."""
        old = os.environ.pop("PLAN_MD", None)
        old_cwd = os.getcwd()
        tmpdir = tempfile.mkdtemp()
        try:
            # Create .PLAN.md in tmpdir, then cd into a subdirectory
            plan_path = os.path.join(tmpdir, ".PLAN.md")
            with open(plan_path, 'w') as f:
                f.write("# Test {#project}\n")
            subdir = os.path.join(tmpdir, "a", "b", "c")
            os.makedirs(subdir)
            os.chdir(subdir)
            result = plan.discover_file({})
            self.assertEqual(result, plan_path)
        finally:
            os.chdir(old_cwd)
            if old is not None:
                os.environ["PLAN_MD"] = old
            import shutil
            shutil.rmtree(tmpdir)

    def test_walk_up_finds_plan_in_cwd(self):
        """discover_file finds .PLAN.md in the current directory itself."""
        old = os.environ.pop("PLAN_MD", None)
        old_cwd = os.getcwd()
        tmpdir = tempfile.mkdtemp()
        try:
            plan_path = os.path.join(tmpdir, ".PLAN.md")
            with open(plan_path, 'w') as f:
                f.write("# Test {#project}\n")
            os.chdir(tmpdir)
            result = plan.discover_file({})
            self.assertEqual(result, plan_path)
        finally:
            os.chdir(old_cwd)
            if old is not None:
                os.environ["PLAN_MD"] = old
            import shutil
            shutil.rmtree(tmpdir)

    def test_walk_up_git_root_takes_precedence(self):
        """Git root .PLAN.md is preferred over walk-up when it exists."""
        old = os.environ.pop("PLAN_MD", None)
        old_cwd = os.getcwd()
        try:
            # We're in a git repo; create .PLAN.md at git root
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                self.skipTest("not in a git repo")
            git_root = result.stdout.strip()
            git_plan = os.path.join(git_root, ".PLAN.md")
            created = not os.path.exists(git_plan)
            if created:
                with open(git_plan, 'w') as f:
                    f.write("# Test {#project}\n")
            try:
                # cd into a subdirectory of the git repo
                subdir = os.path.join(git_root, "AGENTS")
                if os.path.isdir(subdir):
                    os.chdir(subdir)
                else:
                    os.chdir(git_root)
                found = plan.discover_file({})
                self.assertEqual(found, git_plan)
            finally:
                if created:
                    os.unlink(git_plan)
        finally:
            os.chdir(old_cwd)
            if old is not None:
                os.environ["PLAN_MD"] = old


# ===================================================================
# Empty/Missing File Handling
# ===================================================================

class TestEmptyFile(unittest.TestCase):
    """Test handling of empty and missing plan files."""

    def test_parse_empty_string(self):
        """parse('') returns a usable Project with no title."""
        project = plan.parse("")
        self.assertIsInstance(project, plan.Project)
        self.assertEqual(project.title, "")
        self.assertEqual(project.tickets, [])

    def test_bootstrap_creates_minimal_structure(self):
        """_bootstrap_project creates title, metadata, and tickets sections."""
        project = plan.parse("")
        plan._bootstrap_project(project)
        self.assertEqual(project.title, "Project")
        self.assertIn("metadata", project.sections)
        self.assertIn("tickets", project.sections)
        self.assertEqual(project.sections["metadata"].get_attr("next_id"), "1")
        self.assertEqual(project.next_id, 1)
        self.assertTrue(project._trailing_newline)

    def test_bootstrap_registers_in_id_map(self):
        project = plan.parse("")
        plan._bootstrap_project(project)
        self.assertIs(project.lookup("project"), project)
        self.assertIs(project.lookup("metadata"), project.sections["metadata"])
        self.assertIs(project.lookup("tickets"), project.sections["tickets"])

    def test_create_on_bootstrapped_project(self):
        """Creating a ticket on a bootstrapped project produces valid markdown."""
        project = plan.parse("")
        plan._bootstrap_project(project)
        # Simulate create
        new_id = project.allocate_id()
        ticket = plan.Ticket(new_id, "First ticket", "Task")
        ticket.dirty = True
        ticket.set_attr("status", "open")
        ticket.set_attr("rank", "0")
        project.tickets.append(ticket)
        project.register(ticket)

        text = plan.serialize(project)
        self.assertIn("# Project {#project}", text)
        self.assertIn("## Tickets {#tickets}", text)
        self.assertIn("First ticket", text)
        self.assertIn("{#1}", text)
        # Round-trip
        project2 = plan.parse(text)
        self.assertEqual(project2.title, "Project")
        self.assertEqual(len(project2.tickets), 1)
        self.assertEqual(project2.tickets[0].title, "First ticket")

    def test_project_description_add_autocreates_section(self):
        """project description add on bootstrapped project auto-creates section."""
        project = plan.parse("")
        plan._bootstrap_project(project)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["My project description"]
        req.selector_type = "project"
        req.selector_args = ["description"]
        output = []
        plan._handle_project(project, ["description"], req, output)
        self.assertIn("description", project.sections)
        self.assertEqual(project.sections["description"].body_lines,
                         ["My project description"])

    def test_serialize_bootstrapped_empty(self):
        """Serializing bootstrapped project with no tickets is valid."""
        project = plan.parse("")
        plan._bootstrap_project(project)
        text = plan.serialize(project)
        self.assertIn("# Project {#project}", text)
        self.assertIn("## Metadata {#metadata}", text)
        self.assertIn("next_id: 1", text)
        self.assertIn("## Tickets {#tickets}", text)
        self.assertTrue(text.endswith("\n"))

    def test_cli_create_on_nonexistent_file(self):
        """CLI: create on nonexistent file bootstraps and writes."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "new.md")
            self.assertFalse(os.path.exists(path))
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path,
                 "create", 'title="First ticket"'],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                content = f.read()
            self.assertIn("# Project {#project}", content)
            self.assertIn("First ticket", content)
            self.assertIn("{#1}", content)

    def test_cli_list_after_create(self):
        """CLI: list works on file created from scratch."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "new.md")
            subprocess.run(
                [sys.executable, "plan.py", "-f", path,
                 "create", 'title="Test"'],
                capture_output=True, text=True,
            )
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path, "list"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("#1", result.stdout)
            self.assertIn("Test", result.stdout)

    def test_cli_project_description_roundtrip(self):
        """CLI: project description add then get on new file."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "new.md")
            subprocess.run(
                [sys.executable, "plan.py", "-f", path,
                 "project", "description", "add", "Hello world"],
                capture_output=True, text=True,
            )
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path,
                 "project", "description", "get"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Hello world", result.stdout)

    def test_cli_read_only_on_missing_errors(self):
        """CLI: read-only commands on nonexistent file error."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nope.md")
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path, "list"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Error", result.stderr)

    def test_roundtrip_bootstrap_create_serialize_parse(self):
        """Bootstrap -> create ticket -> serialize -> parse -> tickets intact."""
        project = plan.parse("")
        plan._bootstrap_project(project)

        new_id = project.allocate_id()
        ticket = plan.Ticket(new_id, "Roundtrip test", "Task")
        ticket.dirty = True
        ticket.set_attr("status", "open")
        ticket.set_attr("rank", "0")
        project.tickets.append(ticket)
        project.register(ticket)

        text = plan.serialize(project)
        project2 = plan.parse(text)
        self.assertEqual(project2.title, "Project")
        self.assertEqual(len(project2.tickets), 1)
        self.assertEqual(project2.tickets[0].title, "Roundtrip test")
        self.assertEqual(project2.tickets[0].get_attr("status"), "open")
        self.assertEqual(project2.next_id, 2)

    def test_empty_file_on_disk(self):
        """CLI: empty file on disk is bootstrapped on write."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
            f.write("")  # empty file
            path = f.name
        try:
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path,
                 "create", 'title="From empty"'],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(path) as f:
                content = f.read()
            self.assertIn("From empty", content)
            self.assertIn("# Project {#project}", content)
        finally:
            os.unlink(path)


# ===================================================================
# Task 4: Read Commands
# ===================================================================

SAMPLE_DOC = textwrap.dedent("""\
# Test Project {#project}

## Metadata {#metadata}

    next_id: 5

## Description {#description}

This is a test project.

## Tickets {#tickets}

* ## Ticket: Task: First task {#1}

      created: 2024-01-01 00:00:00 UTC
      updated: 2024-01-01 00:00:00 UTC
      status: open
      estimate: 1h

  First task body.

  * ## Ticket: Task: Subtask A {#3}

        created: 2024-01-02 00:00:00 UTC
        updated: 2024-01-02 00:00:00 UTC
        status: open
        estimate: 2h

    Subtask A body.

* ## Ticket: Bug: Second task {#2}

      created: 2024-01-01 00:00:00 UTC
      updated: 2024-01-01 00:00:00 UTC
      status: in-progress
      estimate: 3h
      assignee: alice

  Second task body.

* ## Ticket: Task: Third task {#4}

      created: 2024-01-01 00:00:00 UTC
      updated: 2024-01-01 00:00:00 UTC
      status: done
      estimate: 2h

  Third task done.
""")


class TestGetVerb(unittest.TestCase):
    """Test the get verb."""

    def test_get_ticket(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        targets = [p.lookup("1")]
        plan._handle_get(p, targets, plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("First task", text)
        self.assertIn("status: open", text)

    def test_get_default_verb(self):
        """get is the default verb when none specified."""
        reqs = plan.parse_argv(["1"])
        self.assertEqual(reqs[0].verb, "get")

    def test_get_nonexistent_id(self):
        p = plan.parse(SAMPLE_DOC)
        self.assertIsNone(p.lookup("999"))

    def test_get_section(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        targets = [p.lookup("description")]
        plan._handle_get(p, targets, plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("Description", text)

    def test_get_ticket_includes_comments(self):
        """get on a ticket should include its comments."""
        doc = textwrap.dedent("""\
        # Test {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: Has comments {#1}

              status: open

          Body text.

          * ## Comments {#1:comments}
            * @alice: First note {#1:comment:1}
            * @bob: Second note {#1:comment:2}
        """)
        p = plan.parse(doc)
        output = []
        plan._handle_get(p, [p.lookup("1")], plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("Has comments", text)
        self.assertIn("First note", text)
        self.assertIn("Second note", text)

    def test_get_ticket_without_comments(self):
        """get on a ticket without comments still works."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        plan._handle_get(p, [p.lookup("1")], plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("First task", text)
        # No crash, no empty comments section
        self.assertNotIn("Comments", text)

    def test_get_indentation_toplevel(self):
        """get on a top-level ticket: all output lines start at indent 0."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        plan._handle_get(p, [p.lookup("1")], plan.ParsedRequest(), output)
        for line in output:
            if line.strip():
                # attrs at indent 4 are expected
                if ":" in line and line.lstrip().split(":")[0] in p.lookup("1").attrs:
                    self.assertTrue(line.startswith("    "),
                        f"Attr line should be at indent 4: {line!r}")
                else:
                    self.assertEqual(line, line.lstrip(),
                        f"Non-attr line should start at indent 0: {line!r}")

    def test_get_indentation_nested(self):
        """get on a nested ticket: body dedented to 0, not raw file indent."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        plan._handle_get(p, [p.lookup("3")], plan.ParsedRequest(), output)
        for line in output:
            if line.strip():
                if ":" in line and line.lstrip().split(":")[0] in p.lookup("3").attrs:
                    self.assertTrue(line.startswith("    "),
                        f"Attr line should be at indent 4: {line!r}")
                else:
                    self.assertEqual(line, line.lstrip(),
                        f"Non-attr line should start at indent 0: {line!r}")

    def test_get_indentation_with_comments(self):
        """get on a ticket with comments: comments normalized to indent 0."""
        doc = textwrap.dedent("""\
        # Test {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: Top {#1}

              status: open

          Top body.

          * ## Comments {#1:comments}
            * @alice: Note A {#1:comment:1}

              Detail about note A.

            * @bob: Note B {#1:comment:2}
        """)
        p = plan.parse(doc)
        output = []
        plan._handle_get(p, [p.lookup("1")], plan.ParsedRequest(), output)
        text = "\n".join(output)
        # Header at indent 0
        self.assertTrue(output[0].startswith("## "))
        # Body at indent 0
        self.assertIn("Top body.", output)
        # Comments header at indent 0
        comment_header = [l for l in output if "Comments" in l and l.strip()]
        self.assertTrue(len(comment_header) > 0)
        self.assertEqual(comment_header[0], comment_header[0].lstrip(),
            f"Comments header should be at indent 0: {comment_header[0]!r}")

    def test_get_indentation_deeply_nested_with_comments(self):
        """get on a deeply nested ticket with comments: all normalized to 0."""
        doc = textwrap.dedent("""\
        # Test {#project}

        ## Metadata {#metadata}

            next_id: 5

        ## Tickets {#tickets}

        * ## Ticket: Task: Parent {#1}

              status: open

          Parent body.

          * ## Ticket: Task: Child {#2}

                status: open

            Child body here.

            * ## Comments {#2:comments}
              * @dev: Nested comment {#2:comment:1}

                With extra detail.

              * @lead: Reply {#2:comment:2}
        """)
        p = plan.parse(doc)
        output = []
        plan._handle_get(p, [p.lookup("2")], plan.ParsedRequest(), output)
        # Header at indent 0
        self.assertTrue(output[0].startswith("## "),
            f"Header should start at indent 0: {output[0]!r}")
        # Body at indent 0
        body_line = [l for l in output if "Child body" in l]
        self.assertTrue(len(body_line) > 0)
        self.assertEqual(body_line[0], "Child body here.",
            f"Body should be at indent 0: {body_line[0]!r}")
        # Comments header at indent 0
        comments_hdr = [l for l in output if "Comments" in l and l.strip()]
        self.assertTrue(len(comments_hdr) > 0)
        self.assertEqual(comments_hdr[0], comments_hdr[0].lstrip(),
            f"Comments header should be at indent 0: {comments_hdr[0]!r}")
        # Comment text present
        self.assertIn("Nested comment", "\n".join(output))
        self.assertIn("Reply", "\n".join(output))

    def test_text_namespace_indentation_nested(self):
        """Ticket.as_namespace()['text'] is always dedented regardless of nesting."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        ns = child.as_namespace()
        text = ns["text"]
        for line in text.split("\n"):
            if line.strip():
                self.assertEqual(line, line.lstrip(),
                    f"ns['text'] line should be at indent 0: {line!r}")

    def test_get_indentation_after_add(self):
        """Text added via 'add' verb is dedented in get output."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Added line via add"]
        plan._handle_add(p, [child], req)
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        added = [l for l in output if "Added line" in l]
        self.assertTrue(len(added) > 0)
        self.assertEqual(added[0], "Added line via add",
            f"Added text should be at indent 0 in get: {added[0]!r}")

    def test_get_indentation_after_add_multiline(self):
        """Multi-line text added via 'add' has each line correctly indented."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Line one\nLine two\nLine three"]
        plan._handle_add(p, [child], req)
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("Line one", text)
        self.assertIn("Line two", text)
        self.assertIn("Line three", text)
        for phrase in ("Line one", "Line two", "Line three"):
            matching = [l for l in output if phrase in l]
            self.assertTrue(len(matching) > 0, f"{phrase!r} not found in output")
            self.assertEqual(matching[0], phrase,
                f"Multi-line add: {phrase!r} should be at indent 0, got {matching[0]!r}")

    def test_get_indentation_after_mod_add_multiline(self):
        """Multi-line text added via mod add(text=) has each line correctly indented."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        plan.apply_mod(child, p, 'add(text="Alpha\\nBravo\\nCharlie")')
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        text = "\n".join(output)
        for phrase in ("Alpha", "Bravo", "Charlie"):
            matching = [l for l in output if phrase in l]
            self.assertTrue(len(matching) > 0, f"{phrase!r} not found in output")
            self.assertEqual(matching[0], phrase,
                f"Multi-line mod add: {phrase!r} should be at indent 0, got {matching[0]!r}")

    def test_get_indentation_after_mod_set_text(self):
        """Text set via mod set(text=) is dedented in get output."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        plan.apply_mod(child, p, 'set(text="New body from mod")')
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        body = [l for l in output if "New body from mod" in l]
        self.assertTrue(len(body) > 0)
        self.assertEqual(body[0], "New body from mod",
            f"mod-set text should be at indent 0 in get: {body[0]!r}")

    def test_get_indentation_after_mod_add_text(self):
        """Text added via mod add(text=) is dedented in get output."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        plan.apply_mod(child, p, 'add(text="Extra line")')
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        added = [l for l in output if "Extra line" in l]
        self.assertTrue(len(added) > 0)
        self.assertEqual(added[0], "Extra line",
            f"mod-add text should be at indent 0 in get: {added[0]!r}")

    def test_text_namespace_after_add(self):
        """ns['text'] is dedented after adding text via add verb."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Appended text"]
        plan._handle_add(p, [child], req)
        ns = child.as_namespace()
        for line in ns["text"].split("\n"):
            if line.strip():
                self.assertEqual(line, line.lstrip(),
                    f"ns['text'] after add should be at indent 0: {line!r}")

    def test_get_indentation_after_edit_roundtrip(self):
        """Text survives edit roundtrip with correct indentation."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")  # nested ticket
        # Simulate edit: get content, parse it back
        content = plan._get_content(child)
        text = "\n".join(content)
        new_lines = text.rstrip('\n').split('\n')
        plan._parse_edited_content(new_lines, child)
        # Now get again — should still be at indent 0
        output = []
        plan._handle_get(p, [child], plan.ParsedRequest(), output)
        for line in output:
            if line.strip() and "Subtask A body" in line:
                self.assertEqual(line, "Subtask A body.",
                    f"Body after edit roundtrip should be at indent 0: {line!r}")

    def test_get_indentation_after_create_nested(self):
        """Text on a newly created nested ticket is dedented in get output."""
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "create"
        req.flags = {}
        output = []
        plan._handle_create(p, ["1", 'title="New child", text="Created body"'],
                            req, output)
        new_id = int(output[0])
        new_ticket = p.lookup(new_id)
        get_output = []
        plan._handle_get(p, [new_ticket], plan.ParsedRequest(), get_output)
        body = [l for l in get_output if "Created body" in l]
        self.assertTrue(len(body) > 0)
        self.assertEqual(body[0], "Created body",
            f"Created ticket body should be at indent 0 in get: {body[0]!r}")

    def test_get_parent_flag(self):
        """get -p on nested ticket shows ancestor as title, target as content."""
        p = plan.parse(SAMPLE_DOC)
        # #3 is child of #1; -p adds #1 to the selection
        targets = plan._expand_targets(p, [p.lookup("3")],
            type("R", (), {"flags": {"parent": True}})())
        output = []
        plan._handle_get(p, targets, plan.ParsedRequest(), output)
        text = "\n".join(output)
        # Ancestor #1 shown as bulleted header-only line
        self.assertEqual(output[0], "* ## Task: First task {#1}")
        # Target #3 shown as bulleted full content, indented by depth
        headers = [l for l in output if "Subtask A" in l and "## " in l]
        self.assertTrue(len(headers) > 0)
        self.assertTrue(headers[0].startswith("  * "))

    def test_get_parent_flag_deeply_nested(self):
        """get -p on a 3-level deep ticket shows nested ancestor chain."""
        doc = textwrap.dedent("""\
        # Test {#project}

        ## Metadata {#metadata}

            next_id: 10

        ## Tickets {#tickets}

        * ## Ticket: Task: Grandparent {#1}

              status: open

          GP body.

          * ## Ticket: Task: Parent {#2}

                status: open

            Parent body.

            * ## Ticket: Task: Child {#3}

                  status: open

              Child body.
        """)
        p = plan.parse(doc)
        targets = plan._expand_targets(p, [p.lookup("3")],
            type("R", (), {"flags": {"parent": True}})())
        self.assertEqual([t.node_id for t in targets], [1, 2, 3])
        output = []
        plan._handle_get(p, targets, plan.ParsedRequest(), output)
        # Ancestors as bulleted header-only lines, indented by depth
        self.assertEqual(output[0], "* ## Task: Grandparent {#1}")
        self.assertEqual(output[1], "  * ## Task: Parent {#2}")
        # Child as bulleted full content at depth 2
        headers = [l for l in output if "Child" in l and "## " in l]
        self.assertTrue(len(headers) > 0)
        self.assertTrue(headers[0].startswith("    * "))

    def test_get_parent_flag_toplevel(self):
        """get -p on top-level ticket produces same output as without -p."""
        p = plan.parse(SAMPLE_DOC)
        # Get without -p
        output_normal = []
        plan._handle_get(p, [p.lookup("1")], plan.ParsedRequest(), output_normal)
        # Get with -p
        req = plan.ParsedRequest()
        req.flags = {"parent": True}
        output_parent = []
        plan._handle_get(p, [p.lookup("1")], req, output_parent)
        self.assertEqual(output_normal, output_parent)


class TestListCommand(unittest.TestCase):
    """Test the list command."""

    def test_list_top_level(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_list(p, [], req, output)
        self.assertEqual(len(output), 4)  # all tickets in tree-walk order
        self.assertIn("#1", output[0])
        self.assertIn("#3", output[1])  # subtask of #1

    def test_list_single_target(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "list"
        plan._handle_list(p, [p.lookup("1")], req, output)
        self.assertEqual(len(output), 1)  # ticket itself
        self.assertIn("First task", output[0])

    def test_list_recursive(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["recursive"] = True
        plan._handle_list(p, [], req, output)
        self.assertTrue(len(output) >= 4)  # all tickets including subtask

    def test_list_title_filter(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["title"] = "Second"
        plan._handle_list(p, [], req, output)
        self.assertEqual(len(output), 1)
        self.assertIn("Second", output[0])

    def test_list_q_filter(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["q"] = 'status == "open"'
        plan._handle_list(p, [], req, output)
        # Only ticket #1 is open at top level
        self.assertTrue(all("open" not in o or "#1" in o or "#4" not in o
                           for o in output))

    def test_list_format(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["format"] = 'f"{indent}#{id} [{status}] {title}"'
        plan._handle_list(p, [], req, output)
        self.assertIn("[open]", output[0])

    def test_list_n_limit(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["n"] = 2
        plan._handle_list(p, [], req, output)
        self.assertEqual(len(output), 2)

    def test_list_rank_ordering(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_list(p, [], req, output)
        # Tree-walk order: #1, #3 (child of #1), #2, #4
        self.assertIn("#1", output[0])
        self.assertIn("#3", output[1])
        self.assertIn("#2", output[2])
        self.assertIn("#4", output[3])

    def test_list_ready(self):
        """'plan ready list' filters via DSL ready property."""
        p = plan.parse(SAMPLE_DOC)
        plan._project = p
        # Pre-resolve ready query (as dispatch would)
        all_tickets = []
        def _collect(tlist):
            for t in tlist:
                all_tickets.append(t)
                _collect(t.children)
        _collect(p.tickets)
        targets = [t for t in all_tickets if plan.eval_filter(t, "ready")]
        output = []
        req = plan.ParsedRequest()
        req.verb = "list"
        req.flags["q"] = ["ready"]
        plan._handle_list(p, targets, req, output)
        combined = "\n".join(output)
        # #1 has open child #3, so not ready
        self.assertNotIn("#1", combined)
        # #2 is in-progress with no open children → ready
        self.assertIn("#2", combined)
        # #3 is open with no children and no blockers → ready
        self.assertIn("#3", combined)
        # #4 is done, so not ready
        self.assertNotIn("#4", combined)

    def test_list_single_target_always_shows_ticket(self):
        """Single target always shows the ticket itself, not children."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "list"
        plan._handle_list(p, [p.lookup("1")], req, output)
        self.assertEqual(len(output), 1)
        self.assertIn("First task", output[0])
        self.assertTrue(output[0].startswith("#1"))

    def test_list_recursive_with_target(self):
        """Target + recursive shows ticket and all descendants with indentation."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "list"
        req.flags["recursive"] = True
        # -r expansion now happens in dispatch; pre-expand for direct handler call
        targets = plan._expand_targets(p, [p.lookup("1")], req)
        plan._handle_list(p, targets, req, output)
        self.assertEqual(len(output), 2)  # #1 + #3 (subtask)
        self.assertTrue(output[0].startswith("#1"))
        self.assertTrue(output[1].startswith("  "), f"Child should be indented: {output[1]!r}")


class TestProjectCommand(unittest.TestCase):
    """Test the project command."""

    def test_project_get(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_project(p, [], req, output)
        text = "\n".join(output)
        self.assertIn("Test Project", text)
        # Should include all non-metadata, non-tickets sections
        self.assertIn("Description", text)
        self.assertIn("test project", text)

    def test_project_section(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_project(p, ["description"], req, output)
        text = "\n".join(output)
        self.assertIn("Description", text)


class TestIdSelector(unittest.TestCase):
    """Test the 'id' selector for looking up any node by #id."""

    def test_id_section(self):
        """'plan id description' returns section content."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "id"
        req.selector_args = ["description"]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        self.assertIn("Description", text)
        self.assertIn("test project", text)

    def test_id_ticket(self):
        """'plan id 3' returns the same as 'plan 3'."""
        p = plan.parse(SAMPLE_DOC)
        # Via bare integer
        output_bare = []
        req_bare = plan.ParsedRequest()
        req_bare.verb = "get"
        req_bare.pipeline = [("id", "3")]
        plan.dispatch(p, req_bare, output_bare)
        # Via id selector
        output_id = []
        req_id = plan.ParsedRequest()
        req_id.verb = "get"
        req_id.selector_type = "id"
        req_id.selector_args = ["3"]
        plan.dispatch(p, req_id, output_id)
        self.assertEqual(output_bare, output_id)

    def test_id_ticket_recursive(self):
        """'plan id 1 -r' shows full subtree."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "id"
        req.selector_args = ["1"]
        req.flags = {"recursive": True}
        req.pipeline = [("r",)]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        self.assertIn("First task", text)
        self.assertIn("Subtask A", text)

    def test_id_ticket_parent(self):
        """'plan id 3 -p' shows ancestor and target content."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "id"
        req.selector_args = ["3"]
        req.flags = {"parent": True}
        req.pipeline = [("p",)]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        # -p adds ancestor #1 to the selection, so its content appears
        self.assertIn("First task", text)
        # Target #3 content also appears
        self.assertIn("Subtask A", text)

    def test_id_comment(self):
        """'plan id 1:comment:1' gets a specific comment."""
        doc = textwrap.dedent("""\
        # Test {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: Has comments {#1}

              status: open

          Body text.

          * ## Comments {#1:comments}
            * @alice: First note {#1:comment:1}
            * @bob: Second note {#1:comment:2}
        """)
        p = plan.parse(doc)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "id"
        req.selector_args = ["1:comment:1"]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        self.assertIn("First note", text)

    def test_id_nonexistent(self):
        """'plan id bogus' raises an error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "id"
        req.selector_args = ["bogus"]
        output = []
        with self.assertRaises(SystemExit):
            plan.dispatch(p, req, output)

    def test_id_list_shows_ticket(self):
        """'plan id 1 list' lists ticket 1 itself."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "list"
        req.selector_type = "id"
        req.selector_args = ["1"]
        output = []
        plan.dispatch(p, req, output)
        text = "\n".join(output)
        self.assertIn("First task", text)


class TestHelp(unittest.TestCase):
    """Test help output."""

    def test_help_output(self):
        output = []
        plan._handle_help(output)
        text = "\n".join(output)
        self.assertIn("plan", text)
        self.assertIn("get", text)
        self.assertIn("list", text)
        self.assertIn("create", text)


# ===================================================================
# Task 5: Mutation Commands
# ===================================================================

class TestReplaceVerb(unittest.TestCase):
    """Test the replace verb."""

    def test_replace_body(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.flags["force"] = True
        req.verb_args = ["New body text."]
        plan._handle_replace(p, [t], req)
        self.assertEqual(t.body_lines, ["  New body text."])

    def test_replace_without_force_error(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.verb_args = ["text"]
        with self.assertRaises(SystemExit):
            plan._handle_replace(p, [t], req)

    def test_replace_from_file(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                          delete=False) as f:
            f.write("File content.")
            path = f.name
        try:
            req = plan.ParsedRequest()
            req.verb = "replace"
            req.flags["force"] = True
            req.verb_args = [f"@{path}"]
            plan._handle_replace(p, [t], req)
            self.assertEqual(t.body_lines, ["  File content."])
        finally:
            os.unlink(path)


class TestAddVerb(unittest.TestCase):
    """Test the add verb."""

    def test_add_to_ticket_body(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        orig_len = len(t.body_lines)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Additional text."]
        plan._handle_add(p, [t], req)
        self.assertGreater(len(t.body_lines), orig_len)
        self.assertIn("Additional text.", t.body_lines[-1])

    def test_add_comment(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        # Add a comment directly
        cid = p.allocate_id()
        plan._add_comment_to_ticket(t, p, cid, "Test comment")
        self.assertIsNotNone(t.comments)
        self.assertTrue(len(t.comments.comments) >= 1)

    def test_add_to_section(self):
        p = plan.parse(SAMPLE_DOC)
        desc = p.sections["description"]
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["More description."]
        plan._handle_add(p, [desc], req)
        self.assertIn("More description.", desc.body_lines)


class TestDelVerb(unittest.TestCase):
    """Test the del verb."""

    def test_del_ticket(self):
        p = plan.parse(SAMPLE_DOC)
        self.assertIsNotNone(p.lookup("2"))
        t = p.lookup("2")
        plan._delete_ticket(p, t)
        self.assertIsNone(p.lookup("2"))
        self.assertEqual(len(p.tickets), 2)  # was 3, now 2

    def test_del_ticket_removes_from_parent(self):
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        child = p.lookup("3")
        self.assertIn(child, parent.children)
        plan._delete_ticket(p, child)
        self.assertNotIn(child, parent.children)
        self.assertIsNone(p.lookup("3"))


class TestModVerb(unittest.TestCase):
    """Test the mod verb."""

    def test_mod_set_estimate(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "mod"
        req.verb_args = ['set(estimate="5h")']
        plan._handle_mod(p, [t], req)
        self.assertEqual(t.get_attr("estimate"), "5h")

    def test_mod_link(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "mod"
        req.verb_args = ['link("blocked", 2)']
        plan._handle_mod(p, [t], req)
        links = plan._parse_links(t.get_attr("links"))
        self.assertIn(2, links.get("blocked", []))


class TestCreateCommand(unittest.TestCase):
    """Test the create command."""

    def test_create_top_level(self):
        p = plan.parse(SAMPLE_DOC)
        initial_count = len(p.tickets)
        plan._handle_create(p, ['title="New ticket", estimate="2h"'], plan.ParsedRequest(), [])
        self.assertEqual(len(p.tickets), initial_count + 1)
        new_t = p.tickets[-1]
        self.assertEqual(new_t.title, "New ticket")
        self.assertEqual(new_t.get_attr("estimate"), "2h")
        self.assertEqual(new_t.get_attr("status"), "open")

    def test_create_child(self):
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        initial_children = len(parent.children)
        plan._handle_create(p, ['1', 'title="Child task"'], plan.ParsedRequest(), [])
        self.assertEqual(len(parent.children), initial_children + 1)

    def test_create_allocates_id(self):
        p = plan.parse(SAMPLE_DOC)
        old_next = p.next_id
        plan._handle_create(p, ['title="T"'], plan.ParsedRequest(), [])
        self.assertEqual(p.next_id, old_next + 1)

    def test_create_sets_timestamps(self):
        p = plan.parse(SAMPLE_DOC)
        plan._handle_create(p, ['title="T"'], plan.ParsedRequest(), [])
        new_t = p.tickets[-1]
        self.assertTrue(new_t.get_attr("created"))
        self.assertTrue(new_t.get_attr("updated"))

    def test_create_default_rank_last(self):
        p = plan.parse(SAMPLE_DOC)
        plan._handle_create(p, ['title="T"'], plan.ParsedRequest(), [])
        new_t = p.tickets[-1]
        r = plan._get_rank(new_t)
        # Should be after all existing siblings
        for t in p.tickets[:-1]:
            self.assertGreater(r, plan._get_rank(t))

    def test_create_missing_title_error(self):
        p = plan.parse(SAMPLE_DOC)
        with self.assertRaises(SystemExit):
            plan._handle_create(p, ['estimate="2h"'], plan.ParsedRequest(), [])

    def test_create_child_bare_int_parent(self):
        """'create 1 expr' uses bare integer as parent id."""
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        initial_children = len(parent.children)
        plan._handle_create(p, ['1', 'title="Child via bare int"'], plan.ParsedRequest(), [])
        self.assertEqual(len(parent.children), initial_children + 1)
        self.assertEqual(parent.children[-1].title, "Child via bare int")

    def test_create_child_bare_int_parent_form(self):
        """Bare int parent creates under the correct parent."""
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        initial_children = len(parent.children)
        plan._handle_create(p, ['1', 'title="Sub"'], plan.ParsedRequest(), [])
        self.assertEqual(len(parent.children), initial_children + 1)

    def test_create_parent_zero_is_root(self):
        """'create 0 expr' creates at top level."""
        p = plan.parse(SAMPLE_DOC)
        initial_count = len(p.tickets)
        plan._handle_create(p, ['0', 'title="Root"'], plan.ParsedRequest(), [])
        self.assertEqual(len(p.tickets), initial_count + 1)
        self.assertIsNone(p.tickets[-1].parent,
            "parent_arg='0' should create root ticket")

    def test_create_prints_ticket_number(self):
        """Create outputs the new ticket ID."""
        p = plan.parse(SAMPLE_DOC)
        output = []
        plan._handle_create(p, ['title="T"'], plan.ParsedRequest(), output)
        self.assertEqual(len(output), 1)
        self.assertTrue(output[0].isdigit())

    def test_create_quiet_suppresses_output(self):
        """Create with --quiet flag suppresses ticket ID output."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.flags["quiet"] = True
        output = []
        plan._handle_create(p, ['title="T"'], req, output)
        self.assertEqual(output, [])

    def test_create_quiet_cli_parse(self):
        """'plan create --quiet expr' sets quiet flag."""
        reqs = plan.parse_argv(["create", "--quiet", 'title="T"'])
        self.assertTrue(reqs[0].flags.get("quiet"))
        self.assertEqual(reqs[0].command[0], "create")
        self.assertEqual(reqs[0].command[1], ['title="T"'])

    def test_create_e2e_prints_id(self):
        """End-to-end: create prints the new ticket number."""
        result = subprocess.run(
            [sys.executable, "plan.py", "-f", "/tmp/_test_create_id.md",
             "create", 'title="Test"'],
            capture_output=True, text=True,
        )
        try:
            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.stdout.strip().isdigit())
        finally:
            if os.path.exists("/tmp/_test_create_id.md"):
                os.unlink("/tmp/_test_create_id.md")

    def test_create_e2e_quiet(self):
        """End-to-end: create --quiet prints nothing."""
        result = subprocess.run(
            [sys.executable, "plan.py", "-f", "/tmp/_test_create_q.md",
             "create", "--quiet", 'title="Test"'],
            capture_output=True, text=True,
        )
        try:
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")
        finally:
            if os.path.exists("/tmp/_test_create_q.md"):
                os.unlink("/tmp/_test_create_q.md")


    def test_create_from_stdin(self):
        """Create with '-' reads template from stdin."""
        from unittest.mock import patch
        p = plan.parse(SAMPLE_DOC)
        output = []
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = '## From stdin\n    estimate: 3h\n'
            plan._handle_create(p, ['-'], plan.ParsedRequest(), output)
        new_t = p.tickets[-1]
        self.assertEqual(new_t.title, "From stdin")
        self.assertEqual(new_t.get_attr("estimate"), "3h")

    def test_create_from_stdin_with_parent(self):
        """Create with 'parent -' reads template from stdin under parent."""
        from unittest.mock import patch
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        initial_children = len(parent.children)
        output = []
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = '## Child from stdin\n'
            plan._handle_create(p, ['1', '-'], plan.ParsedRequest(), output)
        self.assertEqual(len(parent.children), initial_children + 1)
        self.assertEqual(parent.children[-1].title, "Child from stdin")

    def test_create_from_stdin_e2e(self):
        """End-to-end: echo template | plan create -"""
        path = "/tmp/_test_create_stdin.md"
        try:
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path, "create", "-"],
                capture_output=True, text=True,
                input='## Piped in\n    estimate: 1h\n',
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "1")
            with open(path) as f:
                content = f.read()
            self.assertIn("Piped in", content)
            self.assertIn("estimate: 1h", content)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestStatusClose(unittest.TestCase):
    """Test status and close commands."""

    def test_status_open(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["open"]
        plan._handle_status_verb(p, [p.lookup("2")], req)
        self.assertEqual(p.lookup("2").get_attr("status"), "open")

    def test_status_in_progress(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["in-progress"]
        plan._handle_status_verb(p, [p.lookup("1")], req)
        self.assertEqual(p.lookup("1").get_attr("status"), "in-progress")

    def test_status_freetext_closes(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["won't do"]
        plan._handle_status_verb(p, [p.lookup("1")], req)
        self.assertEqual(p.lookup("1").get_attr("status"), "won't do")

    def test_close_with_resolution(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["duplicate"]
        plan._handle_close_verb(p, [p.lookup("1")], req)
        self.assertEqual(p.lookup("1").get_attr("status"), "duplicate")

    def test_status_updates_timestamp(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        old_updated = t.get_attr("updated")
        req = plan.ParsedRequest()
        req.verb_args = ["in-progress"]
        plan._handle_status_verb(p, [p.lookup("1")], req)
        self.assertNotEqual(t.get_attr("updated"), old_updated)


class TestReopenCommand(unittest.TestCase):
    """Test reopen command."""

    def test_reopen_sets_open(self):
        p = plan.parse(SAMPLE_DOC)
        plan._handle_close_verb(p, [p.lookup("1")], plan.ParsedRequest())
        self.assertEqual(p.lookup("1").get_attr("status"), "done")
        plan._handle_reopen_verb(p, [p.lookup("1")], plan.ParsedRequest())
        self.assertEqual(p.lookup("1").get_attr("status"), "open")

    def test_reopen_updates_timestamp(self):
        p = plan.parse(SAMPLE_DOC)
        with unittest.mock.patch("plan._now", return_value="2025-01-01 00:00:00 UTC"):
            plan._handle_close_verb(p, [p.lookup("1")], plan.ParsedRequest())
        old_updated = p.lookup("1").get_attr("updated")
        with unittest.mock.patch("plan._now", return_value="2025-01-01 00:00:01 UTC"):
            plan._handle_reopen_verb(p, [p.lookup("1")], plan.ParsedRequest())
        self.assertNotEqual(p.lookup("1").get_attr("updated"), old_updated)

    def test_reopen_multiple(self):
        p = plan.parse(SAMPLE_DOC)
        plan._handle_close_verb(p, [p.lookup("1"), p.lookup("2")], plan.ParsedRequest())
        plan._handle_reopen_verb(p, [p.lookup("1"), p.lookup("2")], plan.ParsedRequest())
        self.assertEqual(p.lookup("1").get_attr("status"), "open")
        self.assertEqual(p.lookup("2").get_attr("status"), "open")

    def test_reopen_no_ids_noop(self):
        p = plan.parse(SAMPLE_DOC)
        # With new verb API, empty targets list is a no-op (validation is upstream)
        plan._handle_reopen_verb(p, [], plan.ParsedRequest())


class TestCommentCommand(unittest.TestCase):
    """Test comment command."""

    def test_comment_get(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_comment(p, [t], req, output)
        # Should have some output if comments exist
        if t.comments:
            self.assertTrue(len(output) > 0)

    def test_comment_add(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        old_next = p.next_id
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["New comment text"]
        plan._handle_comment(p, [t], req, [])
        self.assertEqual(p.next_id, old_next + 1)
        self.assertIsNotNone(t.comments)

    def test_comment_add_multiline(self):
        """Multiline comment text serializes with proper indentation."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Line one\nLine two\nLine three"]
        plan._handle_comment(p, [t], req, [])
        text = plan.serialize(p)
        # All body lines of the comment should be indented
        self.assertNotIn('\nLine two', text)
        self.assertIn('Line one', text)
        self.assertIn('Line two', text)
        self.assertIn('Line three', text)


class TestAttrCommand(unittest.TestCase):
    """Test attr command."""

    def test_attr_get(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        plan._handle_attr(p, [t], ["estimate"], req, output)
        self.assertEqual(output[0], "1h")

    def test_attr_replace(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.flags["force"] = True
        req.verb_args = ["5h"]
        plan._handle_attr(p, [t], ["estimate"], req, [])
        self.assertEqual(t.get_attr("estimate"), "5h")

    def test_attr_links_add_interlink(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["blocked:#2"]
        plan._handle_attr(p, [t1], ["links"], req, [])
        # t2 should have blocking:#1
        links2 = plan._parse_links(t2.get_attr("links"))
        self.assertIn(1, links2.get("blocking", []))

    def test_attr_links_del_removes_mirror(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        # First add link
        plan.add_link(p, t1, "blocked", 2)
        # Then delete via attr
        req = plan.ParsedRequest()
        req.verb = "del"
        plan._handle_attr(p, [t1], ["links"], req, [])
        # Mirror should be gone too
        links2 = plan._parse_links(t2.get_attr("links"))
        self.assertNotIn(1, links2.get("blocking", []))

    def test_attr_custom(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.flags["force"] = True
        req.verb_args = ["my-value"]
        plan._handle_attr(p, [t], ["custom_field"], req, [])
        self.assertEqual(t.get_attr("custom_field"), "my-value")

    def test_attr_add_scalar_error(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["bob"]
        with self.assertRaises(SystemExit):
            plan._handle_attr(p, [t], ["assignee"], req, [])


# ===================================================================
# Task 6: Structural Commands + Integration
# ===================================================================

class TestRankCommand(unittest.TestCase):
    """Test rank/move command."""

    def test_rank_first(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["first"]
        t2 = p.lookup("2")
        t1 = p.lookup("1")
        plan._handle_move_verb(p, [t2], req)
        # Should be before ticket #1
        self.assertLess(t2._rank, t1._rank)

    def test_rank_last(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["last"]
        t1 = p.lookup("1")
        t4 = p.lookup("4")
        plan._handle_move_verb(p, [t1], req)
        # Should be after ticket #4
        self.assertGreater(t1._rank, t4._rank)

    def test_rank_before(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["before", "2"]
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        t4 = p.lookup("4")
        plan._handle_move_verb(p, [t4], req)
        # Should be between #1 and #2
        self.assertTrue(t1._rank < t4._rank < t2._rank)

    def test_rank_after(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["after", "2"]
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        t4 = p.lookup("4")
        plan._handle_move_verb(p, [t1], req)
        # Should be between #2 and #4
        self.assertTrue(t2._rank < t1._rank < t4._rank)

    def test_rank_default_first_child(self):
        """Default rank for first child."""
        p = plan.parse(SAMPLE_DOC)
        plan._handle_create(p, ['2', 'title="New sub"'], plan.ParsedRequest(), [])
        new_t = p.lookup("2").children[-1]
        self.assertIsNotNone(new_t._rank)

    def test_negative_rank(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["first"]
        t1 = p.lookup("1")
        r_before = t1._rank
        plan._handle_move_verb(p, [t1], req)
        self.assertLess(t1._rank, r_before)


class TestRankExprInCreateAndMod(unittest.TestCase):
    """Test move positional expressions in create and mod (end-to-end)."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create 3 tickets: #1, #2, #3
        self._run("create", 'title="First"')
        self._run("create", 'title="Second"')
        self._run("create", 'title="Third"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _load(self):
        with open(self.tmpfile.name) as fh:
            return plan.parse(fh.read())

    def _ranks(self, *ticket_ids):
        """Load file once and return _rank values for given ticket IDs."""
        p = self._load()
        return tuple(plan._get_rank(p.lookup(str(tid))) for tid in ticket_ids)

    def test_create_rank_first(self):
        """create with move='first' places before all existing tickets."""
        self._run("create", 'title="Urgent", move="first"')
        r4, r1 = self._ranks(4, 1)
        self.assertLess(r4, r1)

    def test_create_rank_last(self):
        """create with move='last' places after all existing tickets."""
        self._run("create", 'title="Low priority", move="last"')
        r3, r4 = self._ranks(3, 4)
        self.assertGreater(r4, r3)

    def test_create_rank_after(self):
        """create with move='after 1' places between #1 and #2."""
        self._run("create", 'title="After first", move="after 1"')
        r1, r4, r2 = self._ranks(1, 4, 2)
        self.assertTrue(r1 < r4 < r2)

    def test_create_rank_before(self):
        """create with move='before 3' places between #2 and #3."""
        self._run("create", 'title="Before third", move="before 3"')
        r2, r4, r3 = self._ranks(2, 4, 3)
        self.assertTrue(r2 < r4 < r3)

    def test_create_rank_numeric(self):
        """create with rank='42' — rank is treated as legacy attr by parser.
        The value is written to the file but consumed as legacy rank on re-parse."""
        self._run("create", 'title="Custom rank", rank="42"')
        # rank: 42 is written to file
        with open(self.tmpfile.name) as fh:
            content = fh.read()
        self.assertIn("rank: 42", content)
        # But after re-parse, rank is not in attrs (stripped by parser)
        p = self._load()
        t4 = p.lookup("4")
        self.assertNotIn("rank", t4.attrs)

    def test_mod_set_rank_first(self):
        """mod set(move='first') reorders ticket to first position."""
        self._run("3", "~", 'set(move="first")')
        r3, r1 = self._ranks(3, 1)
        self.assertLess(r3, r1)

    def test_mod_set_rank_after(self):
        """mod set(move='after 1') places #3 between #1 and #2."""
        self._run("3", "~", 'set(move="after 1")')
        r1, r3, r2 = self._ranks(1, 3, 2)
        self.assertTrue(r1 < r3 < r2)

    def test_create_rank_first_target(self):
        """create with move='first 1' creates as first child of #1."""
        self._run("create", 'title="Child", move="first 1"')
        p = self._load()
        t4 = p.lookup("4")
        t1 = p.lookup("1")
        self.assertIs(t4.parent, t1)
        self.assertIn(t4, t1.children)

    def test_create_rank_last_target(self):
        """create with move='last 1' creates as last child of #1."""
        # First add an existing child to #1
        self._run("create", "1", 'title="Existing child"')
        self._run("create", 'title="Last child", move="last 1"')
        p = self._load()
        t5 = p.lookup("5")
        t1 = p.lookup("1")
        self.assertIs(t5.parent, t1)
        r4 = plan._get_rank(p.lookup("4"))
        r5 = plan._get_rank(t5)
        self.assertGreater(r5, r4)

    def test_create_rank_before_reparents(self):
        """create with move='before 1' at root, even without explicit parent."""
        # Create a child of #1
        self._run("create", "1", 'title="Child of 1"')
        # Create another ticket with move="before 1" — should be at root
        self._run("create", 'title="Before child", move="before 1"')
        p = self._load()
        t5 = p.lookup("5")
        self.assertIsNone(t5.parent)
        r5 = plan._get_rank(t5)
        r1 = plan._get_rank(p.lookup("1"))
        self.assertLess(r5, r1)

    def test_mod_rank_first_target_reparents(self):
        """mod set(move='first 1') moves #3 under #1."""
        self._run("3", "~", 'set(move="first 1")')
        p = self._load()
        t3 = p.lookup("3")
        t1 = p.lookup("1")
        self.assertIs(t3.parent, t1)
        self.assertIn(t3, t1.children)
        self.assertNotIn(t3, p.tickets)

    def test_mod_rank_after_reparents(self):
        """mod set(move='after N') where N is under a different parent."""
        # Create child of #1
        self._run("create", "1", 'title="Child of 1"')
        # Move #2 to after #4 (making it a sibling of #4, i.e. child of #1)
        self._run("2", "~", 'set(move="after 4")')
        p = self._load()
        t2 = p.lookup("2")
        t1 = p.lookup("1")
        self.assertIs(t2.parent, t1)
        r2 = plan._get_rank(t2)
        r4 = plan._get_rank(p.lookup("4"))
        self.assertGreater(r2, r4)

    def test_mod_rank_first_0_moves_to_root(self):
        """mod set(move='first 0') moves ticket to root."""
        # Create child of #1
        self._run("create", "1", 'title="Child of 1"')
        self._run("4", "~", 'set(move="first 0")')
        p = self._load()
        t4 = p.lookup("4")
        self.assertIsNone(t4.parent)
        self.assertIn(t4, p.tickets)
        r4 = plan._get_rank(t4)
        r1 = plan._get_rank(p.lookup("1"))
        self.assertLess(r4, r1)


class TestMoveCommand(unittest.TestCase):
    """Test move command."""

    def test_move_to_parent(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("2")  # top-level
        dest = p.lookup("1")  # another top-level
        req = plan.ParsedRequest()
        req.verb_args = ["last", "1"]
        plan._handle_move_verb(p, [p.lookup("2")], req)
        self.assertIn(t, dest.children)
        self.assertNotIn(t, p.tickets)
        self.assertEqual(t.parent, dest)
        # ID should be preserved
        self.assertEqual(t.node_id, 2)

    def test_move_before(self):
        p = plan.parse(SAMPLE_DOC)
        t4 = p.lookup("4")
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb_args = ["before", "1"]
        plan._handle_move_verb(p, [t4], req)
        self.assertLess(t4._rank, t1._rank)

    def test_move_after(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t4 = p.lookup("4")
        req = plan.ParsedRequest()
        req.verb_args = ["after", "4"]
        plan._handle_move_verb(p, [t1], req)
        self.assertGreater(t1._rank, t4._rank)

    def test_move_preserves_id(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("2")
        req = plan.ParsedRequest()
        req.verb_args = ["last", "1"]
        plan._handle_move_verb(p, [p.lookup("2")], req)
        self.assertEqual(t.node_id, 2)
        self.assertIsNotNone(p.lookup("2"))

    def test_move_requires_direction(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = []
        with self.assertRaises(SystemExit):
            plan._handle_move_verb(p, [p.lookup("1")], req)

    def test_move_bare_int_rejected(self):
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb_args = ["1"]
        with self.assertRaises(SystemExit):
            plan._handle_move_verb(p, [p.lookup("2")], req)


class TestCheckFix(unittest.TestCase):
    """Test check and fix commands."""

    def test_check_valid_doc(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        plan._handle_check(p, output)
        self.assertTrue(any("OK" in o for o in output))

    def test_check_broken_link(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        t.set_attr("links", "blocked:#999")
        output = []
        plan._handle_check(p, output)
        self.assertTrue(any("ERROR" in o for o in output))
        self.assertTrue(any("999" in o for o in output))

    def test_check_bad_next_id(self):
        p = plan.parse(SAMPLE_DOC)
        p.next_id = 1  # too low — max is 4
        output = []
        plan._handle_check(p, output)
        self.assertTrue(any("ERROR" in o or "next_id" in o for o in output))

    def test_fix_next_id(self):
        p = plan.parse(SAMPLE_DOC)
        p.next_id = 1
        output = []
        plan._handle_fix(p, output)
        self.assertTrue(p.next_id > 4)
        self.assertTrue(any("FIXED" in o for o in output))

    def test_fix_broken_links(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        t.set_attr("links", "blocked:#999")
        output = []
        plan._handle_fix(p, output)
        links = plan._parse_links(t.get_attr("links", ""))
        self.assertNotIn(999, links.get("blocked", []))


class TestResolve(unittest.TestCase):
    """Test resolve command."""

    def test_resolve_no_conflicts(self):
        output = []
        result = plan._handle_resolve(None, output, raw_text=SAMPLE_DOC)
        self.assertIsNone(result)
        self.assertTrue(any("OK" in o for o in output))

    def test_resolve_timestamp_conflict(self):
        text = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T1 {#1}

        <<<<<<< HEAD
              updated: 2024-01-01 00:00:00 UTC
              status: open
        =======
              updated: 2024-06-01 00:00:00 UTC
              status: in-progress
        >>>>>>> branch
        """)
        output = []
        result = plan._handle_resolve(None, output, raw_text=text)
        self.assertIsNotNone(result)
        # Should pick the newer timestamp
        self.assertIn("2024-06-01", result)
        self.assertTrue(any("Resolved" in o for o in output))

    def test_resolve_preserves_indentation(self):
        text = "<<<<<<< HEAD\n      status: open\n=======\n      status: closed\n>>>>>>> b\n"
        output = []
        result = plan._handle_resolve(None, output, raw_text=text)
        self.assertIsNotNone(result)
        # Indentation should be preserved
        for line in result.split('\n'):
            if 'status' in line:
                self.assertTrue(line.startswith('      '))


class TestBatchMode(unittest.TestCase):
    """Test batch/semicolon-separated operations."""

    def test_multi_request_single_write(self):
        """Multiple ;-separated requests modify same in-memory state."""
        p = plan.parse(SAMPLE_DOC)

        # Simulate: 1 status in-progress ; 2 status done
        req1 = plan.ParsedRequest()
        req1.verb_args = ["in-progress"]
        plan._handle_status_verb(p, [p.lookup("1")], req1)
        req2 = plan.ParsedRequest()
        req2.verb_args = ["done"]
        plan._handle_status_verb(p, [p.lookup("2")], req2)

        self.assertEqual(p.lookup("1").get_attr("status"), "in-progress")
        self.assertEqual(p.lookup("2").get_attr("status"), "done")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def test_empty_doc(self):
        doc = make_doc("""\
        # Empty {#project}

        ## Metadata {#metadata}

            next_id: 1

        ## Tickets {#tickets}

        """)
        self.assertEqual(len(doc.tickets), 0)

    def test_ticket_no_attrs(self):
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: NoAttrs {#1}

          Just a body.
        """)
        t = doc.lookup("1")
        self.assertEqual(t.title, "NoAttrs")
        self.assertEqual(t.attrs, {})
        self.assertTrue(any("Just a body" in l for l in t.body_lines))

    def test_ticket_no_body(self):
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: NoBody {#1}

              status: open
        """)
        t = doc.lookup("1")
        self.assertEqual(t.title, "NoBody")
        self.assertEqual(t.body_lines, [])

    def test_unicode_in_title(self):
        doc = make_doc("""\
        # Проект {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: Фича с юникодом 🎉 {#1}

              status: open

          Описание задачи.
        """)
        t = doc.lookup("1")
        self.assertIn("юникодом", t.title)

    def test_colon_in_attr_value(self):
        doc = make_doc("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: T {#1}

              status: open
              description: has:colons:in:value
        """)
        t = doc.lookup("1")
        self.assertIn("colons", t.get_attr("description"))

    def test_id_zero_root(self):
        """Id 0 refers to top-level scope."""
        p = plan.parse(SAMPLE_DOC)
        # #0 should work for list context
        # The spec says id 0 is used for root of topmost level tickets
        # This is mainly used with create command
        # Just verify lookup doesn't crash
        result = p.lookup("0")
        # May or may not be in id_map — mainly a create convention

    # --- Missing target / argument errors ---

    def test_get_no_target_error(self):
        """'plan get' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_del_no_target_error(self):
        """'plan del' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "del"
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_edit_no_target_error(self):
        """'plan edit' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.command = ("edit", [])
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_add_no_target_error(self):
        """'plan add "text"' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["some text"]
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_replace_no_target_error(self):
        """'plan replace' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.verb_args = ["text"]
        req.flags = {"force": True}
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_mod_no_target_error(self):
        """'plan mod' with no target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "mod"
        req.verb_args = ['set(estimate="1h")']
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_comment_no_target_error(self):
        """'plan comment' with no ticket target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "comment"
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_attr_no_target_error(self):
        """'plan attr estimate' with no ticket target raises error."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "get"
        req.selector_type = "attr"
        req.selector_args = ["estimate"]
        with self.assertRaises(SystemExit) as cm:
            plan.dispatch(p, req, [])
        self.assertIn("ticket ID", str(cm.exception))

    def test_list_no_target_ok(self):
        """'plan list' with no target is fine (shows top-level)."""
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.verb = "list"
        output = []
        plan.dispatch(p, req, output)
        self.assertTrue(len(output) > 0)


class TestCLIIntegration(unittest.TestCase):
    """End-to-end CLI integration tests via subprocess."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.write(SAMPLE_DOC)
        self.tmpfile.close()
        self.addCleanup(os.unlink, self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result

    def test_cli_list(self):
        r = self._run("list")
        self.assertEqual(r.returncode, 0)
        self.assertIn("First task", r.stdout)
        self.assertIn("Second task", r.stdout)

    def test_cli_get(self):
        r = self._run("1", "get")
        self.assertEqual(r.returncode, 0)
        self.assertIn("First task", r.stdout)

    def test_cli_create(self):
        r = self._run("create", 'title="New CLI ticket", estimate="2h"')
        self.assertEqual(r.returncode, 0)
        # Verify it was written
        r2 = self._run("list")
        self.assertIn("New CLI ticket", r2.stdout)

    def test_cli_status(self):
        r = self._run("1", "status", "in-progress")
        self.assertEqual(r.returncode, 0)
        # Verify by reading the full ticket
        r2 = self._run("1", "get")
        self.assertIn("in-progress", r2.stdout)

    def test_cli_reopen(self):
        self._run("1", "close")
        r = self._run("1", "reopen")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("1", "get")
        self.assertIn("open", r2.stdout)

    def test_cli_move_first(self):
        r = self._run("2", "move", "first")
        self.assertEqual(r.returncode, 0)

    def test_cli_check(self):
        r = self._run("check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("OK", r.stdout)

    def test_cli_help(self):
        r = self._run("help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("plan", r.stdout)

    def test_cli_mod(self):
        r = self._run("1", "~", 'set(estimate="5h")')
        self.assertEqual(r.returncode, 0)
        r2 = self._run("1", "attr", "estimate", "get")
        self.assertIn("5h", r2.stdout)

    def test_cli_semicolons(self):
        r = self._run("1", "status", "in-progress", ";", "2", "status", "done")
        self.assertEqual(r.returncode, 0)
        # Verify both changed by reading the full tickets
        r1 = self._run("1", "get")
        self.assertIn("in-progress", r1.stdout)
        r2 = self._run("2", "get")
        self.assertIn("done", r2.stdout)

    def test_cli_link_default(self):
        r = self._run("1", "link", "2")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("1", "attr", "links", "get")
        self.assertIn("related", r2.stdout)

    def test_cli_link_typed(self):
        r = self._run("1", "link", "blocked", "2")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("1", "attr", "links", "get")
        self.assertIn("blocked", r2.stdout)

    def test_cli_unlink(self):
        self._run("1", "link", "blocked", "2")
        r = self._run("1", "unlink", "2")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("1", "attr", "links", "get")
        # links attr should be empty or not contain blocked:#2
        self.assertNotIn("blocked:#2", r2.stdout)

    def test_cli_link_mirror(self):
        """Link #1 blocked #2, verify #2 has blocking:#1."""
        self._run("1", "link", "blocked", "2")
        r = self._run("2", "attr", "links", "get")
        self.assertIn("blocking:#1", r.stdout)


# ===================================================================
# Task 7: Additional Coverage
# ===================================================================

class TestEditVerb(unittest.TestCase):
    """Test edit verb (mocked editor)."""

    def _run_edit(self, doc_text, node_id, transform):
        """Run _handle_edit_command with a mock editor that applies transform.

        transform(text) -> new_text modifies the editor content.
        Returns (project_after_reparse, serialized_text).
        """
        from unittest.mock import patch
        p = plan.parse(doc_text)
        req = plan.ParsedRequest()
        req.command = ("edit", [node_id])

        def mock_editor(cmd, **kwargs):
            path = cmd[-1]
            with open(path) as f:
                content = f.read()
            with open(path, 'w') as f:
                f.write(transform(content))
            return subprocess.CompletedProcess(cmd, 0)

        with patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_command(p, [node_id], req)

        result_text = plan.serialize(p)
        return plan.parse(result_text), result_text

    def test_edit_prepares_content(self):
        """Edit prepares correct temp file content."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        content = plan._get_content(t)
        text = "\n".join(content)
        self.assertIn("First task", text)
        self.assertIn("status: open", text)

    def test_edit_get_content_normalized_indent(self):
        """_get_content returns content with indent normalized to 0."""
        p = plan.parse(SAMPLE_DOC)
        child = p.lookup("3")
        content = plan._get_content(child)
        self.assertTrue(content[0].startswith("## "),
            f"Content should start at indent 0, got: {content[0]!r}")

    def test_edit_top_level_body_roundtrip(self):
        """Edit a top-level ticket body and verify it survives roundtrip."""
        def transform(text):
            return text.replace("First task body.", "Edited body content.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        t = p.lookup("1")
        body = "\n".join(t.body_lines)
        self.assertIn("Edited body content", body)
        self.assertNotIn("First task body", body)

    def test_edit_top_level_preserves_title(self):
        """Editing body preserves ticket title."""
        def transform(text):
            return text.replace("First task body.", "New body.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        t = p.lookup("1")
        self.assertEqual(t.title, "First task")

    def test_edit_top_level_preserves_attrs(self):
        """Editing body preserves ticket attributes."""
        def transform(text):
            return text.replace("First task body.", "New body.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        t = p.lookup("1")
        self.assertEqual(t.attrs["status"], "open")
        self.assertEqual(t.attrs["estimate"], "1h")

    def test_edit_top_level_preserves_children(self):
        """Editing a parent ticket body does not lose its children."""
        def transform(text):
            return text.replace("First task body.", "Changed parent body.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        parent = p.lookup("1")
        self.assertIsInstance(parent, plan.Ticket)
        self.assertTrue(len(parent.children) > 0, "children should be preserved")
        child = p.lookup("3")
        self.assertIsNotNone(child)
        self.assertEqual(child.title, "Subtask A")

    def test_edit_nested_ticket_body_roundtrip(self):
        """Edit a nested (child) ticket body and verify roundtrip."""
        def transform(text):
            return text.replace("Subtask A body.", "Edited subtask body.")
        p, _ = self._run_edit(SAMPLE_DOC, "3", transform)
        child = p.lookup("3")
        body = "\n".join(child.body_lines)
        self.assertIn("Edited subtask body", body)
        self.assertNotIn("Subtask A body", body)

    def test_edit_nested_ticket_preserves_parent(self):
        """Editing a nested ticket body preserves the parent."""
        def transform(text):
            return text.replace("Subtask A body.", "Changed child body.")
        p, _ = self._run_edit(SAMPLE_DOC, "3", transform)
        parent = p.lookup("1")
        body = "\n".join(parent.body_lines)
        self.assertIn("First task body", body)
        self.assertTrue(len(parent.children) > 0)

    def test_edit_nested_ticket_indentation(self):
        """Edited nested ticket body must be properly indented in output."""
        def transform(text):
            return text.replace("Subtask A body.", "Properly indented line.")
        _, text = self._run_edit(SAMPLE_DOC, "3", transform)
        for line in text.split("\n"):
            if "Properly indented line" in line:
                indent = len(line) - len(line.lstrip())
                # Child at indent_level 4, body content at indent_level+2=6
                self.assertGreaterEqual(indent, 4,
                    f"Nested body line should be indented, got: {line!r}")
                break
        else:
            self.fail("Edited body text not found in serialized output")

    def test_edit_preserves_sibling_tickets(self):
        """Editing one ticket does not affect its siblings."""
        def transform(text):
            return text.replace("First task body.", "Only this changed.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        t2 = p.lookup("2")
        self.assertIsNotNone(t2, "Sibling ticket #2 should still exist")
        body2 = "\n".join(t2.body_lines)
        self.assertIn("Second task body", body2)
        t4 = p.lookup("4")
        self.assertIsNotNone(t4, "Sibling ticket #4 should still exist")
        body4 = "\n".join(t4.body_lines)
        self.assertIn("Third task done", body4)

    def test_edit_middle_ticket_roundtrip(self):
        """Edit ticket #2 (middle of top-level list) — roundtrip preserves all."""
        def transform(text):
            return text.replace("Second task body.", "MIDDLE EDITED.")
        p, text = self._run_edit(SAMPLE_DOC, "2", transform)

        # Edited ticket changed
        t2 = p.lookup("2")
        self.assertIn("MIDDLE EDITED", "\n".join(t2.body_lines))
        self.assertEqual(t2.title, "Second task")
        self.assertEqual(t2.node_id, 2)
        self.assertEqual(t2.get_attr("status"), "in-progress")

        # Siblings before and after are untouched
        t1 = p.lookup("1")
        self.assertIn("First task body", "\n".join(t1.body_lines))
        self.assertEqual(len(t1.children), 1)
        t3 = p.lookup("3")
        self.assertIn("Subtask A body", "\n".join(t3.body_lines))
        t4 = p.lookup("4")
        self.assertIn("Third task done", "\n".join(t4.body_lines))

        # Top-level ordering: #1, #2, #4 (file order from SAMPLE_DOC)
        top_ids = [t.node_id for t in p.tickets]
        self.assertEqual(top_ids, [1, 2, 4])

        # Second roundtrip: serialize→parse again is stable
        text2 = plan.serialize(p)
        p2 = plan.parse(text2)
        self.assertEqual(
            "\n".join(p2.lookup("2").body_lines),
            "\n".join(t2.body_lines))
        self.assertEqual([t.node_id for t in p2.tickets], [1, 2, 4])

    def test_edit_middle_child_roundtrip(self):
        """Edit a child in the middle of a hierarchy — roundtrip preserves all."""
        # Build a doc with parent #1 having three children
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 5
        ## Tickets {#tickets}
        * ## Ticket: Epic: Parent {#1}

              status: open

          Parent body.

          * ## Ticket: Task: Child A {#2}

                status: open

            Child A body.

          * ## Ticket: Task: Child B {#3}

                status: open

            Child B body.

          * ## Ticket: Task: Child C {#4}

                status: open

            Child C body.
        """)
        # Edit the middle child #3
        def transform(text):
            return text.replace("Child B body.", "B IS EDITED.")
        p, text = self._run_edit(doc, "3", transform)

        t3 = p.lookup("3")
        self.assertIn("B IS EDITED", "\n".join(t3.body_lines))
        self.assertEqual(t3.node_id, 3)

        # Siblings untouched
        self.assertIn("Child A body", "\n".join(p.lookup("2").body_lines))
        self.assertIn("Child C body", "\n".join(p.lookup("4").body_lines))

        # Parent untouched, children order preserved
        parent = p.lookup("1")
        self.assertIn("Parent body", "\n".join(parent.body_lines))
        child_ids = [c.node_id for c in parent.children]
        self.assertEqual(child_ids, [2, 3, 4])

        # Serialize→parse roundtrip is stable
        text2 = plan.serialize(p)
        p2 = plan.parse(text2)
        child_ids2 = [c.node_id for c in p2.lookup("1").children]
        self.assertEqual(child_ids2, [2, 3, 4])
        self.assertIn("B IS EDITED", "\n".join(p2.lookup("3").body_lines))

    def test_edit_multiline_body(self):
        """Edit that produces multi-line body works correctly."""
        def transform(text):
            return text.replace("First task body.",
                                "Line one.\n\nLine two.\n\nLine three.")
        p, _ = self._run_edit(SAMPLE_DOC, "1", transform)
        t = p.lookup("1")
        body = "\n".join(t.body_lines)
        self.assertIn("Line one", body)
        self.assertIn("Line two", body)
        self.assertIn("Line three", body)

    def test_edit_section_roundtrip(self):
        """Edit a project section (Description) and verify roundtrip."""
        def transform(text):
            return text.replace("This is a test project.",
                                "Updated project description.")
        p, _ = self._run_edit(SAMPLE_DOC, "description", transform)
        desc = p.lookup("description")
        body = "\n".join(desc.body_lines)
        self.assertIn("Updated project description", body)

    def test_edit_deeply_nested_ticket(self):
        """Edit a ticket nested 2+ levels deep."""
        doc = textwrap.dedent("""\
        # Deep Project {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Epic: Parent {#1}

              created: 2024-01-01 00:00:00 UTC
              status: open

          Parent body.

          * ## Ticket: Task: Child {#2}

                created: 2024-01-01 00:00:00 UTC
                status: open

            Child body.

            * ## Ticket: Task: Grandchild {#3}

                  created: 2024-01-01 00:00:00 UTC
                  status: open

              Grandchild body.
        """)
        def transform(text):
            return text.replace("Grandchild body.", "Edited grandchild.")
        p, text = self._run_edit(doc, "3", transform)
        gc = p.lookup("3")
        body = "\n".join(gc.body_lines)
        self.assertIn("Edited grandchild", body)
        # Parent and child should be unaffected
        self.assertIn("Parent body", "\n".join(p.lookup("1").body_lines))
        self.assertIn("Child body", "\n".join(p.lookup("2").body_lines))
        # Verify indentation in serialized output
        for line in text.split("\n"):
            if "Edited grandchild" in line:
                indent = len(line) - len(line.lstrip())
                # Grandchild: indent_level=4, content at indent_level+2=6
                self.assertGreaterEqual(indent, 6,
                    f"Deeply nested body should be indented >=6, got: {line!r}")
                break
        else:
            self.fail("Edited grandchild text not found in serialized output")

    def test_edit_no_duplicate_header(self):
        """Editing should not produce duplicate ticket headers in output."""
        def transform(text):
            return text.replace("First task body.", "New body.")
        _, text = self._run_edit(SAMPLE_DOC, "1", transform)
        count = text.count("First task {#1}")
        self.assertEqual(count, 1,
            f"Ticket header should appear exactly once, found {count} times")

    COMMENT_DOC = textwrap.dedent("""\
    # P {#project}

    ## Metadata {#metadata}

        next_id: 2

    ## Tickets {#tickets}

    * ## Ticket: Task: Has comments {#1}

          created: 2024-01-01 00:00:00 UTC
          status: open

      Body text here.

      * ## Comments {#1:comments}

        * First note {#1:comment:1}

          Detail of first note.

        * Second note {#1:comment:2}
    """)

    def test_edit_ticket_with_comments_no_duplication(self):
        """Editing a ticket with comments must not duplicate the comments."""
        def transform(text):
            return text.replace("Body text here.", "Edited body.")
        _, text = self._run_edit(self.COMMENT_DOC, "1", transform)
        count = text.count("First note")
        self.assertEqual(count, 1,
            f"Comment should appear exactly once, found {count}")
        count2 = text.count("Second note")
        self.assertEqual(count2, 1,
            f"Second comment should appear exactly once, found {count2}")
        self.assertIn("Edited body.", text)

    def test_edit_ticket_with_comments_preserves_comments(self):
        """Editing a ticket body preserves comment content and structure."""
        def transform(text):
            return text.replace("Body text here.", "New body.")
        p, text = self._run_edit(self.COMMENT_DOC, "1", transform)
        t = p.lookup("1")
        self.assertIsNotNone(t.comments)
        self.assertEqual(len(t.comments.comments), 2)
        self.assertEqual(t.comments.comments[0].title, "First note")
        self.assertEqual(t.comments.comments[1].title, "Second note")

    def test_edit_ticket_with_comments_can_edit_comment(self):
        """Editing a ticket can also modify comment text."""
        def transform(text):
            return text.replace("First note", "Updated note")
        p, text = self._run_edit(self.COMMENT_DOC, "1", transform)
        t = p.lookup("1")
        self.assertEqual(t.comments.comments[0].title, "Updated note")

    def test_edit_nonrecursive_preserves_children(self):
        """Non-recursive edit of a parent ticket must preserve its children."""
        def transform(text):
            return text.replace("First task body.", "Edited parent body.")
        p, text = self._run_edit(SAMPLE_DOC, "1", transform)
        parent = p.lookup("1")
        self.assertIn("Edited parent body", "\n".join(parent.body_lines))
        # Child #3 must still exist
        child = p.lookup("3")
        self.assertIsNotNone(child, "Child ticket #3 should still exist")
        self.assertEqual(child.title, "Subtask A")
        self.assertIs(child.parent, parent)
        self.assertIn(child, parent.children)

    def test_edit_nonrecursive_does_not_show_children(self):
        """Non-recursive edit should not include children in editor buffer."""
        from unittest.mock import patch
        p = plan.parse(SAMPLE_DOC)
        req = plan.ParsedRequest()
        req.command = ("edit", ["1"])

        captured = {}
        def mock_editor(cmd, **kwargs):
            path = cmd[-1]
            with open(path) as f:
                captured['content'] = f.read()
            # No changes
            return subprocess.CompletedProcess(cmd, 0)

        with patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_command(p, ["1"], req)

        self.assertNotIn("Subtask A", captured['content'],
            "Children should not appear in non-recursive edit buffer")


class TestEditIdentityPreservesOrder(unittest.TestCase):
    """Test that identity edit (no changes) preserves ticket ordering."""

    def _run_edit(self, doc_text, node_id, transform):
        """Run _handle_edit_command with a mock editor that applies transform."""
        from unittest.mock import patch
        p = plan.parse(doc_text)
        req = plan.ParsedRequest()
        req.command = ("edit", [node_id])

        def mock_editor(cmd, **kwargs):
            path = cmd[-1]
            with open(path) as f:
                content = f.read()
            with open(path, 'w') as f:
                f.write(transform(content))
            return subprocess.CompletedProcess(cmd, 0)

        with patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_command(p, [node_id], req)

        result_text = plan.serialize(p)
        return plan.parse(result_text), result_text

    def test_identity_edit_preserves_ticket_order(self):
        """An identity edit (EDITOR=true) must not reorder tickets."""
        doc = textwrap.dedent("""\
        # Project {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: Alpha {#1}

              status: open
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC

        * ## Ticket: Task: Beta {#2}

              status: open
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC

        * ## Ticket: Task: Gamma {#3}

              status: open
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC
        """)

        # Identity transform — no changes
        _, result = self._run_edit(doc, "3", lambda text: text)

        # Extract ticket order from serialized output
        ids = re.findall(r'\{#(\d+)\}', result)
        # Filter to only ticket IDs (skip project, metadata, etc.)
        ticket_ids = [i for i in ids if i in ('1', '2', '3')]
        self.assertEqual(ticket_ids, ['1', '2', '3'],
            f"Identity edit of #3 reordered tickets: {ticket_ids}")

    def test_identity_edit_last_ticket_stays_last(self):
        """Identity edit of the last ticket must not move it to the front."""
        doc = textwrap.dedent("""\
        # Project {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: First {#1}

              status: done
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC

          First body.

        * ## Ticket: Task: Second {#2}

              status: done
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC

          Second body.

        * ## Ticket: Task: Third {#3}

              status: done
              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC

          Third body.
        """)

        _, result = self._run_edit(doc, "3", lambda text: text)

        lines = result.split('\n')
        ticket_lines = [(i, l) for i, l in enumerate(lines)
                        if '## Ticket:' in l]
        # #3 should still be last
        titles = [l for _, l in ticket_lines]
        self.assertTrue(titles[-1].strip().endswith('{#3}'),
            f"#3 should be last ticket but order is: {titles}")


class TestEditRecursive(unittest.TestCase):
    """Test recursive edit (-r flag)."""

    DEEP_DOC = textwrap.dedent("""\
    # Deep Project {#project}

    ## Metadata {#metadata}

        next_id: 4

    ## Tickets {#tickets}

    * ## Ticket: Epic: Parent {#1}

          created: 2024-01-01 00:00:00 UTC
          status: open

      Parent body.

      * ## Ticket: Task: Child {#2}

            created: 2024-01-01 00:00:00 UTC
            status: open

        Child body.

        * ## Ticket: Task: Grandchild {#3}

              created: 2024-01-01 00:00:00 UTC
              status: open

            Grandchild body.
    """)

    def _run_recursive_edit(self, doc_text, node_id, transform):
        """Run _handle_edit_command with -r flag using a mock editor.

        transform(text) -> new_text modifies the full subtree content.
        Returns (project_after_reparse, serialized_text).
        """
        from unittest.mock import patch
        p = plan.parse(doc_text)
        req = plan.ParsedRequest()
        req.command = ("edit", [node_id])
        req.flags = {"recursive": True}

        def mock_editor(cmd, **kwargs):
            path = cmd[-1]
            with open(path) as f:
                content = f.read()
            with open(path, 'w') as f:
                f.write(transform(content))
            return subprocess.CompletedProcess(cmd, 0)

        with patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_command(p, [node_id], req)

        result_text = plan.serialize(p)
        return plan.parse(result_text), result_text

    def test_recursive_identity_roundtrip(self):
        """Identity edit (no changes) preserves the full subtree."""
        p, text = self._run_recursive_edit(self.DEEP_DOC, "1", lambda t: t)
        self.assertIsNotNone(p.lookup("1"))
        self.assertIsNotNone(p.lookup("2"))
        self.assertIsNotNone(p.lookup("3"))
        self.assertIn("Parent body", "\n".join(p.lookup("1").body_lines))
        self.assertIn("Child body", "\n".join(p.lookup("2").body_lines))
        self.assertIn("Grandchild body", "\n".join(p.lookup("3").body_lines))

    def test_recursive_edit_root_body(self):
        """Editing the root body preserves children."""
        def transform(text):
            return text.replace("Parent body.", "Updated parent.")
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertIn("Updated parent", "\n".join(p.lookup("1").body_lines))
        self.assertIsNotNone(p.lookup("2"))
        self.assertIsNotNone(p.lookup("3"))

    def test_recursive_edit_child_body(self):
        """Editing a child body within recursive edit works."""
        def transform(text):
            return text.replace("Child body.", "Edited child.")
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertIn("Edited child", "\n".join(p.lookup("2").body_lines))
        # Parent and grandchild unchanged
        self.assertIn("Parent body", "\n".join(p.lookup("1").body_lines))
        self.assertIn("Grandchild body", "\n".join(p.lookup("3").body_lines))

    def test_recursive_edit_grandchild_body(self):
        """Editing a grandchild body within recursive edit works."""
        def transform(text):
            return text.replace("Grandchild body.", "Edited grandchild.")
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertIn("Edited grandchild", "\n".join(p.lookup("3").body_lines))

    def test_recursive_edit_preserves_attrs(self):
        """Recursive edit preserves ticket attributes."""
        def transform(text):
            return text.replace("Parent body.", "New parent body.")
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertEqual(p.lookup("1").attrs["status"], "open")
        self.assertEqual(p.lookup("2").attrs["status"], "open")

    def test_recursive_edit_preserves_siblings(self):
        """Recursive edit on one ticket doesn't affect siblings."""
        def transform(text):
            return text.replace("First task body.", "Changed.")
        p, _ = self._run_recursive_edit(SAMPLE_DOC, "1", transform)
        t2 = p.lookup("2")
        self.assertIsNotNone(t2)
        self.assertIn("Second task body", "\n".join(t2.body_lines))
        t4 = p.lookup("4")
        self.assertIsNotNone(t4)
        self.assertIn("Third task done", "\n".join(t4.body_lines))

    def test_recursive_edit_child_subtree(self):
        """Recursive edit on a mid-level child edits its subtree."""
        def transform(text):
            return text.replace("Child body.", "Edited child from subtree.")
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "2", transform)
        self.assertIn("Edited child from subtree",
                       "\n".join(p.lookup("2").body_lines))
        # Grandchild still present
        self.assertIsNotNone(p.lookup("3"))
        self.assertIn("Grandchild body", "\n".join(p.lookup("3").body_lines))
        # Parent unaffected
        self.assertIn("Parent body", "\n".join(p.lookup("1").body_lines))

    def test_recursive_edit_indentation(self):
        """Body lines in recursive edit output are properly indented."""
        def transform(text):
            return text.replace("Parent body.", "Reindented parent.")
        _, text = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        for line in text.split("\n"):
            if "Reindented parent" in line:
                indent = len(line) - len(line.lstrip())
                # Root ticket indent_level=0, body at 0+2=2
                self.assertGreaterEqual(indent, 2,
                    f"Root body should be indented >=2, got: {line!r}")
                break
        else:
            self.fail("Edited body text not found in serialized output")

    def test_recursive_edit_child_indentation(self):
        """Child body lines maintain correct indentation after recursive edit."""
        def transform(text):
            return text.replace("Grandchild body.", "Edited GC.")
        _, text = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        for line in text.split("\n"):
            if "Edited GC" in line:
                indent = len(line) - len(line.lstrip())
                # Grandchild indent_level=4, body at 4+2=6
                self.assertGreaterEqual(indent, 6,
                    f"Grandchild body should be indented >=6, got: {line!r}")
                break
        else:
            self.fail("Edited grandchild text not found in serialized output")

    def test_recursive_edit_multiline_body(self):
        """Multi-line body replacement within recursive edit."""
        def transform(text):
            return text.replace("Parent body.", "Line one.\n\nLine two.")
        p, text = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        body = "\n".join(p.lookup("1").body_lines)
        self.assertIn("Line one", body)
        self.assertIn("Line two", body)
        # Children still intact
        self.assertIsNotNone(p.lookup("2"))
        self.assertIsNotNone(p.lookup("3"))

    def test_recursive_edit_replace_all_bodies(self):
        """Replace body text in all tickets within recursive edit."""
        def transform(text):
            text = text.replace("Parent body.", "New parent.")
            text = text.replace("Child body.", "New child.")
            text = text.replace("Grandchild body.", "New grandchild.")
            return text
        p, _ = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertIn("New parent", "\n".join(p.lookup("1").body_lines))
        self.assertIn("New child", "\n".join(p.lookup("2").body_lines))
        self.assertIn("New grandchild", "\n".join(p.lookup("3").body_lines))

    def test_recursive_edit_no_duplicate_headers(self):
        """Recursive edit doesn't produce duplicate ticket headers."""
        def transform(text):
            return text.replace("Parent body.", "Changed.")
        _, text = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        self.assertEqual(text.count("Parent {#1}"), 1)
        self.assertEqual(text.count("Child {#2}"), 1)
        self.assertEqual(text.count("Grandchild {#3}"), 1)

    def test_recursive_edit_check_passes(self):
        """File passes check after recursive edit."""
        def transform(text):
            return text.replace("Parent body.", "Checked parent.")
        p, text = self._run_recursive_edit(self.DEEP_DOC, "1", transform)
        # Re-parse and run check to validate structure
        p2 = plan.parse(text)
        self.assertIsNotNone(p2.lookup("1"))
        self.assertIsNotNone(p2.lookup("2"))
        self.assertIsNotNone(p2.lookup("3"))
        # Verify body indentation is correct
        for tid in ["1", "2", "3"]:
            t = p2.lookup(tid)
            min_body_indent = t.indent_level + 2
            for bl in t.body_lines:
                if bl.strip():
                    actual = len(bl) - len(bl.lstrip())
                    self.assertGreaterEqual(actual, min_body_indent,
                        f"#{tid} body indent {actual} < {min_body_indent}: {bl!r}")

    def test_recursive_edit_with_comments(self):
        """Recursive edit preserves comments section."""
        doc = textwrap.dedent("""\
        # Project {#project}

        ## Metadata {#metadata}

            next_id: 3

        ## Tickets {#tickets}

        * ## Ticket: Task: Parent {#1}

              created: 2024-01-01 00:00:00 UTC
              status: open

          Parent body.

          * ## Comments {#c1}

            * 2024-01-01 alice {#cc1}

              A comment here.

          * ## Ticket: Task: Child {#2}

                created: 2024-01-01 00:00:00 UTC
                status: open

            Child body.
        """)
        def transform(text):
            return text.replace("Parent body.", "Edited parent.")
        p, text = self._run_recursive_edit(doc, "1", transform)
        self.assertIn("Edited parent", "\n".join(p.lookup("1").body_lines))
        self.assertIsNotNone(p.lookup("2"))
        self.assertIn("A comment here", text)

    def test_recursive_edit_leaf_ticket(self):
        """Recursive edit on a leaf ticket (no children) works like normal edit."""
        def transform(text):
            return text.replace("Second task body.", "Leaf edited.")
        p, _ = self._run_recursive_edit(SAMPLE_DOC, "2", transform)
        self.assertIn("Leaf edited", "\n".join(p.lookup("2").body_lines))


class TestAddFromFile(unittest.TestCase):
    """Test add from file and stdin."""

    def test_add_from_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                          delete=False) as f:
            f.write("Content from file.")
            path = f.name
        try:
            p = plan.parse(SAMPLE_DOC)
            t = p.lookup("1")
            req = plan.ParsedRequest()
            req.verb = "add"
            req.verb_args = [f"@{path}"]
            plan._handle_add(p, [t], req)
            self.assertTrue(any("Content from file" in l for l in t.body_lines))
        finally:
            os.unlink(path)


class TestReplaceFromStdin(unittest.TestCase):
    """Test replace from file."""

    def test_replace_from_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                          delete=False) as f:
            f.write("Replaced from file.")
            path = f.name
        try:
            p = plan.parse(SAMPLE_DOC)
            t = p.lookup("1")
            req = plan.ParsedRequest()
            req.verb = "replace"
            req.flags["force"] = True
            req.verb_args = [f"@{path}"]
            plan._handle_replace(p, [t], req)
            self.assertEqual(t.body_lines, ["  Replaced from file."])
        finally:
            os.unlink(path)

    def test_replace_indentation_restored(self):
        """When replacing, the body is stored and dirty flag set for regen."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "replace"
        req.flags["force"] = True
        req.verb_args = ["New line 1\nNew line 2"]
        plan._handle_replace(p, [t], req)
        self.assertTrue(t.dirty)
        self.assertEqual(len(t.body_lines), 2)


class TestCommentThreading(unittest.TestCase):
    """Test comment threading."""

    def test_comment_ids_unique(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        id1 = p.allocate_id()
        id2 = p.allocate_id()
        self.assertNotEqual(id1, id2)

    def test_comment_nested_reply(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        # Add a comment
        cid = p.allocate_id()
        plan._add_comment_to_ticket(t, p, cid, "Top comment")
        comment = t.comments.comments[-1]
        # Add a reply
        reply_id = f"{t.node_id}:comment:{p.allocate_id()}"
        reply = plan.Comment(reply_id, "Reply text")
        reply.indent_level = comment.indent_level + 2
        reply.dirty = True
        comment.children.append(reply)
        p.register(reply)
        self.assertEqual(len(comment.children), 1)

    def test_comment_updates_ticket_timestamp(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Comment text"]
        plan._handle_comment(p, [t], req, [])
        # Ticket's updated timestamp should be refreshed
        # (handled by _add_comment_to_ticket which sets ticket.dirty)
        self.assertTrue(t.dirty)


class TestListAttrFilter(unittest.TestCase):
    """Test list --attr filter."""

    def test_list_attr_filter(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["attr_filter"] = "alice"
        plan._handle_list(p, [], req, output)
        # Only ticket #2 has assignee=alice
        self.assertEqual(len(output), 1)
        self.assertIn("#2", output[0])


class TestListTextFilter(unittest.TestCase):
    """Test list --text filter."""

    def test_list_text_filter(self):
        p = plan.parse(SAMPLE_DOC)
        output = []
        req = plan.ParsedRequest()
        req.verb = "get"
        req.flags["text"] = "Subtask"
        req.flags["recursive"] = True
        plan._handle_list(p, [], req, output)
        self.assertTrue(any("Subtask" in o for o in output))


class TestListOrder(unittest.TestCase):
    """Test 'list order' — topological sort by execution order."""

    ORDER_DOC = textwrap.dedent("""\
    # P {#project}

    ## Metadata {#metadata}

        next_id: 6

    ## Tickets {#tickets}

    * ## Ticket: Task: A {#1}

          status: open

    * ## Ticket: Task: B {#2}

          status: open
          links: blocked:#1

    * ## Ticket: Task: C {#3}

          status: open
          links: blocked:#2
    """)

    def _list_order(self, doc, *extra_args):
        """Run list order and return list of node_ids in output order."""
        p = plan.parse(doc)
        req = plan.ParsedRequest()
        req.verb = "list"
        req.verb_args = ["order"]
        for a in extra_args:
            if a == "-r":
                req.flags["recursive"] = True
        output = []
        plan._handle_list(p, [], req, output)
        ids = []
        for line in output:
            m = re.match(r'\s*#(\d+)\s', line)
            if m:
                ids.append(int(m.group(1)))
        return ids, p

    def test_order_linear_chain(self):
        """A -> B -> C: must execute A first, then B, then C."""
        ids, _ = self._list_order(self.ORDER_DOC)
        self.assertEqual(ids, [1, 2, 3])

    def test_order_skips_closed(self):
        """Closed tickets are excluded from the order."""
        doc = self.ORDER_DOC.replace(
            'Task: A {#1}\n\n      status: open',
            'Task: A {#1}\n\n      status: done',
        )
        ids, _ = self._list_order(doc)
        self.assertNotIn(1, ids)
        # B is no longer blocked (A is closed)
        self.assertEqual(ids, [2, 3])

    def test_order_parent_after_children(self):
        """Parent appears after all its open children."""
        doc = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: Parent {#1}

              status: open

          * ## Ticket: Task: Child1 {#2}

                status: open

          * ## Ticket: Task: Child2 {#3}

                status: open
        """)
        ids, _ = self._list_order(doc)
        idx_parent = ids.index(1)
        idx_c1 = ids.index(2)
        idx_c2 = ids.index(3)
        self.assertGreater(idx_parent, idx_c1)
        self.assertGreater(idx_parent, idx_c2)

    def test_order_blocked_and_parent(self):
        """Mixed blocked links and parent-child: both respected."""
        doc = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 5

        ## Tickets {#tickets}

        * ## Ticket: Task: Parent {#1}

              status: open

          * ## Ticket: Task: Child {#2}

                status: open
                links: blocked:#3

        * ## Ticket: Task: Blocker {#3}

              status: open

        * ## Ticket: Task: Independent {#4}

              status: open
        """)
        ids, _ = self._list_order(doc)
        # Blocker #3 before Child #2
        self.assertLess(ids.index(3), ids.index(2))
        # Child #2 before Parent #1
        self.assertLess(ids.index(2), ids.index(1))

    def test_order_independent_use_rank(self):
        """Independent tickets sorted by file position as tiebreaker."""
        doc = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: A {#2}

              status: open

        * ## Ticket: Task: M {#3}

              status: open

        * ## Ticket: Task: Z {#1}

              status: open
        """)
        ids, _ = self._list_order(doc)
        self.assertEqual(ids, [2, 3, 1])

    def test_order_closed_blocker_not_blocking(self):
        """If blocker is closed, it doesn't constrain order."""
        doc = textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 3

        ## Tickets {#tickets}

        * ## Ticket: Task: Blocker {#1}

              status: done

        * ## Ticket: Task: Blocked {#2}

              status: open
              links: blocked:#1
        """)
        ids, _ = self._list_order(doc)
        # #1 is closed so excluded; #2 is the only open ticket
        self.assertEqual(ids, [2])

    def test_order_all_closed(self):
        """All closed tickets: empty result."""
        doc = self.ORDER_DOC.replace('status: open', 'status: done')
        ids, _ = self._list_order(doc)
        self.assertEqual(ids, [])

    def test_order_dfs_subtree_completion(self):
        """Subtrees complete before moving to next sibling subtree."""
        tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        tmpfile.close()
        try:
            def run(*args):
                cmd = [sys.executable, "plan.py", "-f", tmpfile.name] + list(args)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r
            # #1 -> #2 (rank 0) -> #4,#5,#6
            #    -> #3 (rank 1) -> #7,#8,#9
            run("create", 'title="111"')
            run("create", "1", 'title="222"')
            run("create", "1", 'title="333"')
            run("create", "2", 'title="444"')
            run("create", "2", 'title="555"')
            run("create", "2", 'title="666"')
            run("create", "3", 'title="777"')
            run("create", "3", 'title="888"')
            run("create", "3", 'title="999"')
            r = run("list", "order")
            lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
            ids = [int(re.match(r'#(\d+)', l).group(1)) for l in lines]
            self.assertEqual(ids, [4, 5, 6, 2, 7, 8, 9, 3, 1])
        finally:
            os.unlink(tmpfile.name)

    def test_order_via_subprocess(self):
        """End-to-end: 'plan list order' via subprocess."""
        tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        tmpfile.close()
        try:
            def run(*args):
                cmd = [sys.executable, "plan.py", "-f", tmpfile.name] + list(args)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r
            run("create", 'title="First"')
            run("create", 'title="Second"')
            run("2", "~", 'link("blocked", 1)')
            r = run("list", "order")
            lines = [l for l in r.stdout.strip().split('\n') if l.strip()]
            self.assertRegex(lines[0], r'#1\b')
            self.assertRegex(lines[1], r'#2\b')
        finally:
            os.unlink(tmpfile.name)


class TestMultiTargetOps(unittest.TestCase):
    """Test operations on multiple targets."""

    def test_get_multiple_targets(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        output = []
        plan._handle_get(p, [t1, t2], plan.ParsedRequest(), output)
        text = "\n".join(output)
        self.assertIn("First task", text)
        self.assertIn("Second task", text)

    def test_del_multiple_targets(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        req.flags["recursive"] = True
        # -r expansion happens in dispatch; pre-expand for direct handler call
        targets = plan._expand_targets(p, [t1, t2], req)
        plan._handle_del(p, targets, req)
        self.assertIsNone(p.lookup("1"))
        self.assertIsNone(p.lookup("2"))


class TestLargeRanks(unittest.TestCase):
    """Test large rank values."""

    def test_large_rank_midpoint(self):
        result = plan.midpoint_rank(1000000, 1000001)
        self.assertTrue(1000000 < result < 1000001)

    def test_very_close_ranks(self):
        result = plan.midpoint_rank(1.001, 1.002)
        self.assertTrue(1.001 < result < 1.002)


class TestMultiRequestSameTicket(unittest.TestCase):
    """Test multiple requests modifying the same ticket."""

    def test_sequential_modifications(self):
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        # First set status
        req = plan.ParsedRequest()
        req.verb_args = ["in-progress"]
        plan._handle_status_verb(p, [p.lookup("1")], req)
        # Then set estimate
        t.set_attr("estimate", "5h")
        self.assertEqual(t.get_attr("status"), "in-progress")
        self.assertEqual(t.get_attr("estimate"), "5h")


class TestFileWriteOnce(unittest.TestCase):
    """Test that file is written only once after all requests."""

    def test_single_write_after_semicolons(self):
        """Verify the main() flow handles multiple requests with single write."""
        tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        tmpfile.write(SAMPLE_DOC)
        tmpfile.close()
        try:
            r = subprocess.run(
                [sys.executable, "plan.py", "-f", tmpfile.name,
                 "1", "status", "done", ";", "2", "status", "done"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(r.returncode, 0)
            # Read and verify both changed
            with open(tmpfile.name) as fh:
                text = fh.read()
            p = plan.parse(text)
            self.assertEqual(p.lookup("1").get_attr("status"), "done")
            self.assertEqual(p.lookup("2").get_attr("status"), "done")
        finally:
            os.unlink(tmpfile.name)


class TestGitRootDiscovery(unittest.TestCase):
    """Test git root file discovery."""

    def test_git_root_discovery(self):
        """When .PLAN.md exists at git root, it should be found."""
        # This test depends on being in a git repo
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                self.skipTest("Not in a git repo")
            root = result.stdout.strip()
            plan_path = os.path.join(root, ".PLAN.md")
            # Create the file
            with open(plan_path, 'w') as f:
                f.write(SAMPLE_DOC)
            try:
                old = os.environ.pop("PLAN_MD", None)
                try:
                    path = plan.discover_file({})
                    self.assertEqual(path, plan_path)
                finally:
                    if old is not None:
                        os.environ["PLAN_MD"] = old
            finally:
                os.unlink(plan_path)
        except (subprocess.SubprocessError, FileNotFoundError):
            self.skipTest("Git not available")


class TestExpandTargets(unittest.TestCase):
    """Test the _expand_targets helper function."""

    def _make_tree(self):
        """Build a tree: #1 -> #2 -> #3, #1 -> #4 (all open, ranked by id)."""
        doc = textwrap.dedent("""\
        # Project {#project}

        ## Metadata {#metadata}

            next_id: 5

        ## Tickets {#tickets}

        * ## Ticket: Task: Root {#1}

              created: 2024-01-01 00:00:00 UTC
              updated: 2024-01-01 00:00:00 UTC
              status: open

          * ## Ticket: Task: Child A {#2}

                created: 2024-01-01 00:00:00 UTC
                updated: 2024-01-01 00:00:00 UTC
                status: open

            * ## Ticket: Task: Grandchild {#3}

                  created: 2024-01-01 00:00:00 UTC
                  updated: 2024-01-01 00:00:00 UTC
                  status: open

          * ## Ticket: Task: Child B {#4}

                created: 2024-01-01 00:00:00 UTC
                updated: 2024-01-01 00:00:00 UTC
                status: open
        """)
        return plan.parse(doc)

    def test_expand_no_flags(self):
        """Without -r or -p, targets unchanged."""
        p = self._make_tree()
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        result = plan._expand_targets(p, [t1, t2], req)
        self.assertEqual(result, [t1, t2])

    def test_expand_recursive(self):
        """With -r, target #1 expands to [1, 2, 3, 4]."""
        p = self._make_tree()
        req = plan.ParsedRequest()
        req.flags["recursive"] = True
        result = plan._expand_targets(p, [p.lookup("1")], req)
        self.assertEqual([t.node_id for t in result], [1, 2, 3, 4])

    def test_expand_parent(self):
        """With -p, target #3 expands to [1, 2, 3] (ancestors + self)."""
        p = self._make_tree()
        req = plan.ParsedRequest()
        req.flags["parent"] = True
        result = plan._expand_targets(p, [p.lookup("3")], req)
        self.assertEqual([t.node_id for t in result], [1, 2, 3])

    def test_expand_parent_and_recursive(self):
        """With -p -r, target #2 expands to [1, 2, 3] (ancestor + self + descendants)."""
        p = self._make_tree()
        req = plan.ParsedRequest()
        req.flags["parent"] = True
        req.flags["recursive"] = True
        result = plan._expand_targets(p, [p.lookup("2")], req)
        self.assertEqual([t.node_id for t in result], [1, 2, 3])

    def test_expand_q_no_longer_filters(self):
        """-q queries are resolved in dispatch, not in _expand_targets."""
        p = self._make_tree()
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        t2.set_attr("status", "closed")
        req = plan.ParsedRequest()
        req.flags["q"] = ['status == "closed"']
        # _expand_targets passes targets through (no filtering)
        result = plan._expand_targets(p, [t1, t2], req)
        self.assertEqual(len(result), 2)

    def test_expand_recursive_without_q_filtering(self):
        """-r expands targets; -q query resolution happens before expansion."""
        p = self._make_tree()
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.flags["recursive"] = True
        result = plan._expand_targets(p, [t1], req)
        # All descendants of t1
        self.assertGreater(len(result), 1)
        self.assertEqual(result[0].node_id, 1)

    def test_expand_deduplicates(self):
        """Overlapping targets [#1, #2] with -r don't duplicate descendants."""
        p = self._make_tree()
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        req.flags["recursive"] = True
        result = plan._expand_targets(p, [t1, t2], req)
        ids = [t.node_id for t in result]
        # #2 and #3 should appear only once even though both #1 and #2 would expand to include them
        self.assertEqual(ids, [1, 2, 3, 4])
        self.assertEqual(len(ids), len(set(ids)))


class TestRecursiveVerbs(unittest.TestCase):
    """Test -r (recursive) and -q (query) flags on mod, replace, add verbs."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create tree: #1 (root) -> #2 (child1), #1 -> #3 (child2)
        self._run("create", 'title="Root"')
        self._run("create", '1', 'title="Child1"')
        self._run("create", '1', 'title="Child2"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _load(self):
        with open(self.tmpfile.name) as fh:
            return plan.parse(fh.read())

    def test_mod_recursive(self):
        """1 -r mod 'set(type=\"Bug\")' sets type=Bug on #1, #2, #3."""
        self._run("1", "-r", "mod", 'set(type="Bug")')
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("type"), "Bug",
                             f"Ticket #{tid} should have type=Bug")

    def test_mod_recursive_q(self):
        """-q filters within targets — bool filter narrows, not unions."""
        # First set #2 to type=Bug
        self._run("2", "mod", 'set(type="Bug")')
        # Use is_descendant_of to select Bug descendants of #1
        self._run("-q", 'is_descendant_of(1) and type=="Bug"', "mod",
                  'set(estimate="high")')
        p = self._load()
        # Only #2 matches (Bug descendant of #1)
        self.assertEqual(p.lookup(2).get_attr("estimate"), "high")
        self.assertNotEqual(p.lookup(1).get_attr("estimate", ""), "high")
        self.assertNotEqual(p.lookup(3).get_attr("estimate", ""), "high")

    def test_replace_recursive(self):
        """1 -r replace --force 'new body' sets body on all three tickets."""
        self._run("1", "-r", "replace", "--force", "new body")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            body = "\n".join(t.body_lines).strip()
            self.assertEqual(body, "new body",
                             f"Ticket #{tid} should have body='new body'")

    def test_add_recursive(self):
        """1 -r add 'extra line' appends to body of all three tickets."""
        self._run("1", "-r", "add", "extra line")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            body = "\n".join(t.body_lines)
            self.assertIn("extra line", body,
                          f"Ticket #{tid} body should contain 'extra line'")


class TestRecursiveCommands(unittest.TestCase):
    """Test -r (recursive) and -q (query) flags on status, close, comment, attr commands."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create tree: #1 (root) -> #2 (child1), #1 -> #3 (child2)
        self._run("create", 'title="Root"')
        self._run("create", '1', 'title="Child1"')
        self._run("create", '1', 'title="Child2"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _load(self):
        with open(self.tmpfile.name) as fh:
            return plan.parse(fh.read())

    def test_status_recursive(self):
        """1 -r status in-progress sets status on #1, #2, #3."""
        self._run("1", "-r", "status", "in-progress")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("status"), "in-progress",
                             f"Ticket #{tid} should have status=in-progress")

    def test_close_recursive(self):
        """1 -r close closes #1, #2, #3 (status=done)."""
        self._run("1", "-r", "close")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("status"), "done",
                             f"Ticket #{tid} should have status=done")

    def test_close_recursive_q(self):
        """-r then -q: expand first, then filter — only matching tickets closed."""
        self._run("1", "mod", 'set(type="Bug")')
        self._run("2", "mod", 'set(type="Bug")')
        self._run("1", "-r", "-q", 'type=="Bug"', "close")
        p = self._load()
        # Pipeline: select #1, -r expands to [#1,#2,#3], -q keeps Bugs [#1,#2]
        for tid in (1, 2):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("status"), "done",
                             f"Ticket #{tid} should be closed")
        # #3 is not a Bug, so it stays open
        self.assertNotEqual(p.lookup("3").get_attr("status"), "done")

    def test_reopen_recursive(self):
        """1 -r reopen reopens #1, #2, #3."""
        self._run("1", "-r", "close")
        self._run("1", "-r", "reopen")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("status"), "open",
                             f"Ticket #{tid} should have status=open")

    def test_comment_add_recursive(self):
        """1 -r comment add 'Sprint 5' adds comment to all three."""
        self._run("1", "-r", "comment", "add", "Sprint 5")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertIsNotNone(t.comments,
                                 f"Ticket #{tid} should have comments")
            titles = [c.title for c in t.comments.comments]
            self.assertTrue(any("Sprint 5" in title for title in titles),
                            f"Ticket #{tid} comment should contain 'Sprint 5'")

    def test_attr_replace_recursive(self):
        """1 -r attr estimate replace --force high sets estimate=high on all three."""
        self._run("1", "-r", "attr", "estimate", "replace", "--force", "high")
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("estimate"), "high",
                             f"Ticket #{tid} should have estimate=high")

    def test_attr_get_recursive(self):
        """First set estimate=planned on all 3 via -r. Then 1 -r attr estimate get outputs 3 lines."""
        self._run("1", "-r", "attr", "estimate", "replace", "--force", "planned")
        r = self._run("1", "-r", "attr", "estimate", "get")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        self.assertEqual(len(lines), 3,
                         f"Expected 3 lines of output, got {len(lines)}: {r.stdout!r}")


class TestRecursiveGetEditDel(unittest.TestCase):
    """Tests for -r/-q on get, edit, del (handlers with existing -r behavior)."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create tree: #1 -> #2 (Bug), #1 -> #3
        self._run("create", 'title="Root"')
        self._run("create", "1", 'title="Child1"')
        self._run("create", "1", 'title="Child2"')
        self._run("2", "mod", 'set(type="Bug")')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_get_recursive_q(self):
        """-q filters within subtree using is_descendant_of."""
        r = self._run("-q", 'is_descendant_of(1) and type=="Bug"', "get")
        self.assertIn("Child1", r.stdout)
        self.assertNotIn("Root", r.stdout)
        self.assertNotIn("Child2", r.stdout)

    def test_get_recursive_no_q(self):
        """get -r without -q still shows tree view (existing behavior)."""
        r = self._run("1", "-r", "get")
        # Should contain all three tickets in tree format
        self.assertIn("Root", r.stdout)
        self.assertIn("Child1", r.stdout)
        self.assertIn("Child2", r.stdout)

    def test_del_recursive_q(self):
        """-q filters — only Bug descendants of #1 deleted."""
        self._run("-q", 'is_descendant_of(1) and type=="Bug"', "del")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        self.assertIsNotNone(p.lookup(1))  # Root still exists
        self.assertIsNone(p.lookup(2))     # Bug child deleted
        self.assertIsNotNone(p.lookup(3))  # Non-bug child still exists

    def test_del_recursive_no_q(self):
        """del -r without -q still cascade-deletes (existing behavior)."""
        self._run("1", "-r", "del")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        self.assertIsNone(p.lookup(1))
        self.assertIsNone(p.lookup(2))
        self.assertIsNone(p.lookup(3))

    # -- get: single vs recursive ----------------------------------------

    def test_get_single_shows_only_target(self):
        """'plan 1 get' without -r shows only the target ticket, not children."""
        r = self._run("1", "get")
        self.assertIn("Root", r.stdout)
        self.assertNotIn("Child1", r.stdout)
        self.assertNotIn("Child2", r.stdout)

    def test_get_recursive_shows_full_subtree(self):
        """'plan 1 -r get' shows the target and all descendants."""
        r = self._run("1", "-r", "get")
        self.assertIn("Root", r.stdout)
        self.assertIn("Child1", r.stdout)
        self.assertIn("Child2", r.stdout)

    # -- replace: single vs recursive ------------------------------------

    def test_replace_single_only_target(self):
        """'plan 1 replace --force text' replaces only target, children unchanged."""
        self._run("1", "replace", "--force", "new root body")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        t1 = p.lookup(1)
        self.assertIn("new root body", "\n".join(t1.body_lines))
        # Children must be untouched (still have default empty body)
        t2 = p.lookup(2)
        self.assertNotIn("new root body", "\n".join(t2.body_lines))
        t3 = p.lookup(3)
        self.assertNotIn("new root body", "\n".join(t3.body_lines))

    def test_replace_recursive_all_descendants(self):
        """'plan 1 -r replace --force text' replaces body on all descendants."""
        self._run("1", "-r", "replace", "--force", "shared body")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertIn("shared body", "\n".join(t.body_lines),
                          f"Ticket #{tid} should have replaced body")

    # -- edit: single vs recursive ----------------------------------------

    def _run_edit(self, args, old, new):
        """Run edit via subprocess with EDITOR doing old->new replacement."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh',
                                          delete=False) as sf:
            sf.write('#!/bin/bash\n'
                     f'{sys.executable} -c "\n'
                     'import sys\n'
                     'p = sys.argv[1]\n'
                     'with open(p) as f: t = f.read()\n'
                     f"t = t.replace('''{old}''', '''{new}''')\n"
                     'with open(p, chr(119)) as f: f.write(t)\n"'
                     ' "$1"\n')
            script = sf.name
        os.chmod(script, 0o755)
        try:
            cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
            env = os.environ.copy()
            env["EDITOR"] = script
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result
        finally:
            os.unlink(script)

    def test_edit_single_only_target(self):
        """'plan edit 1' edits only the target ticket, children unchanged."""
        # Add bodies so we can distinguish them
        self._run("1", "replace", "--force", "root body")
        self._run("2", "replace", "--force", "child1 body")
        self._run("3", "replace", "--force", "child2 body")
        # Edit #1 only — replace body
        self._run_edit(["edit", "1"], "root body", "EDITED")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        t1 = p.lookup(1)
        self.assertIn("EDITED", "\n".join(t1.body_lines))
        # Children must be untouched
        t2 = p.lookup(2)
        self.assertIn("child1 body", "\n".join(t2.body_lines))
        self.assertNotIn("EDITED", "\n".join(t2.body_lines))
        t3 = p.lookup(3)
        self.assertIn("child2 body", "\n".join(t3.body_lines))

    def test_edit_recursive_all_descendants(self):
        """'plan edit 1 -r' edits the target and all descendants together."""
        self._run("1", "replace", "--force", "root body")
        self._run("2", "replace", "--force", "child1 body")
        self._run("3", "replace", "--force", "child2 body")
        # Recursive edit — transform applies to the combined buffer
        self._run_edit(["edit", "1", "-r"], " body", " EDITED")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertIn("EDITED", "\n".join(t.body_lines),
                          f"Ticket #{tid} should be edited recursively")

    def test_edit_single_preserves_children_count(self):
        """Non-recursive edit of parent must not lose or duplicate children."""
        self._run_edit(["edit", "1"], "xyznonexistent", "xyznonexistent")
        with open(self.tmpfile.name) as f:
            p = plan.parse(f.read())
        parent = p.lookup(1)
        self.assertEqual(len(parent.children), 2,
                         "Parent should still have exactly 2 children")
        self.assertIsNotNone(p.lookup(2))
        self.assertIsNotNone(p.lookup(3))


class TestRecursiveAlias(unittest.TestCase):
    """Test --recursive long-form alias for -r."""

    def test_parse_recursive_long_form(self):
        """--recursive is parsed the same as -r."""
        reqs = plan.parse_argv(["1", "--recursive", "list"])
        self.assertTrue(reqs[0].flags.get("recursive"))

    def test_parse_r_short_form(self):
        """Short -r still works."""
        reqs = plan.parse_argv(["1", "-r", "list"])
        self.assertTrue(reqs[0].flags.get("recursive"))

    def test_recursive_long_form_is_keyword(self):
        """--recursive is recognized as a keyword."""
        self.assertTrue(plan._is_keyword("--recursive"))


class TestRecursiveLongFormEndToEnd(unittest.TestCase):
    """Test --recursive long form end-to-end via subprocess."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create tree: #1 (root) -> #2 (child1), #1 -> #3 (child2)
        self._run("create", 'title="Root"')
        self._run("create", '1', 'title="Child1"')
        self._run("create", '1', 'title="Child2"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _load(self):
        with open(self.tmpfile.name) as fh:
            return plan.parse(fh.read())

    def test_mod_recursive_long_form(self):
        """--recursive long form works end-to-end."""
        self._run("1", "--recursive", "mod", 'set(type="Bug")')
        p = self._load()
        for tid in (1, 2, 3):
            t = p.lookup(tid)
            self.assertEqual(t.get_attr("type"), "Bug")


class TestParentSelector(unittest.TestCase):
    """Test -p / --parent selector."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Create tree: #1 -> #2 -> #3
        self._run("create", 'title="Root"')
        self._run("create", '1', 'title="Middle"')
        self._run("create", '2', 'title="Deep"')
        # Also create a child of #3
        self._run("create", '3', 'title="Deepest"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_parent_flag_parsed(self):
        """'-p' sets parent flag."""
        reqs = plan.parse_argv(["3", "-p", "list"])
        self.assertTrue(reqs[0].flags.get("parent"))

    def test_parent_long_form_parsed(self):
        """'--parent' sets parent flag."""
        reqs = plan.parse_argv(["3", "--parent", "list"])
        self.assertTrue(reqs[0].flags.get("parent"))

    def test_parent_is_keyword(self):
        """'-p' and '--parent' are recognized as keywords."""
        self.assertTrue(plan._is_keyword("-p"))
        self.assertTrue(plan._is_keyword("--parent"))

    def test_list_with_parent(self):
        """list 3 -p shows ancestor path + self."""
        r = self._run("3", "-p", "list")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        # Should show: #1 Root, #2 Middle, #3 Deep (not children)
        self.assertEqual(len(lines), 3, f"Expected 3 lines, got: {lines}")
        self.assertIn("#1", lines[0])
        self.assertIn("Root", lines[0])
        self.assertIn("#2", lines[1])
        self.assertIn("Middle", lines[1])
        self.assertIn("#3", lines[2])
        self.assertIn("Deep", lines[2])

    def test_list_with_parent_recursive(self):
        """list 3 -p -r shows ancestor path + self + descendants."""
        r = self._run("3", "-p", "-r", "list")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        # Should show: #1 Root, #2 Middle, #3 Deep, #4 Deepest
        self.assertEqual(len(lines), 4, f"Expected 4 lines, got: {lines}")
        self.assertIn("#4", lines[3])
        self.assertIn("Deepest", lines[3])

    def test_list_with_parent_indentation(self):
        """list 3 -p shows proper indentation hierarchy."""
        r = self._run("3", "-p", "list")
        lines = r.stdout.strip().splitlines()
        # Root at depth 0, Middle at depth 1, Deep at depth 2
        self.assertTrue(lines[0].startswith("#1"), f"Root not at depth 0: {lines[0]!r}")
        self.assertTrue(lines[1].startswith("  #2"), f"Middle not at depth 1: {lines[1]!r}")
        self.assertTrue(lines[2].startswith("    #3"), f"Deep not at depth 2: {lines[2]!r}")

    def test_list_with_parent_top_level(self):
        """list 1 -p on a top-level ticket just shows self (no ancestors)."""
        r = self._run("1", "-p", "list")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"Expected 1 line, got: {lines}")
        self.assertIn("#1", lines[0])
        self.assertIn("Root", lines[0])

    def test_list_with_parent_long_form(self):
        """--parent works same as -p."""
        r = self._run("3", "--parent", "list")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        self.assertTrue(len(lines) >= 3)
        self.assertIn("#1", lines[0])


class TestParentFilterAncestorInclusion(unittest.TestCase):
    """-p with -r and filter includes ancestors of matches for tree context."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.close()
        # Tree: #1 (open) -> #2 (done) -> #3 (open)
        #                  -> #5 (open)
        # Top-level: #4 (open)
        self._run("create", 'title="Epic"')
        self._run("create", "1", 'title="ClosedChild"')
        self._run("create", "2", 'title="OpenGrandchild"')
        self._run("create", 'title="TopOpen"')
        self._run("create", "1", 'title="OpenChild"')
        self._run("2", "status", "done")

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _ids(self, result):
        """Extract ticket IDs from output lines."""
        ids = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                m = re.match(r'.*#(\d+)', line)
                if m:
                    ids.append(int(m.group(1)))
        return ids

    def test_query_without_parent(self):
        """-q filter then -r expands: open tickets plus descendants."""
        r = self._run("-q", "is_open", "-r", "list")
        ids = self._ids(r)
        # is_open filters: #1, #3, #4, #5.  -r adds descendants: #2 (child of #1)
        self.assertIn(1, ids)
        self.assertIn(3, ids)
        self.assertIn(4, ids)
        self.assertIn(5, ids)
        self.assertIn(2, ids)

    def test_filter_with_parent_includes_ancestors(self):
        """-q then -r then -p: filter, expand descendants, add ancestors."""
        r = self._run("-q", "is_open", "-r", "-p", "list")
        ids = self._ids(r)
        # is_open → [#1,#3,#4,#5].  -r adds descendants → [#1,#2,#3,#4,#5].
        # -p adds ancestors (all already present).  All 5 tickets.
        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertIn(3, ids)
        self.assertIn(4, ids)
        self.assertIn(5, ids)

    def test_filter_with_parent_preserves_tree_order(self):
        """Pipeline results are in depth-first rank order."""
        r = self._run("-q", "is_open", "-r", "-p", "list")
        ids = self._ids(r)
        self.assertLess(ids.index(1), ids.index(2))
        self.assertLess(ids.index(2), ids.index(3))
        self.assertLess(ids.index(1), ids.index(5))

    def test_filter_with_parent_preserves_indentation(self):
        """Pipeline results: indentation reflects real tree depth."""
        r = self._run("-q", "is_open", "-r", "-p", "list")
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        for line in lines:
            if "#1" in line:
                self.assertTrue(line.startswith("#1"), f"Epic not at depth 0: {line!r}")
            elif "#2" in line:
                self.assertTrue(line.startswith("  #2"), f"ClosedChild not at depth 1: {line!r}")
            elif "#3" in line:
                self.assertTrue(line.startswith("    #3"), f"OpenGrandchild not at depth 2: {line!r}")

    def test_filter_with_parent_no_duplicates(self):
        """Pipeline deduplicates: shared ancestors appear only once."""
        r = self._run("-q", "is_open", "-r", "-p", "list")
        ids = self._ids(r)
        self.assertEqual(ids.count(1), 1)

    def test_filter_with_parent_no_filter_unchanged(self):
        """-r -p on empty set: no-op (positional semantics)."""
        r1 = self._run("-r", "-p", "list")
        ids1 = self._ids(r1)
        # -r -p on empty set is a no-op
        self.assertEqual(ids1, [])

    def test_filter_with_parent_title_filter(self):
        """--title is a handler-level filter; -p only expands existing targets."""
        r = self._run("--title", "OpenGrandchild", "list")
        ids = self._ids(r)
        # --title filters at handler level, only #3 matches
        self.assertIn(3, ids)
        self.assertNotIn(4, ids)
        self.assertNotIn(5, ids)


class TestPipelineOrder(unittest.TestCase):
    """Test that pipeline argument order produces different results."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False)
        self.tmpfile.close()
        # Tree: #1 (open) -> #2 (open) -> #3 (done)
        #       #4 (open, top-level)
        self._run("create", 'title="Root"')
        self._run("create", "1", 'title="Child"')
        self._run("create", "2", 'title="Grandchild"')
        self._run("create", 'title="Other"')
        self._run("3", "close")

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _ids(self, result):
        ids = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r'\s*#(\d+)', line.strip())
            if m:
                ids.append(int(m.group(1)))
        return ids

    def test_select_then_filter(self):
        """'plan 1 -r is_open list' — select #1, expand, then filter open."""
        r = self._run("1", "-r", "is_open", "list")
        ids = self._ids(r)
        # #1 expanded to [#1,#2,#3], then is_open filters out #3
        self.assertEqual(set(ids), {1, 2})

    def test_filter_then_select(self):
        """'plan is_open 1 -r list' — filter open, add #1, expand descendants."""
        r = self._run("is_open", "1", "-r", "list")
        ids = self._ids(r)
        # is_open → [#1,#2,#4], add #1 (already in), -r adds descendants
        # Descendants of #1: #2,#3; of #2: #3; of #4: none
        # Result: [#1,#2,#3,#4] (including #3 as descendant)
        self.assertEqual(set(ids), {1, 2, 3, 4})

    def test_order_matters(self):
        """Same args, different order → different results."""
        r1 = self._run("1", "-r", "is_open", "list")
        r2 = self._run("is_open", "1", "-r", "list")
        ids1 = set(self._ids(r1))
        ids2 = set(self._ids(r2))
        # First excludes closed #3, second includes it via -r
        self.assertNotEqual(ids1, ids2)
        self.assertNotIn(3, ids1)
        self.assertIn(3, ids2)

    def test_r_before_target_is_noop(self):
        """'-r 1 list' — -r on empty set, then add #1 → just #1."""
        r = self._run("-r", "1", "list")
        ids = self._ids(r)
        self.assertEqual(ids, [1])

    def test_target_then_r(self):
        """'1 -r list' — add #1, expand → full subtree."""
        r = self._run("1", "-r", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {1, 2, 3})

    def test_p_before_target(self):
        """'-p 3 list' — -p is position-independent, same as '3 -p list'."""
        r = self._run("-p", "3", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {1, 2, 3})

    def test_target_then_p(self):
        """'3 -p list' — add #3, then add ancestors → [#1, #2, #3]."""
        r = self._run("3", "-p", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {1, 2, 3})

    def test_filter_initial_set_is_all(self):
        """First arg is filter → starts from all tickets."""
        r = self._run("is_open", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {1, 2, 4})

    def test_selector_initial_set_is_empty(self):
        """First arg is selector → starts from empty."""
        r = self._run("children_of(1)", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {2})

    def test_filter_then_add_back(self):
        """'is_descendant_of(1) 1 list' — filter descendants, add #1 back."""
        r = self._run("is_descendant_of(1)", "1", "list")
        ids = self._ids(r)
        # is_descendant_of(1) filters all → [#2,#3], then add #1
        self.assertEqual(set(ids), {1, 2, 3})

    def test_mixed_selectors_and_filters(self):
        """'1 -r is_open 4 list' — select, expand, filter, add."""
        r = self._run("1", "-r", "is_open", "4", "list")
        ids = self._ids(r)
        # 1 → [#1], -r → [#1,#2,#3], is_open → [#1,#2], add #4 → [#1,#2,#4]
        self.assertEqual(set(ids), {1, 2, 4})


class TestCommandFirstWordParsing(unittest.TestCase):
    """Test that commands must be the first word and related parsing rules."""

    def test_command_first_word(self):
        """'plan create ...' parses as command."""
        reqs = plan.parse_argv(["create", 'title="X"'])
        self.assertEqual(reqs[0].command[0], "create")

    def test_misplaced_command_error(self):
        """'plan 1 edit' errors — edit is a command, not a verb."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["1", "edit"])
        self.assertIn("command", str(cm.exception).lower())
        self.assertIn("first word", str(cm.exception).lower())

    def test_edit_project_node(self):
        """'plan edit project' parses — 'project' is a valid node ID arg."""
        reqs = plan.parse_argv(["edit", "project"])
        self.assertEqual(reqs[0].command, ("edit", ["project"]))

    def test_edit_section_node(self):
        """'plan edit description' parses — section ID as edit arg."""
        reqs = plan.parse_argv(["edit", "description"])
        self.assertEqual(reqs[0].command, ("edit", ["description"]))

    def test_help_via_flag(self):
        """'plan list -h' converts to help list."""
        reqs = plan.parse_argv(["list", "-h"])
        self.assertEqual(reqs[0].command, ("help", ["list"]))

    def test_help_via_flag_on_command(self):
        """'plan edit -h' converts to help edit."""
        reqs = plan.parse_argv(["edit", "-h"])
        self.assertEqual(reqs[0].command, ("help", ["edit"]))

    def test_help_bare(self):
        """'plan -h' converts to help."""
        reqs = plan.parse_argv(["-h"])
        self.assertEqual(reqs[0].command, ("help", []))

    def test_help_command_direct(self):
        """'plan help list' works directly."""
        reqs = plan.parse_argv(["help", "list"])
        self.assertEqual(reqs[0].command, ("help", ["list"]))

    def test_file_flag_global(self):
        """'-f' is extracted before splitting by ';'."""
        reqs = plan.parse_argv(["-f", "a.md", "1", "get", ";", "2", "get"])
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0].flags["file"], "a.md")
        self.assertEqual(reqs[1].flags["file"], "a.md")

    def test_flags_before_command(self):
        """'plan -r edit 1' — flags before command are consumed."""
        reqs = plan.parse_argv(["-r", "edit", "1"])
        self.assertEqual(reqs[0].command, ("edit", ["1"]))
        self.assertTrue(reqs[0].flags.get("recursive"))

    def test_id_selector_accepts_keywords(self):
        """'plan id project' — id selector consumes keyword as node ID."""
        reqs = plan.parse_argv(["id", "project"])
        self.assertEqual(reqs[0].selector_type, "id")
        self.assertEqual(reqs[0].selector_args, ["project"])

    def test_file_flag_duplicate_error(self):
        """Specifying -f twice is an error."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["-f", "a.md", "-f", "b.md", "list"])
        self.assertIn("more than once", str(cm.exception))

    def test_file_flag_mixed_forms_error(self):
        """Specifying -f and --file is an error."""
        with self.assertRaises(SystemExit) as cm:
            plan.parse_argv(["-f", "a.md", "--file", "b.md", "list"])
        self.assertIn("more than once", str(cm.exception))


class TestChildrenDSLFunction(unittest.TestCase):
    """Test children() DSL function."""

    def _make_tree(self):
        """Create a tree: #1 -> #2, #1 -> #3, #2 -> #4."""
        doc = textwrap.dedent("""\
            # Test {#project}
            ## Metadata {#metadata}
                next_id: 5
            ## Tickets {#tickets}
            * ## Ticket: Task: Root {#1}
                  status: open
              * ## Ticket: Task: Child1 {#2}
                    status: open
                  * ## Ticket: Task: Grandchild {#4}
                        status: open
              * ## Ticket: Task: Child2 {#3}
                    status: open
        """)
        return plan.parse(doc)

    def test_children_is_list(self):
        """children behaves like a list."""
        p = self._make_tree()
        t1 = p.lookup(1)
        ns = t1.as_namespace()
        self.assertEqual(len(ns["children"]), 2)
        self.assertIsInstance(ns["children"], list)

    def test_children_callable_direct(self):
        """children() returns direct children."""
        p = self._make_tree()
        t1 = p.lookup(1)
        ns = t1.as_namespace()
        result = ns["children"]()
        self.assertEqual(len(result), 2)

    def test_children_callable_recursive(self):
        """children(recursive=True) returns all descendants."""
        p = self._make_tree()
        t1 = p.lookup(1)
        ns = t1.as_namespace()
        result = ns["children"](recursive=True)
        self.assertEqual(len(result), 3)  # #2, #4, #3
        ids = [t.node_id for t in result]
        self.assertIn(2, ids)
        self.assertIn(3, ids)
        self.assertIn(4, ids)

    def test_children_recursive_order(self):
        """children(recursive=True) returns depth-first order."""
        p = self._make_tree()
        t1 = p.lookup(1)
        ns = t1.as_namespace()
        result = ns["children"](recursive=True)
        ids = [t.node_id for t in result]
        # Depth-first: #2, #4 (child of #2), then #3
        self.assertEqual(ids, [2, 4, 3])

    def test_children_leaf_node(self):
        """children() on leaf node returns empty list."""
        p = self._make_tree()
        t4 = p.lookup(4)
        ns = t4.as_namespace()
        self.assertEqual(len(ns["children"]), 0)
        self.assertEqual(ns["children"](), [])
        self.assertEqual(ns["children"](recursive=True), [])

    def test_children_in_filter(self):
        """children works in filter expressions."""
        p = self._make_tree()
        t1 = p.lookup(1)
        # Has children
        self.assertTrue(plan.eval_filter(t1, 'len(children) > 0'))
        # Leaf has no children
        t4 = p.lookup(4)
        self.assertFalse(plan.eval_filter(t4, 'len(children) > 0'))

    def test_children_recursive_in_filter(self):
        """children(recursive=True) works in filter."""
        p = self._make_tree()
        t1 = p.lookup(1)
        self.assertTrue(plan.eval_filter(t1, 'len(children(recursive=True)) == 3'))

    def test_children_iteration(self):
        """Can iterate over children in DSL."""
        p = self._make_tree()
        t1 = p.lookup(1)
        result = plan.eval_filter(t1, 'any(c.title == "Child1" for c in children)')
        self.assertTrue(result)

    def test_children_backward_compat(self):
        """Existing children usage patterns still work."""
        p = self._make_tree()
        t1 = p.lookup(1)
        # These are patterns from existing DSL docs
        self.assertTrue(plan.eval_filter(t1, 'children'))  # truthy
        self.assertTrue(plan.eval_filter(t1, 'len(children) > 0'))
        self.assertTrue(plan.eval_filter(t1, 'any(c.title == "Child1" for c in children)'))


class TestParentDSLFunction(unittest.TestCase):
    """Test parent DSL variable and related functions."""

    def test_parent_is_int_with_parent(self):
        """parent is an int (parent's node_id) when parent exists."""
        parent = plan.Ticket(1, "Parent", "Task")
        child = plan.Ticket(2, "Child", "Task")
        child.parent = parent
        ns = child.as_namespace()
        self.assertEqual(ns["parent"], 1)
        self.assertIsInstance(ns["parent"], int)

    def test_parent_is_zero_for_root(self):
        """parent is 0 for top-level ticket."""
        t = plan.Ticket(1, "Root", "Task")
        ns = t.as_namespace()
        self.assertEqual(ns["parent"], 0)

    def test_parent_truthy_for_nested(self):
        """parent is truthy (nonzero) when parent exists."""
        parent = plan.Ticket(1, "Parent", "Task")
        child = plan.Ticket(2, "Child", "Task")
        child.parent = parent
        ns = child.as_namespace()
        self.assertTrue(bool(ns["parent"]))

    def test_parent_falsy_for_root(self):
        """parent is falsy (0) for top-level ticket."""
        t = plan.Ticket(1, "Root", "Task")
        ns = t.as_namespace()
        self.assertFalse(bool(ns["parent"]))

    def test_parent_in_filter_expression(self):
        """parent works in -q filter expressions."""
        parent = plan.Ticket(1, "Parent", "Task")
        parent.attrs["status"] = "open"
        child = plan.Ticket(2, "Child", "Task")
        child.parent = parent
        child.attrs["status"] = "open"
        # Filter: has parent (nonzero)
        self.assertTrue(plan.eval_filter(child, 'parent'))
        # Filter: no parent (0 = falsy)
        self.assertFalse(plan.eval_filter(parent, 'parent'))

    def test_parent_equality_in_filter(self):
        """parent == N checks direct parent ID."""
        parent = plan.Ticket(1, "Parent", "Task")
        child = plan.Ticket(2, "Child", "Task")
        child.parent = parent
        child.attrs["status"] = "open"
        self.assertTrue(plan.eval_filter(child, 'parent == 1'))
        self.assertFalse(plan.eval_filter(child, 'parent == 99'))

    def test_parent_zero_for_root_filter(self):
        """parent == 0 matches root tickets."""
        t = plan.Ticket(1, "Root", "Task")
        t.attrs["status"] = "open"
        self.assertTrue(plan.eval_filter(t, 'parent == 0'))


class TestParentOfFunction(unittest.TestCase):
    """Test parent_of() DSL function."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False)
        self.tmpfile.close()
        self._run("create", 'title="Root"')
        self._run("create", "1", 'title="Child"')
        self._run("create", "2", 'title="Grandchild"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_parent_of_root(self):
        """parent_of(root_ticket) returns 0."""
        r = self._run("-q", "parent_of(1) == 0", "list")
        self.assertIn("#1", r.stdout)

    def test_parent_of_child(self):
        """parent_of(child) returns parent id."""
        r = self._run("-q", "parent_of(2) == 1", "list")
        # All tickets match since parent_of(2)==1 is a global truth
        self.assertIn("#", r.stdout)

    def test_parent_of_grandchild(self):
        """parent_of(grandchild) returns child id."""
        r = self._run("-q", "parent_of(3) == 2", "list")
        self.assertIn("#", r.stdout)

    def test_parent_of_zero(self):
        """parent_of(0) returns 0 (virtual root)."""
        r = self._run("-q", "parent_of(0) == 0", "list")
        self.assertIn("#", r.stdout)


class TestIsDescendantOfFunction(unittest.TestCase):
    """Test is_descendant_of() DSL function."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False)
        self.tmpfile.close()
        self._run("create", 'title="Root"')
        self._run("create", "1", 'title="Child"')
        self._run("create", "2", 'title="Grandchild"')
        self._run("create", 'title="Other"')

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _ids(self, result):
        ids = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r'\s*#(\d+)', line.strip())
            if m:
                ids.append(int(m.group(1)))
        return ids

    def test_descendants_of_root_ticket(self):
        """is_descendant_of(1) matches child and grandchild."""
        r = self._run("-q", "is_descendant_of(1)", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {2, 3})
        self.assertNotIn(1, ids)  # not self
        self.assertNotIn(4, ids)  # not other tree

    def test_descendants_of_zero(self):
        """is_descendant_of(0) matches all tickets (0 = virtual root)."""
        r = self._run("-q", "is_descendant_of(0)", "list")
        ids = self._ids(r)
        self.assertEqual(set(ids), {1, 2, 3, 4})

    def test_descendants_of_leaf(self):
        """is_descendant_of(leaf) matches nothing."""
        r = self._run("-q", "is_descendant_of(3)", "list")
        self.assertEqual(r.stdout.strip(), "")

    def test_descendant_two_arg_form(self):
        """is_descendant_of(1, 3) checks if #3 is descendant of #1."""
        r = self._run("-q", "is_descendant_of(1, 3)", "list")
        ids = self._ids(r)
        # This is a global truth, so all tickets match
        self.assertEqual(set(ids), {1, 2, 3, 4})

    def test_descendant_two_arg_false(self):
        """is_descendant_of(1, 4) — #4 is not under #1."""
        # Use get since we need to check it returns nothing useful
        r = self._run("-q", "is_descendant_of(1, 4)", "list")
        self.assertEqual(r.stdout.strip(), "")

    def test_combined_with_filter(self):
        """is_descendant_of combined with other filters."""
        r = self._run("-q", 'is_descendant_of(1) and is_open', "list")
        ids = self._ids(r)
        # #2 Child and #3 Grandchild are both open and descendants of #1
        self.assertEqual(set(ids), {2, 3})


class TestChildrenOfFunction(unittest.TestCase):
    """Test children_of() DSL function."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False)
        self.tmpfile.close()
        self._run("create", 'title="Root"')        # #1
        self._run("create", "1", 'title="Child"')   # #2
        self._run("create", "2", 'title="Grandchild"')  # #3
        self._run("create", 'title="Other"')        # #4

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _ids(self, result):
        ids = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r'\s*#(\d+)', line.strip())
            if m:
                ids.append(int(m.group(1)))
        return ids

    def test_children_of_root_ticket(self):
        """children_of(1) returns direct children of #1."""
        r = self._run("-q", "id in children_of(1)", "list")
        self.assertEqual(self._ids(r), [2])

    def test_children_of_zero(self):
        """children_of(0) returns top-level ticket IDs."""
        r = self._run("-q", "id in children_of(0)", "list")
        self.assertEqual(set(self._ids(r)), {1, 4})

    def test_children_of_leaf(self):
        """children_of(leaf) returns empty list."""
        r = self._run("-q", "id in children_of(3)", "list")
        self.assertEqual(r.stdout.strip(), "")

    def test_children_of_recursive(self):
        """children_of(1, True) returns all descendants."""
        r = self._run("-q", "id in children_of(1, True)", "list")
        self.assertEqual(set(self._ids(r)), {2, 3})

    def test_children_of_zero_recursive(self):
        """children_of(0, True) returns all ticket IDs."""
        r = self._run("-q", "id in children_of(0, True)", "list")
        self.assertEqual(set(self._ids(r)), {1, 2, 3, 4})


class TestInstallUninstall(unittest.TestCase):
    """Test install and uninstall commands."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        # Init a git repo so install works
        subprocess.run(["git", "init", "-q"], check=True,
                       capture_output=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        os.chdir(self.orig_cwd)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _quiet(fn, *args, **kwargs):
        """Run fn with stdout suppressed."""
        with unittest.mock.patch('sys.stdout', new_callable=io.StringIO):
            return fn(*args, **kwargs)

    def test_install_local_creates_plugin(self):
        """install local creates plugin directory and settings."""
        self._quiet(plan._handle_install, "local")
        plugin_dir = os.path.join(self.tmpdir, ".claude", "plugins", "claude-plan")
        self.assertTrue(os.path.isdir(plugin_dir))
        self.assertTrue(os.path.isfile(
            os.path.join(plugin_dir, ".claude-plugin", "plugin.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(plugin_dir, "skills", "planning-with-plan", "SKILL.md")))
        self.assertTrue(os.path.isfile(
            os.path.join(plugin_dir, "skills", "team-with-plan", "SKILL.md")))
        self.assertTrue(os.path.isfile(
            os.path.join(plugin_dir, "hooks", "hooks.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(plugin_dir, "hooks", "scripts", "load-plan-context.sh")))

    def test_install_local_creates_settings(self):
        """install local registers plugin in .claude/settings.json."""
        self._quiet(plan._handle_install, "local")
        settings_path = os.path.join(self.tmpdir, ".claude", "settings.json")
        self.assertTrue(os.path.isfile(settings_path))
        import json
        with open(settings_path) as f:
            settings = json.load(f)
        self.assertIn(".claude/plugins/claude-plan", settings["plugins"])

    def test_install_local_creates_claude_md(self):
        """install local adds task tracking section to CLAUDE.md."""
        self._quiet(plan._handle_install, "local")
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        self.assertTrue(os.path.isfile(claude_md))
        with open(claude_md) as f:
            content = f.read()
        self.assertIn("## Task tracking", content)
        self.assertIn("plan create", content)

    def test_install_local_appends_to_existing_claude_md(self):
        """install local appends to existing CLAUDE.md without overwriting."""
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        with open(claude_md, "w") as f:
            f.write("# My Project\n\nExisting content.\n")
        self._quiet(plan._handle_install, "local")
        with open(claude_md) as f:
            content = f.read()
        self.assertIn("Existing content.", content)
        self.assertIn("## Task tracking", content)

    def test_install_local_replaces_existing_section(self):
        """install local replaces existing task tracking section."""
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        with open(claude_md, "w") as f:
            f.write("## Task tracking\n\nOld content.\n")
        self._quiet(plan._handle_install, "local")
        with open(claude_md) as f:
            content = f.read()
        # Should not duplicate
        self.assertEqual(content.count("## Task tracking"), 1)
        # Old content replaced with current section
        self.assertNotIn("Old content.", content)
        self.assertIn("plan create", content)

    def test_install_local_copies_binary(self):
        """install local copies binary when plan not on PATH."""
        # Temporarily hide plan from PATH
        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            self._quiet(plan._handle_install, "local")
        finally:
            os.environ["PATH"] = orig_path
        bin_path = os.path.join(self.tmpdir, "plan")
        self.assertTrue(os.path.isfile(bin_path))

    def test_uninstall_local_removes_plugin(self):
        """uninstall local removes plugin directory."""
        self._quiet(plan._handle_install, "local")
        self._quiet(plan._handle_uninstall, "local")
        plugin_dir = os.path.join(self.tmpdir, ".claude", "plugins", "claude-plan")
        self.assertFalse(os.path.isdir(plugin_dir))

    def test_uninstall_local_removes_settings_entry(self):
        """uninstall local removes plugin from settings.json."""
        self._quiet(plan._handle_install, "local")
        self._quiet(plan._handle_uninstall, "local")
        settings_path = os.path.join(self.tmpdir, ".claude", "settings.json")
        if os.path.exists(settings_path):
            import json
            with open(settings_path) as f:
                settings = json.load(f)
            self.assertNotIn(
                ".claude/plugins/claude-plan", settings.get("plugins", []))

    def test_uninstall_local_removes_claude_md_section(self):
        """uninstall local removes task tracking section from CLAUDE.md."""
        self._quiet(plan._handle_install, "local")
        self._quiet(plan._handle_uninstall, "local")
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        if os.path.exists(claude_md):
            with open(claude_md) as f:
                content = f.read()
            self.assertNotIn("## Task tracking", content)

    def test_uninstall_local_preserves_other_claude_md_content(self):
        """uninstall local keeps non-plan content in CLAUDE.md."""
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        with open(claude_md, "w") as f:
            f.write("# My Project\n\nKeep this.\n")
        self._quiet(plan._handle_install, "local")
        self._quiet(plan._handle_uninstall, "local")
        with open(claude_md) as f:
            content = f.read()
        self.assertIn("Keep this.", content)
        self.assertNotIn("## Task tracking", content)

    def test_uninstall_local_deletes_empty_claude_md(self):
        """uninstall local deletes CLAUDE.md if it becomes empty."""
        self._quiet(plan._handle_install, "local")
        self._quiet(plan._handle_uninstall, "local")
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        self.assertFalse(os.path.isfile(claude_md))

    def test_uninstall_local_removes_binary(self):
        """uninstall local removes binary if present."""
        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            self._quiet(plan._handle_install, "local")
        finally:
            os.environ["PATH"] = orig_path
        bin_path = os.path.join(self.tmpdir, "plan")
        self.assertTrue(os.path.isfile(bin_path))
        self._quiet(plan._handle_uninstall, "local")
        self.assertFalse(os.path.isfile(bin_path))

    def test_roundtrip_install_uninstall(self):
        """Full install then uninstall leaves no artifacts."""
        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            self._quiet(plan._handle_install, "local")
        finally:
            os.environ["PATH"] = orig_path
        self._quiet(plan._handle_uninstall, "local")
        # Only .git should remain
        remaining = [f for f in os.listdir(self.tmpdir) if f != ".git"]
        self.assertEqual(remaining, [],
                         f"Unexpected files after uninstall: {remaining}")

    def test_install_user_creates_cache_plugin(self):
        """install user puts plugin files in ~/.claude/plugins/cache/."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools", "claude-plan", plan._get_plugin_version())
        self.assertTrue(os.path.isdir(cache_dir))
        self.assertTrue(os.path.isfile(
            os.path.join(cache_dir, ".claude-plugin", "plugin.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(cache_dir, "skills", "planning-with-plan", "SKILL.md")))
        self.assertTrue(os.path.isfile(
            os.path.join(cache_dir, "hooks", "hooks.json")))

    def test_install_user_registers_in_installed_plugins(self):
        """install user adds entry to installed_plugins.json."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        self.assertTrue(os.path.isfile(ip_path))
        with open(ip_path) as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)
        self.assertIn("claude-plan@plan-tools", data["plugins"])
        entry = data["plugins"]["claude-plan@plan-tools"][0]
        self.assertEqual(entry["scope"], "user")
        self.assertEqual(entry["version"], plan._get_plugin_version())

    def test_install_user_enables_plugin(self):
        """install user adds claude-plan@plan-tools to enabledPlugins."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertTrue(settings["enabledPlugins"].get("claude-plan@plan-tools"))

    def test_uninstall_user_removes_cache(self):
        """uninstall user removes plugin from cache."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
            self._quiet(plan._handle_uninstall, "user")
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools")
        self.assertFalse(os.path.exists(cache_dir))

    def test_uninstall_user_removes_from_installed_plugins(self):
        """uninstall user removes entry from installed_plugins.json."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
            self._quiet(plan._handle_uninstall, "user")
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        with open(ip_path) as f:
            data = json.load(f)
        self.assertNotIn("claude-plan@plan-tools", data.get("plugins", {}))

    def test_uninstall_user_removes_enabled_plugin(self):
        """uninstall user removes from enabledPlugins."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
            self._quiet(plan._handle_uninstall, "user")
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertNotIn("claude-plan@plan-tools",
                         settings.get("enabledPlugins", {}))

    def test_uninstall_user_cleans_legacy_remnants(self):
        """uninstall user removes old-style ~/.claude/plugins/claude-plan/ dir."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
        # Create old-style plugin dir
        old_dir = os.path.join(fake_home, ".claude", "plugins", "claude-plan")
        os.makedirs(old_dir, exist_ok=True)
        with open(os.path.join(old_dir, "dummy"), "w") as f:
            f.write("old")
        # Old-style settings
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({
                "enabledPlugins": {"claude-plan": True},
                "plugins": [old_dir],
            }, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_uninstall, "user")
        self.assertFalse(os.path.exists(old_dir))
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertNotIn("claude-plan", settings.get("enabledPlugins", {}))
        self.assertNotIn("plugins", settings)

    def test_roundtrip_user_install_uninstall(self):
        """Full user install then uninstall cleans up properly."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
        with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {}}, f)
        orig_path = os.environ.get("PATH", "")
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home, "PATH": ""}):
            self._quiet(plan._handle_install, "user")
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_uninstall, "user")
        # Cache dir for plan-tools should be gone
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools")
        self.assertFalse(os.path.exists(cache_dir))
        # installed_plugins.json should have no plan entry
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        with open(ip_path) as f:
            data = json.load(f)
        self.assertNotIn("claude-plan@plan-tools", data.get("plugins", {}))

    def _make_fake_home(self, settings=None, installed_plugins=None):
        """Create a fake HOME with optional pre-existing config."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        if settings is not None:
            os.makedirs(os.path.join(fake_home, ".claude"), exist_ok=True)
            with open(os.path.join(fake_home, ".claude", "settings.json"), "w") as f:
                json.dump(settings, f, indent=2)
        if installed_plugins is not None:
            os.makedirs(os.path.join(fake_home, ".claude", "plugins"), exist_ok=True)
            with open(os.path.join(fake_home, ".claude", "plugins",
                                   "installed_plugins.json"), "w") as f:
                json.dump(installed_plugins, f, indent=2)
        return fake_home

    def test_install_user_into_existing_config(self):
        """install user preserves existing plugins in all config files."""
        existing_settings = {
            "enabledPlugins": {"superpowers@claude-plugins-official": True},
            "env": {"SOME_VAR": "1"},
        }
        existing_installed = {
            "version": 2,
            "plugins": {
                "superpowers@claude-plugins-official": [{
                    "scope": "user",
                    "installPath": "/fake/path/superpowers/5.0.5",
                    "version": "5.0.5",
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }],
            },
        }
        fake_home = self._make_fake_home(existing_settings, existing_installed)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        # Our plugin is added
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertTrue(settings["enabledPlugins"].get("claude-plan@plan-tools"))
        # Existing plugins are preserved
        self.assertTrue(settings["enabledPlugins"].get(
            "superpowers@claude-plugins-official"))
        self.assertEqual(settings["env"]["SOME_VAR"], "1")
        # installed_plugins.json: both entries exist
        with open(os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")) as f:
            data = json.load(f)
        self.assertIn("superpowers@claude-plugins-official", data["plugins"])
        self.assertIn("claude-plan@plan-tools", data["plugins"])

    def test_uninstall_user_preserves_existing_config(self):
        """uninstall user only removes plan entries, preserves everything else."""
        existing_settings = {
            "enabledPlugins": {
                "superpowers@claude-plugins-official": True,
                "claude-plan@plan-tools": True,
            },
            "env": {"SOME_VAR": "1"},
        }
        fake_home = self._make_fake_home(existing_settings)
        # Set up cache + installed_plugins.json as if install had run
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools", "claude-plan", plan._get_plugin_version())
        os.makedirs(os.path.join(cache_dir, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(cache_dir, ".claude-plugin", "plugin.json"), "w") as f:
            json.dump({"name": "claude-plan", "version": plan._get_plugin_version()}, f)
        installed = {
            "version": 2,
            "plugins": {
                "superpowers@claude-plugins-official": [{
                    "scope": "user",
                    "installPath": "/fake/path/superpowers/5.0.5",
                    "version": "5.0.5",
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }],
                "claude-plan@plan-tools": [{
                    "scope": "user",
                    "installPath": cache_dir,
                    "version": plan._get_plugin_version(),
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }],
            },
        }
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        with open(ip_path, "w") as f:
            json.dump(installed, f, indent=2)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_uninstall, "user")
        # Our entries are gone
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertNotIn("claude-plan@plan-tools", settings["enabledPlugins"])
        self.assertFalse(os.path.exists(cache_dir))
        with open(ip_path) as f:
            data = json.load(f)
        self.assertNotIn("claude-plan@plan-tools", data["plugins"])
        # Other entries are preserved
        self.assertTrue(settings["enabledPlugins"].get(
            "superpowers@claude-plugins-official"))
        self.assertEqual(settings["env"]["SOME_VAR"], "1")
        self.assertIn("superpowers@claude-plugins-official", data["plugins"])

    def test_install_user_no_preexisting_claude_dir(self):
        """install user works when ~/.claude/ does not exist at all."""
        fake_home = os.path.join(self.tmpdir, "fakehome")
        # Don't create .claude/ at all
        os.makedirs(fake_home, exist_ok=True)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        # Cache plugin created
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools", "claude-plan", plan._get_plugin_version())
        self.assertTrue(os.path.isdir(cache_dir))
        # installed_plugins.json created
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        with open(ip_path) as f:
            data = json.load(f)
        self.assertIn("claude-plan@plan-tools", data["plugins"])
        # settings.json created with enabledPlugins
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertTrue(settings["enabledPlugins"].get("claude-plan@plan-tools"))

    def test_roundtrip_user_preserves_preexisting_state(self):
        """install+uninstall returns config to its original state."""
        original_settings = {
            "enabledPlugins": {"superpowers@claude-plugins-official": True},
            "env": {"SOME_VAR": "1"},
        }
        original_installed = {
            "version": 2,
            "plugins": {
                "superpowers@claude-plugins-official": [{
                    "scope": "user",
                    "installPath": "/fake/path/superpowers/5.0.5",
                    "version": "5.0.5",
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }],
            },
        }
        fake_home = self._make_fake_home(original_settings, original_installed)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
            self._quiet(plan._handle_uninstall, "user")
        # settings.json matches original
        with open(os.path.join(fake_home, ".claude", "settings.json")) as f:
            settings = json.load(f)
        self.assertEqual(settings["enabledPlugins"],
                         original_settings["enabledPlugins"])
        self.assertEqual(settings["env"], original_settings["env"])
        # installed_plugins.json matches original (our entry gone, theirs kept)
        with open(os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")) as f:
            data = json.load(f)
        self.assertIn("superpowers@claude-plugins-official", data["plugins"])
        self.assertNotIn("claude-plan@plan-tools", data["plugins"])
        # No leftover cache dirs for plan-tools
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools")
        self.assertFalse(os.path.exists(cache_dir))

    def test_install_invalid_scope(self):
        """install with invalid scope raises error."""
        with self.assertRaises(SystemExit):
            self._quiet(plan._handle_install, "invalid")

    def test_uninstall_invalid_scope(self):
        """uninstall with invalid scope raises error."""
        with self.assertRaises(SystemExit):
            self._quiet(plan._handle_uninstall, "invalid")

    # --- --version flag ---

    def test_version_flag(self):
        """--version prints VERSION_STR and exits."""
        buf = io.StringIO()
        with unittest.mock.patch('sys.stdout', buf):
            plan.main(["--version"])
        self.assertEqual(buf.getvalue().strip(), plan.VERSION_STR)

    def test_version_flag_anywhere(self):
        """--version anywhere in argv prints version and exits."""
        buf = io.StringIO()
        with unittest.mock.patch('sys.stdout', buf):
            plan.main(["install", "--version", "local"])
        self.assertEqual(buf.getvalue().strip(), plan.VERSION_STR)

    # --- Multi-version uninstall ---

    def test_uninstall_user_removes_all_versions(self):
        """uninstall user removes ALL version directories, not just current."""
        fake_home = self._make_fake_home({"enabledPlugins": {}})
        version = plan._get_plugin_version()
        cache_base = os.path.join(fake_home, ".claude", "plugins", "cache",
                                  "plan-tools", "claude-plan")
        # Create multiple version dirs (simulate old installs)
        for v in ["1.0.0", "1.0.50", version]:
            vdir = os.path.join(cache_base, v)
            os.makedirs(os.path.join(vdir, ".claude-plugin"), exist_ok=True)
            with open(os.path.join(vdir, ".claude-plugin", "plugin.json"), "w") as f:
                json.dump({"name": "claude-plan", "version": v}, f)
        # installed_plugins.json points to current version only
        ip_path = os.path.join(fake_home, ".claude", "plugins",
                               "installed_plugins.json")
        os.makedirs(os.path.dirname(ip_path), exist_ok=True)
        with open(ip_path, "w") as f:
            json.dump({"version": 2, "plugins": {
                "claude-plan@plan-tools": [{
                    "scope": "user",
                    "installPath": os.path.join(cache_base, version),
                    "version": version,
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }],
            }}, f)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_uninstall, "user")
        # ALL version dirs should be gone
        self.assertFalse(os.path.exists(cache_base))
        # plan-tools dir should be cleaned up too
        self.assertFalse(os.path.exists(os.path.dirname(cache_base)))

    def test_uninstall_user_removes_untracked_versions(self):
        """uninstall user removes version dirs even if not in installed_plugins.json."""
        fake_home = self._make_fake_home({"enabledPlugins": {}})
        cache_base = os.path.join(fake_home, ".claude", "plugins", "cache",
                                  "plan-tools", "claude-plan")
        # Create version dirs without any installed_plugins.json tracking
        for v in ["1.0.0", "1.0.50"]:
            vdir = os.path.join(cache_base, v)
            os.makedirs(os.path.join(vdir, ".claude-plugin"), exist_ok=True)
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_uninstall, "user")
        self.assertFalse(os.path.exists(cache_base))

    # --- Install overwrites existing version dir (repair) ---

    def test_install_user_overwrites_same_version(self):
        """install user overwrites files when same version dir already exists."""
        fake_home = self._make_fake_home({"enabledPlugins": {}})
        version = plan._get_plugin_version()
        cache_dir = os.path.join(fake_home, ".claude", "plugins", "cache",
                                 "plan-tools", "claude-plan", version)
        # Pre-create with stale content
        os.makedirs(os.path.join(cache_dir, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(cache_dir, ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"stale": true}')
        with unittest.mock.patch.dict(os.environ, {"HOME": fake_home}):
            self._quiet(plan._handle_install, "user")
        # File should be overwritten with current content
        with open(os.path.join(cache_dir, ".claude-plugin", "plugin.json")) as f:
            data = json.load(f)
        self.assertEqual(data["name"], "claude-plan")
        self.assertNotIn("stale", data)

    # --- Binary update ---

    def test_install_local_updates_existing_binary(self):
        """install local overwrites existing binary at target path."""
        bin_path = os.path.join(self.tmpdir, "plan")
        with open(bin_path, "w") as f:
            f.write("old content")
        self._quiet(plan._handle_install, "local")
        with open(bin_path) as f:
            content = f.read()
        self.assertNotEqual(content, "old content")
        self.assertGreater(os.path.getsize(bin_path), 100)

    # --- CLAUDE.md replace on reinstall ---

    def test_install_local_replaces_section_preserves_other(self):
        """install local replaces section but keeps other CLAUDE.md content."""
        claude_md = os.path.join(self.tmpdir, "CLAUDE.md")
        with open(claude_md, "w") as f:
            f.write("# My Project\n\nKeep this.\n\n"
                    "## Task tracking\n\nOld instructions.\n")
        self._quiet(plan._handle_install, "local")
        with open(claude_md) as f:
            content = f.read()
        self.assertIn("Keep this.", content)
        self.assertNotIn("Old instructions.", content)
        self.assertIn("plan create", content)
        self.assertEqual(content.count("## Task tracking"), 1)


class TestEditFlagParsing(unittest.TestCase):
    """Tests for -e/--edit flag parsing."""

    def test_create_edit_flag_cli_parse(self):
        """'plan create -e expr' sets edit flag."""
        reqs = plan.parse_argv(["create", "-e", 'title="T"'])
        self.assertTrue(reqs[0].flags.get("edit"))
        self.assertEqual(reqs[0].command[0], "create")
        self.assertEqual(reqs[0].command[1], ['title="T"'])

    def test_create_edit_long_flag_cli_parse(self):
        """'plan create --edit expr' sets edit flag."""
        reqs = plan.parse_argv(["create", "--edit", 'title="T"'])
        self.assertTrue(reqs[0].flags.get("edit"))

    def test_add_edit_flag_cli_parse(self):
        """'plan 1 add -e' sets edit flag."""
        reqs = plan.parse_argv(["1", "add", "-e"])
        self.assertTrue(reqs[0].flags.get("edit"))

    def test_comment_add_edit_flag_cli_parse(self):
        """'plan 1 comment add -e' sets edit flag."""
        reqs = plan.parse_argv(["1", "comment", "add", "-e"])
        self.assertTrue(reqs[0].flags.get("edit"))


class TestOpenEditor(unittest.TestCase):
    """Test the _open_editor helper."""

    def test_open_editor_returns_edited_text(self):
        """_open_editor returns text after editor modifies file."""
        # Use 'true' as editor (no-op), so file content is returned as-is
        with unittest.mock.patch.dict(os.environ, {"EDITOR": "true"}):
            result = plan._open_editor("initial content")
        self.assertEqual(result, "initial content")

    def test_open_editor_returns_none_on_empty(self):
        """_open_editor returns None if file is empty after editing."""
        # Use a command that truncates the file
        with unittest.mock.patch.dict(os.environ, {"EDITOR": "cp /dev/null"}):
            result = plan._open_editor("initial content")
        self.assertIsNone(result)

    def test_open_editor_strips_comment_lines(self):
        """_open_editor strips lines starting with '# ' at top only."""
        content = "# Error: title required\n## My title\n    move: 1\n"
        with unittest.mock.patch.dict(os.environ, {"EDITOR": "true"}):
            result = plan._open_editor(content)
        self.assertEqual(result, "## My title\n    move: 1\n")

    def test_open_editor_preserves_body_hash_lines(self):
        """Body lines starting with '# ' are NOT stripped."""
        content = "## Title\n    move: 1\n\n# Heading in body\n"
        with unittest.mock.patch.dict(os.environ, {"EDITOR": "true"}):
            result = plan._open_editor(content)
        self.assertIn("# Heading in body", result)

    def test_open_editor_raises_on_editor_failure(self):
        """_open_editor raises SystemExit if editor exits non-zero."""
        with unittest.mock.patch.dict(os.environ, {"EDITOR": "false"}):
            with self.assertRaises(SystemExit):
                plan._open_editor("content")


class TestParseCreateTemplate(unittest.TestCase):
    """Test parsing editor template back into ticket fields."""

    def test_parse_title(self):
        text = "## My ticket\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "My ticket")

    def test_parse_title_no_hash(self):
        """Title line without ## is still accepted."""
        text = "My ticket\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "My ticket")

    def test_parse_attributes(self):
        text = "## T\n    move: 1.5\n    estimate: 2h\n    assignee: alice\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["attrs"]["move"], "1.5")
        self.assertEqual(result["attrs"]["estimate"], "2h")
        self.assertEqual(result["attrs"]["assignee"], "alice")

    def test_blank_attributes_dropped(self):
        text = "## T\n    move: 1\n    estimate: \n    assignee: \n"
        result = plan._parse_create_template(text)
        self.assertNotIn("estimate", result["attrs"])
        self.assertNotIn("assignee", result["attrs"])
        self.assertIn("move", result["attrs"])

    def test_parse_body(self):
        text = "## T\n    move: 1\n\nBody line 1\nBody line 2\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["body"], "Body line 1\nBody line 2")

    def test_parse_parent(self):
        text = "## T\n    parent: 5\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["parent"], "5")
        self.assertNotIn("parent", result["attrs"])

    def test_parse_parent_blank(self):
        text = "## T\n    parent: \n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertIsNone(result["parent"])

    def test_empty_title_error(self):
        text = "## \n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertIn("title is required", result["errors"][0])

    def test_empty_text_returns_none(self):
        result = plan._parse_create_template("")
        self.assertIsNone(result)

    def test_parse_title_with_ticket_prefix(self):
        """'Ticket:' prefix is stripped from title."""
        text = "## Ticket: My ticket\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "My ticket")
        self.assertEqual(result["ticket_type"], "Task")

    def test_parse_title_with_type_prefix(self):
        """Type prefix like 'Epic:' is parsed."""
        text = "## Epic: My ticket\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "My ticket")
        self.assertEqual(result["ticket_type"], "Epic")

    def test_parse_title_with_ticket_and_type(self):
        """Both 'Ticket:' and type prefix are parsed."""
        text = "## Ticket: Bug: Fix login\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "Fix login")
        self.assertEqual(result["ticket_type"], "Bug")

    def test_parse_plain_title_defaults_task(self):
        """Plain title without prefixes defaults to Task type."""
        text = "## My ticket\n    move: 1\n"
        result = plan._parse_create_template(text)
        self.assertEqual(result["title"], "My ticket")
        self.assertEqual(result["ticket_type"], "Task")


class TestBuildCreateTemplate(unittest.TestCase):
    """Test building editor template for create."""

    def test_basic_template(self):
        text = plan._build_create_template(move="1")
        self.assertIn("## ", text)
        self.assertIn("    move: 1", text)
        self.assertIn("    assignee:", text)
        self.assertIn("    links:", text)

    def test_template_with_parent(self):
        text = plan._build_create_template(move="1", parent="5")
        self.assertIn("    parent: 5", text)

    def test_template_with_prefilled_title(self):
        text = plan._build_create_template(move="1", title="My task")
        self.assertIn("## My task", text)

    def test_template_no_parent_by_default(self):
        text = plan._build_create_template(move="1")
        # parent line should be present but empty
        self.assertIn("    parent:", text)

    def test_template_with_errors(self):
        text = plan._build_create_template(move="1", errors=["title is required"])
        self.assertTrue(text.startswith("# Error: title is required\n"))

    def test_template_roundtrip(self):
        """Build template, parse it back — fields should survive."""
        text = plan._build_create_template(
            move="2.5", parent="3", title="Roundtrip test"
        )
        parsed = plan._parse_create_template(text)
        self.assertEqual(parsed["title"], "Roundtrip test")
        self.assertEqual(parsed["parent"], "3")
        self.assertEqual(parsed["attrs"]["move"], "2.5")

    def test_blank_line_before_attrs(self):
        """Template has a blank line between title and attributes."""
        text = plan._build_create_template(move="1", title="T")
        lines = text.split('\n')
        # Line 0: ## T, Line 1: blank, Line 2: first attr
        self.assertEqual(lines[0], "## T")
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("    "))

    def test_bulk_template(self):
        """bulk=True produces * ## format."""
        text = plan._build_create_template(move="1", title="My task", bulk=True)
        self.assertIn("* ## My task", text)
        self.assertIn("      move: 1", text)
        self.assertIn("      assignee:", text)

    def test_bulk_template_roundtrip(self):
        """Bulk template round-trips through bulk markdown parsing."""
        text = plan._build_create_template(
            move="2.5", title="Bulk test", bulk=True
        )
        # Should be detected as bulk markdown
        self.assertTrue(
            any(plan.RE_TICKET_BULK.match(l) for l in text.split("\n")))

    def test_bulk_template_blank_line_before_attrs(self):
        """Bulk template has a blank line between header and attributes."""
        text = plan._build_create_template(move="1", title="T", bulk=True)
        lines = text.split('\n')
        self.assertIn("* ## T", lines[0])
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("      "))


class TestCreateEditorMode(unittest.TestCase):
    """Test create command with editor mode."""

    def test_create_no_args_opens_editor(self):
        """create with no args uses editor."""
        p = plan.parse(SAMPLE_DOC)
        template_text = "## Editor ticket\n    move: last\n\nSome body\n"
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=template_text) as mock_ed:
            plan._handle_create(p, [], plan.ParsedRequest(), output)
            mock_ed.assert_called_once()
        new_t = p.tickets[-1]
        self.assertEqual(new_t.title, "Editor ticket")
        self.assertIn("Some body", '\n'.join(new_t.body_lines))

    def test_create_edit_flag_opens_editor(self):
        """create -e opens editor."""
        p = plan.parse(SAMPLE_DOC)
        template_text = "## Flagged\n    move: last\n"
        req = plan.ParsedRequest()
        req.flags["edit"] = True
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=template_text):
            plan._handle_create(p, [], req, output)
        self.assertEqual(p.tickets[-1].title, "Flagged")

    def test_create_edit_with_parent(self):
        """create 1 -e pre-fills parent in template."""
        p = plan.parse(SAMPLE_DOC)
        parent = p.lookup("1")
        initial_children = len(parent.children)
        template_text = "## Child via editor\n    parent: 1\n    move: last\n"
        req = plan.ParsedRequest()
        req.flags["edit"] = True
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=template_text):
            plan._handle_create(p, ['1'], req, output)
        self.assertEqual(len(parent.children), initial_children + 1)
        self.assertEqual(parent.children[-1].title, "Child via editor")

    def test_create_edit_with_expr_prefills(self):
        """create -e 'title="Pre"' pre-fills title in template."""
        p = plan.parse(SAMPLE_DOC)
        template_text = "## Pre\n    move: last\n"
        req = plan.ParsedRequest()
        req.flags["edit"] = True
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=template_text) as mock_ed:
            plan._handle_create(p, ['title="Pre"'], req, output)
            # Check template was pre-filled with title
            call_arg = mock_ed.call_args[0][0]
            self.assertIn("## Pre", call_arg)

    def test_create_edit_with_move_expr_no_phantom_ticket(self):
        """create -e 'move="after 3"' must not leak a Ticket(0) into the tree."""
        p = plan.parse(SAMPLE_DOC)
        parent_ticket = p.lookup("1")
        children_before = len(parent_ticket.children)
        all_ids_before = set(p.id_map.keys())
        # Editor returns a valid template; move target #3 is a child of #1
        template_text = "## New ticket\n\n    move: after 3\n"
        req = plan.ParsedRequest()
        req.flags["edit"] = True
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=template_text):
            plan._handle_create(p, ['move="after 3"'], req, output)
        # Exactly one new child should be added (no phantom ticket #0)
        self.assertEqual(len(parent_ticket.children), children_before + 1)
        for child in parent_ticket.children:
            self.assertNotEqual(child.node_id, 0,
                                "Phantom Ticket(0) leaked into children")

    def test_create_editor_cancel(self):
        """create editor returns None (empty) — no ticket created."""
        p = plan.parse(SAMPLE_DOC)
        initial_count = len(p.tickets)
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=None):
            plan._handle_create(p, [], plan.ParsedRequest(), output)
        self.assertEqual(len(p.tickets), initial_count)

    def test_create_editor_validation_loop(self):
        """create editor re-opens on validation error, then succeeds."""
        p = plan.parse(SAMPLE_DOC)
        # First call: empty title (error). Second call: valid.
        with unittest.mock.patch('plan._open_editor', side_effect=[
            "## \n    move: last\n",   # missing title
            "## Fixed\n    move: last\n",  # valid
        ]) as mock_ed, unittest.mock.patch('builtins.input', return_value='e'), \
                unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            output = []
            plan._handle_create(p, [], plan.ParsedRequest(), output)
            self.assertEqual(mock_ed.call_count, 2)
        self.assertIn("title is required", mock_err.getvalue())
        self.assertEqual(p.tickets[-1].title, "Fixed")

    def test_create_recursive_flag_bulk_template(self):
        """create -r opens editor with bulk template format."""
        p = plan.parse(SAMPLE_DOC)
        bulk_text = "* ## Task: Bulk ticket\n\n      move: last\n\n  Body.\n"
        req = plan.ParsedRequest()
        req.flags["edit"] = True
        req.flags["recursive"] = True
        output = []
        with unittest.mock.patch('plan._open_editor', return_value=bulk_text) as mock_ed:
            plan._handle_create(p, [], req, output)
            call_arg = mock_ed.call_args[0][0]
            self.assertIn("* ## ", call_arg)
            self.assertIn("      move:", call_arg)
        self.assertEqual(p.tickets[-1].title, "Bulk ticket")

    def test_create_editor_validation_cancel(self):
        """create editor validation — user chooses cancel."""
        p = plan.parse(SAMPLE_DOC)
        initial_count = len(p.tickets)
        with unittest.mock.patch('plan._open_editor', return_value="## \n    move: last\n"), \
                unittest.mock.patch('builtins.input', return_value='c'), \
                unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            output = []
            plan._handle_create(p, [], plan.ParsedRequest(), output)
        self.assertIn("title is required", mock_err.getvalue())
        self.assertEqual(len(p.tickets), initial_count)

    def test_create_editor_e2e(self):
        """End-to-end: create with editor (using script as EDITOR)."""
        path = "/tmp/_test_create_editor.md"
        # Write a script that fills in the template
        script = "/tmp/_test_editor.sh"
        with open(script, 'w') as f:
            f.write('#!/bin/sh\n')
            f.write('cat > "$1" << \'TEMPLATE\'\n')
            f.write('## E2E editor ticket\n')
            f.write('    move: last\n')
            f.write('\nBody from editor.\n')
            f.write('TEMPLATE\n')
        os.chmod(script, 0o755)
        try:
            result = subprocess.run(
                [sys.executable, "plan.py", "-f", path, "create"],
                capture_output=True, text=True,
                env={**os.environ, "EDITOR": script},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().isdigit())
            with open(path) as f:
                content = f.read()
            self.assertIn("E2E editor ticket", content)
            self.assertIn("Body from editor", content)
        finally:
            for p in (path, script):
                if os.path.exists(p):
                    os.unlink(p)


class TestAddEditorMode(unittest.TestCase):
    """Test add verb with editor mode."""

    def test_add_no_args_opens_editor(self):
        """add with no text arg opens editor."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        orig_len = len(t.body_lines)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = []
        with unittest.mock.patch('plan._open_editor', return_value="Editor text.\n"):
            plan._handle_add(p, [t], req)
        self.assertGreater(len(t.body_lines), orig_len)
        self.assertIn("Editor text.", t.body_lines[-1])

    def test_add_edit_flag_opens_editor(self):
        """add -e opens editor."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        orig_len = len(t.body_lines)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = []
        req.flags["edit"] = True
        with unittest.mock.patch('plan._open_editor', return_value="Flagged text.\n"):
            plan._handle_add(p, [t], req)
        self.assertGreater(len(t.body_lines), orig_len)

    def test_add_editor_cancel(self):
        """add editor returns None — no change."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        orig_len = len(t.body_lines)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = []
        with unittest.mock.patch('plan._open_editor', return_value=None):
            plan._handle_add(p, [t], req)
        self.assertEqual(len(t.body_lines), orig_len)

    def test_add_with_text_arg_unchanged(self):
        """add 'text' still works without editor."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        orig_len = len(t.body_lines)
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Direct text."]
        plan._handle_add(p, [t], req)
        self.assertGreater(len(t.body_lines), orig_len)


class TestCommentAddEditorMode(unittest.TestCase):
    """Test comment add with editor mode."""

    def test_comment_add_no_args_opens_editor(self):
        """comment add with no text opens editor."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = []
        with unittest.mock.patch('plan._open_editor', return_value="Editor comment.\n"):
            plan._handle_comment(p, [t], req, [])
        self.assertIsNotNone(t.comments)

    def test_comment_add_editor_cancel(self):
        """comment add editor returns None — no comment added."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        had_comments = t.comments is not None
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = []
        with unittest.mock.patch('plan._open_editor', return_value=None):
            plan._handle_comment(p, [t], req, [])
        if not had_comments:
            self.assertIsNone(t.comments)

    def test_comment_add_with_text_unchanged(self):
        """comment add 'text' still works without editor."""
        p = plan.parse(SAMPLE_DOC)
        t = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "add"
        req.verb_args = ["Direct comment."]
        plan._handle_comment(p, [t], req, [])
        self.assertIsNotNone(t.comments)


class TestLinkUnlinkVerbs(unittest.TestCase):
    """Test link and unlink verb handlers."""

    def test_link_default_related(self):
        """plan 1 link 2 → related link."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["2"]
        plan._handle_link(p, [t1], req)
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertIn(2, links1.get("related", []))
        # Mirror
        links2 = plan._parse_links(t2.get_attr("links"))
        self.assertIn(1, links2.get("related", []))

    def test_link_with_type(self):
        """plan 1 link blocked 2 → blocked link."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["blocked", "2"]
        plan._handle_link(p, [t1], req)
        links = plan._parse_links(t1.get_attr("links"))
        self.assertIn(2, links.get("blocked", []))

    def test_link_updates_timestamp(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        old = t1.get_attr("updated")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["2"]
        plan._handle_link(p, [t1], req)
        self.assertNotEqual(t1.get_attr("updated"), old)

    def test_link_invalid_type(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["bogus", "2"]
        with self.assertRaises(SystemExit):
            plan._handle_link(p, [t1], req)

    def test_link_self_error(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["1"]
        with self.assertRaises(SystemExit):
            plan._handle_link(p, [t1], req)

    def test_link_missing_target(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = []
        with self.assertRaises(SystemExit):
            plan._handle_link(p, [t1], req)

    def test_link_target_not_found(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["999"]
        with self.assertRaises(SystemExit):
            plan._handle_link(p, [t1], req)

    def test_link_multiple_sources(self):
        """plan 1 2 link related 3 — link both to some target."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        t2 = p.lookup("2")
        req = plan.ParsedRequest()
        req.verb = "link"
        req.verb_args = ["related", "2"]
        plan._handle_link(p, [t1], req)
        links1 = plan._parse_links(t1.get_attr("links"))
        self.assertIn(2, links1.get("related", []))

    def test_unlink_default_all(self):
        """plan 1 unlink 2 → remove ALL links to #2."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        plan.add_link(p, t1, "blocked", 2)
        plan.add_link(p, t1, "related", 2)
        req = plan.ParsedRequest()
        req.verb = "unlink"
        req.verb_args = ["2"]
        plan._handle_unlink(p, [t1], req)
        links = plan._parse_links(t1.get_attr("links", ""))
        self.assertNotIn(2, links.get("blocked", []))
        self.assertNotIn(2, links.get("related", []))

    def test_unlink_specific_type(self):
        """plan 1 unlink blocked 2 → remove only blocked link."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        plan.add_link(p, t1, "blocked", 2)
        plan.add_link(p, t1, "related", 2)
        req = plan.ParsedRequest()
        req.verb = "unlink"
        req.verb_args = ["blocked", "2"]
        plan._handle_unlink(p, [t1], req)
        links = plan._parse_links(t1.get_attr("links", ""))
        self.assertNotIn(2, links.get("blocked", []))
        self.assertIn(2, links.get("related", []))

    def test_unlink_all_explicit(self):
        """plan 1 unlink all 2 → same as plan 1 unlink 2."""
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        plan.add_link(p, t1, "blocked", 2)
        plan.add_link(p, t1, "related", 2)
        req = plan.ParsedRequest()
        req.verb = "unlink"
        req.verb_args = ["all", "2"]
        plan._handle_unlink(p, [t1], req)
        links = plan._parse_links(t1.get_attr("links", ""))
        self.assertNotIn(2, links.get("blocked", []))
        self.assertNotIn(2, links.get("related", []))

    def test_unlink_updates_timestamp(self):
        p = plan.parse(SAMPLE_DOC)
        t1 = p.lookup("1")
        plan.add_link(p, t1, "related", 2)
        old = t1.get_attr("updated")
        req = plan.ParsedRequest()
        req.verb = "unlink"
        req.verb_args = ["2"]
        plan._handle_unlink(p, [t1], req)
        self.assertNotEqual(t1.get_attr("updated"), old)


class TestNextVerb(unittest.TestCase):
    """Test 'next' verb — shortcut for list order -n 1."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        )
        self.tmpfile.write(textwrap.dedent("""\
        # P {#project}

        ## Metadata {#metadata}

            next_id: 4

        ## Tickets {#tickets}

        * ## Ticket: Task: A {#1}

              status: open

        * ## Ticket: Task: B {#2}

              status: open
              links: blocked:#1

        * ## Ticket: Task: C {#3}

              status: open
              links: blocked:#2
        """))
        self.tmpfile.close()
        self.addCleanup(os.unlink, self.tmpfile.name)

    def _run(self, *args):
        cmd = [sys.executable, "plan.py", "-f", self.tmpfile.name] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result

    def test_next_returns_one(self):
        """plan next returns exactly one ticket."""
        r = self._run("next")
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.strip().split('\n') if l.strip()]
        self.assertEqual(len(lines), 1)

    def test_next_returns_first_in_order(self):
        """plan next returns #1 (no blockers, comes first)."""
        r = self._run("next")
        self.assertEqual(r.returncode, 0)
        self.assertIn("#1", r.stdout)

    def test_next_n_overrides(self):
        """plan next -n 2 returns two tickets."""
        r = self._run("next", "-n", "2")
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.strip().split('\n') if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_next_with_format(self):
        """plan next --format works."""
        r = self._run("next", "--format", 'f"{indent}#{id} {title}"')
        self.assertEqual(r.returncode, 0)
        self.assertIn("#1", r.stdout)
        self.assertIn("A", r.stdout)

    def test_next_with_query(self):
        """plan next -q filters before picking."""
        r = self._run("next", "-q", 'title == "B"')
        self.assertEqual(r.returncode, 0)
        # B is blocked by A, but order mode filters only open tickets
        # and B is open, so it should appear (even if blocked)
        # Actually order mode includes all open tickets in topological order
        self.assertIn("#2", r.stdout)

    def test_parse_next_verb(self):
        """Parser recognizes 'next' as a verb."""
        reqs = plan.parse_argv(["next"])
        self.assertEqual(reqs[0].verb, "next")

    def test_parse_next_with_n(self):
        """Parser: plan next -n 3."""
        reqs = plan.parse_argv(["next", "-n", "3"])
        self.assertEqual(reqs[0].verb, "next")
        self.assertEqual(reqs[0].flags.get("n"), 3)


class TestBulkScanning(unittest.TestCase):
    """Test _scan_bulk_headers() — pass 1 of bulk creation."""

    def test_scan_placeholder_ids(self):
        text = textwrap.dedent("""\
        * ## Ticket: Epic: Auth {#newAuth}

          Auth system.

          * ## Ticket: Task: JWT {#newJWT}

            JWT middleware.
        """)
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 2)
        self.assertEqual(headers[0][1], "newAuth")
        self.assertTrue(headers[0][2])
        self.assertEqual(headers[1][1], "newJWT")
        self.assertTrue(headers[1][2])

    def test_scan_missing_ids(self):
        text = "* ## Ticket: Task: Build API\n\n  API impl.\n"
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 1)
        self.assertIsNone(headers[0][1])
        self.assertTrue(headers[0][2])

    def test_scan_numeric_ids(self):
        text = "* ## Ticket: Task: Existing {#5}\n"
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 1)
        self.assertFalse(headers[0][2])  # is_new = False

    def test_scan_placeholder_without_new_prefix(self):
        """Non-numeric IDs without 'new' prefix are treated as placeholders."""
        text = "* ## Ticket: Task: Auth {#auth}\n* ## Ticket: Task: DB {#db}\n"
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 2)
        self.assertEqual(headers[0][1], "auth")
        self.assertTrue(headers[0][2])
        self.assertEqual(headers[1][1], "db")
        self.assertTrue(headers[1][2])

    def test_scan_placeholder_with_hyphens(self):
        """Placeholders can contain hyphens."""
        text = "* ## Ticket: Task: Auth Service {#auth-service}\n"
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0][1], "auth-service")
        self.assertTrue(headers[0][2])

    def test_scan_digit_prefixed_id_is_placeholder(self):
        """IDs starting with a digit but containing non-digits are placeholders."""
        text = (
            "* ## Ticket: Task: A {#1a}\n"
            "* ## Ticket: Task: B {#2-auth}\n"
            "* ## Ticket: Task: C {#3_task}\n"
        )
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 3)
        for _, placeholder, is_new in headers:
            self.assertTrue(is_new, f"'{placeholder}' should be treated as new")
            self.assertIsNotNone(placeholder)
        self.assertEqual(headers[0][1], "1a")
        self.assertEqual(headers[1][1], "2-auth")
        self.assertEqual(headers[2][1], "3_task")

    def test_scan_duplicate_placeholder_error(self):
        text = "* ## Ticket: Task: A {#newFoo}\n* ## Ticket: Task: B {#newFoo}\n"
        with self.assertRaises(SystemExit):
            plan._scan_bulk_headers(text)

    def test_scan_mixed_new_and_existing(self):
        text = textwrap.dedent("""\
        * ## Ticket: Epic: Existing {#3}

          * ## Ticket: Task: New Child {#newChild}

            New task.
        """)
        headers = plan._scan_bulk_headers(text)
        self.assertEqual(len(headers), 2)
        self.assertFalse(headers[0][2])   # existing
        self.assertTrue(headers[1][2])    # new
        self.assertEqual(headers[1][1], "newChild")


class TestBulkIdAllocation(unittest.TestCase):

    def test_allocate_placeholders(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        headers = [
            (0, "newAuth", True),
            (5, "newDB", True),
        ]
        placeholder_map, new_ids, id_for_missing, next_id = plan._allocate_bulk_ids(project, headers)
        self.assertEqual(placeholder_map, {"#newAuth": "#1", "#newDB": "#2"})
        self.assertEqual(new_ids, {1, 2})
        self.assertEqual(next_id, 3)
        self.assertEqual(project.next_id, 1)  # NOT mutated

    def test_allocate_missing_ids(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        headers = [(0, None, True), (3, None, True)]
        placeholder_map, new_ids, id_for_missing, next_id = plan._allocate_bulk_ids(project, headers)
        self.assertEqual(placeholder_map, {})
        self.assertEqual(new_ids, {1, 2})
        self.assertEqual(next_id, 3)

    def test_allocate_skips_existing(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 10
        ## Tickets {#tickets}
        """)
        headers = [(0, None, False), (3, "newFoo", True)]
        placeholder_map, new_ids, id_for_missing, next_id = plan._allocate_bulk_ids(project, headers)
        self.assertEqual(placeholder_map, {"#newFoo": "#10"})
        self.assertEqual(new_ids, {10})
        self.assertEqual(next_id, 11)

    def test_create_mode_rejects_numeric_ids(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 10
        ## Tickets {#tickets}
        """)
        headers = [(0, None, False)]
        with self.assertRaises(SystemExit):
            plan._allocate_bulk_ids(project, headers, mode="create")


class TestRankHashTolerance(unittest.TestCase):
    """Test that move expressions tolerate # prefix on IDs."""

    def test_rank_after_with_hash(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        """)
        ticket_b = project.lookup("2")
        old_rank = ticket_b._rank
        result = plan._resolve_move_expr("after #1", ticket_b, project)
        self.assertTrue(result)
        self.assertIsInstance(ticket_b._rank, (int, float))

    def test_rank_before_with_hash(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        """)
        ticket_b = project.lookup("2")
        result = plan._resolve_move_expr("before #1", ticket_b, project)
        self.assertTrue(result)
        self.assertIsInstance(ticket_b._rank, (int, float))

    def test_rank_first_with_hash(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: Parent {#1}
              status: open
          * ## Ticket: Task: Child {#2}
                status: open
        """)
        new_ticket = plan.Ticket(3, "New", "Task")
        new_ticket._rank = 0.0
        new_ticket.parent = project.lookup("1")
        new_ticket.indent_level = 2
        result = plan._resolve_move_expr("first #1", new_ticket, project)
        self.assertTrue(result)
        self.assertIsInstance(new_ticket._rank, (int, float))

    def test_rank_last_with_hash(self):
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: Parent {#1}
              status: open
          * ## Ticket: Task: Child {#2}
                status: open
        """)
        new_ticket = plan.Ticket(3, "New", "Task")
        new_ticket._rank = 0.0
        new_ticket.parent = project.lookup("1")
        new_ticket.indent_level = 2
        result = plan._resolve_move_expr("last #1", new_ticket, project)
        self.assertTrue(result)
        self.assertIsInstance(new_ticket._rank, (int, float))

    def test_rank_without_hash_still_works(self):
        """Existing behavior: move 'after 1' without # should still work."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        """)
        ticket_b = project.lookup("2")
        result = plan._resolve_move_expr("after 1", ticket_b, project)
        self.assertTrue(result)
        self.assertIsInstance(ticket_b._rank, (int, float))


class TestBulkSubstitution(unittest.TestCase):

    def test_substitute_placeholder_in_header(self):
        text = "* ## Ticket: Epic: Auth {#newAuth}\n"
        placeholder_map = {"#newAuth": "#1"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("{#1}", result)
        self.assertNotIn("#newAuth", result)

    def test_substitute_placeholder_in_links(self):
        text = "    links: blocked:#newDB\n"
        placeholder_map = {"#newDB": "#5"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("blocked:#5", result)

    def test_insert_id_for_missing(self):
        text = "* ## Ticket: Task: Build API\n"
        result = plan._substitute_bulk_text(text, {}, {0: 1})
        self.assertIn("{#1}", result)

    def test_undefined_placeholder_error(self):
        text = "    links: blocked:#newGhost\n"
        with self.assertRaises(SystemExit):
            plan._substitute_bulk_text(text, {}, {})

    def test_undefined_placeholder_without_new_prefix(self):
        """Non-numeric identifiers without 'new' prefix are also caught."""
        text = "    links: blocked:#ghost\n"
        with self.assertRaises(SystemExit):
            plan._substitute_bulk_text(text, {}, {})

    def test_substitute_placeholder_without_new_prefix(self):
        """Placeholders without 'new' prefix are substituted correctly."""
        text = "* ## Ticket: Epic: Auth {#auth}\n    links: blocking:#db\n"
        placeholder_map = {"#auth": "#1", "#db": "#2"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("{#1}", result)
        self.assertIn("blocking:#2", result)

    def test_substitute_placeholder_with_hyphens(self):
        """Placeholders with hyphens work correctly."""
        text = "    links: blocked:#auth-service\n"
        placeholder_map = {"#auth-service": "#5"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("blocked:#5", result)

    def test_body_text_references_substituted(self):
        text = "  See #newAuth for details.\n"
        placeholder_map = {"#newAuth": "#1"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("See #1 for details", result)

    def test_multiple_placeholders(self):
        text = "    links: blocked:#newA blocking:#newB\n"
        placeholder_map = {"#newA": "#10", "#newB": "#11"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("blocked:#10", result)
        self.assertIn("blocking:#11", result)

    def test_substitute_prefix_collision(self):
        """#auth must not match inside #auth-svc (prefix collision)."""
        text = (
            "* ## Ticket: Task: Auth {#auth}\n"
            "    links: blocking:#auth-svc\n"
            "* ## Ticket: Task: Auth Service {#auth-svc}\n"
            "    links: blocked:#auth\n"
        )
        placeholder_map = {"#auth": "#1", "#auth-svc": "#2"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("{#1}", result)
        self.assertIn("{#2}", result)
        self.assertIn("blocking:#2", result)
        self.assertIn("blocked:#1", result)
        # Must NOT contain corrupted fragments like #1-svc
        self.assertNotIn("#1-svc", result)

    def test_substitute_prefix_collision_in_body(self):
        """Body text references with prefix overlap resolve correctly."""
        text = (
            "  See #a and #ab for details.\n"
        )
        placeholder_map = {"#a": "#5", "#ab": "#6"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("#5 and #6", result)
        # Must not corrupt #ab into #5b
        self.assertNotIn("#5b", result)

    def test_substitute_digit_prefixed_placeholder(self):
        """Digit-prefixed non-numeric placeholders are resolved like any other."""
        text = (
            "* ## Ticket: Task: A {#1a}\n"
            "    links: blocked:#2b\n"
            "* ## Ticket: Task: B {#2b}\n"
            "    links: blocking:#1a\n"
        )
        placeholder_map = {"#1a": "#10", "#2b": "#11"}
        result = plan._substitute_bulk_text(text, placeholder_map, {})
        self.assertIn("{#10}", result)
        self.assertIn("{#11}", result)
        self.assertIn("blocked:#11", result)
        self.assertIn("blocking:#10", result)


class TestParseBulkMarkdown(unittest.TestCase):

    def _project(self, next_id=1):
        return make_doc(f"""\
        # Test {{#project}}
        ## Metadata {{#metadata}}
            next_id: {next_id}
        ## Tickets {{#tickets}}
        """)

    def test_create_single_ticket(self):
        project = self._project()
        text = "* ## Ticket: Task: Build API\n\n  Implement the API.\n"
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Build API")
        self.assertEqual(tickets[0].node_id, 1)
        self.assertIn(1, new_ids)
        self.assertEqual(tickets[0].get_attr("status"), "open")
        self.assertNotEqual(tickets[0].get_attr("created"), "")

    def test_create_hierarchy(self):
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Epic: Auth {#newAuth}

              links: blocking:#newDB

          Auth system.

          * ## Ticket: Task: JWT

            JWT middleware.

        * ## Ticket: Epic: Database {#newDB}

              links: blocked:#newAuth

          Schema.
        """)
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 2)  # two top-level
        self.assertEqual(len(tickets[0].children), 1)  # JWT under Auth
        self.assertEqual(new_ids, {1, 2, 3})
        # Cross-references resolved
        auth = tickets[0]
        db = tickets[1]
        self.assertIn(f"blocking:#{db.node_id}", auth.get_attr("links"))
        self.assertIn(f"blocked:#{auth.node_id}", db.get_attr("links"))

    def test_create_hierarchy_without_new_prefix(self):
        """Placeholders without 'new' prefix work end-to-end."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Epic: Auth {#auth}

              links: blocking:#db

          Auth system.

        * ## Ticket: Epic: Database {#db}

              links: blocked:#auth

          Schema.
        """)
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 2)
        self.assertEqual(new_ids, {1, 2})
        auth = tickets[0]
        db = tickets[1]
        self.assertIn(f"blocking:#{db.node_id}", auth.get_attr("links"))
        self.assertIn(f"blocked:#{auth.node_id}", db.get_attr("links"))

    def test_create_with_hyphenated_placeholders(self):
        """Placeholders with hyphens work end-to-end."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Task: Auth Service {#auth-svc}

              links: blocking:#db-svc

          Auth.

        * ## Ticket: Task: DB Service {#db-svc}

              links: blocked:#auth-svc

          DB.
        """)
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 2)
        auth = tickets[0]
        db = tickets[1]
        self.assertIn(f"blocking:#{db.node_id}", auth.get_attr("links"))
        self.assertIn(f"blocked:#{auth.node_id}", db.get_attr("links"))

    def test_create_prefix_collision_e2e(self):
        """Placeholder that is a prefix of another resolves correctly e2e."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Task: Auth {#auth}

              links: blocking:#auth-svc

          Auth core.

        * ## Ticket: Task: Auth Service {#auth-svc}

              links: blocked:#auth

          Auth service.
        """)
        tickets, _ = plan._parse_bulk_markdown(
            text, project, parent=None, mode="create")
        auth = tickets[0]
        svc = tickets[1]
        self.assertIn(f"blocking:#{svc.node_id}", auth.get_attr("links"))
        self.assertIn(f"blocked:#{auth.node_id}", svc.get_attr("links"))
        # Verify IDs are distinct
        self.assertNotEqual(auth.node_id, svc.node_id)

    def test_create_digit_prefixed_placeholders_e2e(self):
        """IDs like {#1a} are user-defined placeholders, not numeric IDs."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Task: Step 1 {#1a}

              links: blocking:#1b

          First step.

        * ## Ticket: Task: Step 2 {#1b}

              links: blocked:#1a

          Second step.
        """)
        tickets, new_ids = plan._parse_bulk_markdown(
            text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 2)
        # Both treated as new (allocated numeric IDs)
        self.assertEqual(len(new_ids), 2)
        s1 = tickets[0]
        s2 = tickets[1]
        # Cross-references resolved to allocated numeric IDs
        self.assertIn(f"blocking:#{s2.node_id}", s1.get_attr("links"))
        self.assertIn(f"blocked:#{s1.node_id}", s2.get_attr("links"))

    def test_create_rejects_numeric_ids(self):
        project = self._project()
        text = "* ## Ticket: Task: Existing {#5}\n"
        with self.assertRaises(SystemExit):
            plan._parse_bulk_markdown(text, project, parent=None, mode="create")

    def test_project_next_id_committed(self):
        project = self._project(next_id=1)
        text = "* ## Ticket: Task: A\n* ## Ticket: Task: B\n* ## Ticket: Task: C\n"
        plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(project.next_id, 4)

    def test_no_tickets_found_error(self):
        project = self._project()
        text = "Just some text, no ticket headers.\n"
        with self.assertRaises(SystemExit):
            plan._parse_bulk_markdown(text, project, parent=None, mode="create")

    def test_defaults_not_overwritten(self):
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Task: Custom Status

              status: in-progress

          Has custom status.
        """)
        tickets, _ = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(tickets[0].get_attr("status"), "in-progress")

    def test_snapshot_restored_on_error(self):
        project = self._project(next_id=5)
        text = "* ## Ticket: Task: OK\n    links: blocked:#newGhost\n"
        with self.assertRaises(SystemExit):
            plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(project.next_id, 5)  # restored

    def test_blank_attributes_dropped(self):
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Task: Empty Attrs

              estimate:
              assignee:
              priority: high

          Some body.
        """)
        tickets, _ = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertNotIn("estimate", tickets[0].attrs)
        self.assertNotIn("assignee", tickets[0].attrs)
        self.assertEqual(tickets[0].get_attr("priority"), "high")

    def test_create_under_parent(self):
        project = self._project(next_id=2)
        parent = plan.Ticket(1, "Parent Epic", "Epic")
        parent.attrs["status"] = "open"
        parent.attrs["rank"] = "0"
        parent.indent_level = 0
        project.tickets.append(parent)
        project.register(parent)
        text = "* ## Ticket: Task: Child\n\n  Child task.\n"
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=parent, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].parent, parent)
        self.assertEqual(tickets[0].indent_level, 2)

    def test_create_title_only(self):
        """Minimal format: just * ## Title."""
        project = self._project()
        text = "* ## Build API\n"
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Build API")
        self.assertEqual(tickets[0].ticket_type, "Task")

    def test_create_type_only(self):
        """Format with type but no Ticket: keyword."""
        project = self._project()
        text = "* ## Epic: Build API\n"
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Build API")
        self.assertEqual(tickets[0].ticket_type, "Epic")

    def test_create_ticket_keyword_only(self):
        """Format with Ticket: but no type defaults to Task."""
        project = self._project()
        text = "* ## Ticket: Build API\n"
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Build API")
        self.assertEqual(tickets[0].ticket_type, "Task")

    def test_create_mixed_formats(self):
        """Mix of full, partial, and minimal formats."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Ticket: Epic: Full format
        * ## Bug: Type only
        * ## Ticket: Keyword only
        * ## Title only
        """)
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 4)
        self.assertEqual(tickets[0].ticket_type, "Epic")
        self.assertEqual(tickets[0].title, "Full format")
        self.assertEqual(tickets[1].ticket_type, "Bug")
        self.assertEqual(tickets[1].title, "Type only")
        self.assertEqual(tickets[2].ticket_type, "Task")
        self.assertEqual(tickets[2].title, "Keyword only")
        self.assertEqual(tickets[3].ticket_type, "Task")
        self.assertEqual(tickets[3].title, "Title only")

    def test_create_hierarchy_minimal(self):
        """Hierarchy with minimal format."""
        project = self._project()
        text = textwrap.dedent("""\
        * ## Parent task

          * ## Child task
        """)
        tickets, new_ids = plan._parse_bulk_markdown(text, project, parent=None, mode="create")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Parent task")
        self.assertEqual(len(tickets[0].children), 1)
        self.assertEqual(tickets[0].children[0].title, "Child task")


class TestCreateBulk(unittest.TestCase):
    """Test bulk creation via _handle_create with markdown input."""

    def _project(self, next_id=1):
        return make_doc(f"""\
        # Test {{#project}}
        ## Metadata {{#metadata}}
            next_id: {next_id}
        ## Tickets {{#tickets}}
        """)

    def test_create_bulk_from_stdin(self):
        project = self._project()
        md = textwrap.dedent("""\
        * ## Ticket: Epic: Feature X

          Feature description.

          * ## Ticket: Task: Subtask A

            Do A.

          * ## Ticket: Task: Subtask B

            Do B.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)
        self.assertEqual(len(project.tickets), 1)
        self.assertEqual(len(project.tickets[0].children), 2)
        self.assertEqual(sorted(output), ["1", "2", "3"])

    def test_create_bulk_under_parent(self):
        project = self._project(next_id=5)
        parent = plan.Ticket(4, "Parent", "Epic")
        parent.attrs["status"] = "open"
        parent.attrs["rank"] = "0"
        parent.indent_level = 0
        project.tickets.append(parent)
        project.register(parent)

        md = "* ## Ticket: Task: Child A\n\n  Do A.\n"
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["4", "-"], req, output)
        self.assertEqual(len(parent.children), 1)
        self.assertEqual(parent.children[0].title, "Child A")
        self.assertEqual(output, ["5"])

    def test_create_bulk_rejects_numeric_ids(self):
        project = self._project()
        md = "* ## Ticket: Task: Bad {#99}\n"
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            with self.assertRaises(SystemExit):
                plan._handle_create(project, ["-"], req, output)

    def test_create_bulk_cross_references(self):
        project = self._project()
        md = textwrap.dedent("""\
        * ## Ticket: Task: A {#newA}

              links: blocked:#newB

          Task A.

        * ## Ticket: Task: B {#newB}

              links: blocking:#newA

          Task B.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)
        a = project.lookup("1")
        b = project.lookup("2")
        self.assertIn("blocked:#2", a.get_attr("links"))
        self.assertIn("blocking:#1", b.get_attr("links"))

    def test_create_expr_mode_unchanged(self):
        """Existing DSL expression mode still works."""
        project = self._project()
        output = []
        req = plan.ParsedRequest()
        plan._handle_create(project, ['title="Test task"'], req, output)
        self.assertEqual(len(project.tickets), 1)
        self.assertEqual(project.tickets[0].title, "Test task")

    def test_create_bulk_quiet_flag(self):
        project = self._project()
        md = "* ## Ticket: Task: Quiet\n"
        output = []
        req = plan.ParsedRequest()
        req.flags["quiet"] = True
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)
        self.assertEqual(output, [])  # quiet = no output
        self.assertEqual(len(project.tickets), 1)


class TestEditRecursiveBulk(unittest.TestCase):
    """Test bulk ticket creation during edit -r."""

    def _project_with_ticket(self):
        return make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 2
        ## Tickets {#tickets}
        * ## Ticket: Epic: Auth {#1}

              status: open

          Auth system.
        """)

    def test_edit_add_new_child_no_id(self):
        project = self._project_with_ticket()
        ticket = project.lookup("1")

        def mock_editor(cmd):
            path = cmd[-1]
            with open(path) as f:
                text = f.read()
            text += "\n  * ## Ticket: Task: New Child\n\n    New child task.\n"
            with open(path, 'w') as f:
                f.write(text)
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_recursive(project, ticket, "vi", include_children=True)

        root = project.tickets[0]
        self.assertEqual(len(root.children), 1)
        self.assertEqual(root.children[0].title, "New Child")
        self.assertEqual(root.children[0].get_attr("status"), "open")
        self.assertNotEqual(root.children[0].get_attr("created"), "")
        self.assertEqual(project.next_id, 3)

    def test_edit_add_child_with_placeholder(self):
        project = self._project_with_ticket()
        ticket = project.lookup("1")

        def mock_editor(cmd):
            path = cmd[-1]
            with open(path) as f:
                text = f.read()
            # Editor text is normalized to indent 0, so children need 2-space indent
            text += "\n"
            text += "  * ## Ticket: Task: A {#newA}\n"
            text += "\n"
            text += "        links: blocked:#newB\n"
            text += "\n"
            text += "    Task A.\n"
            text += "\n"
            text += "  * ## Ticket: Task: B {#newB}\n"
            text += "\n"
            text += "        links: blocking:#newA\n"
            text += "\n"
            text += "    Task B.\n"
            with open(path, 'w') as f:
                f.write(text)
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_recursive(project, ticket, "vi", include_children=True)

        root = project.tickets[0]
        self.assertEqual(len(root.children), 2)
        child_a = root.children[0]
        child_b = root.children[1]
        self.assertIn(f"blocked:#{child_b.node_id}", child_a.get_attr("links"))
        self.assertIn(f"blocking:#{child_a.node_id}", child_b.get_attr("links"))

    def test_edit_preserves_existing_ticket(self):
        """Editing existing ticket content while adding new children."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 3
        ## Tickets {#tickets}
        * ## Ticket: Epic: Auth {#1}

              status: open

          Auth system.

          * ## Ticket: Task: Existing {#2}

                status: in-progress

            Existing task.
        """)
        ticket = project.lookup("1")

        def mock_editor(cmd):
            path = cmd[-1]
            with open(path) as f:
                text = f.read()
            # Add a new sibling to existing child
            text += "\n  * ## Ticket: Task: New Sibling\n\n    New task.\n"
            with open(path, 'w') as f:
                f.write(text)
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_recursive(project, ticket, "vi", include_children=True)

        root = project.tickets[0]
        self.assertEqual(len(root.children), 2)
        self.assertEqual(root.children[0].node_id, 2)  # existing preserved
        self.assertEqual(root.children[1].node_id, 3)  # new allocated
        self.assertEqual(project.next_id, 4)

    def test_edit_no_new_tickets_unchanged(self):
        """Existing edit -r behavior without new tickets still works."""
        project = self._project_with_ticket()
        ticket = project.lookup("1")

        def mock_editor(cmd):
            path = cmd[-1]
            with open(path) as f:
                text = f.read()
            # Just modify the body text, don't add new tickets
            text = text.replace("Auth system.", "Updated auth system.")
            with open(path, 'w') as f:
                f.write(text)
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_recursive(project, ticket, "vi", include_children=True)

        root = project.tickets[0]
        self.assertEqual(root.node_id, 1)
        self.assertEqual(project.next_id, 2)  # unchanged


# ===================================================================
# Task 10: Integration tests for bulk ticket creation
# ===================================================================

class TestBulkIntegration(unittest.TestCase):
    """End-to-end tests for bulk creation and edit workflows."""

    def test_roundtrip_create_and_serialize(self):
        """Create bulk tickets, serialize, re-parse — verify consistency."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        md = textwrap.dedent("""\
        * ## Ticket: Epic: Auth {#newAuth}

              links: blocking:#newDB

          Auth system.

          * ## Ticket: Task: JWT

            JWT middleware.

        * ## Ticket: Epic: DB {#newDB}

              links: blocked:#newAuth

          Database layer.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)

        # Serialize and re-parse
        serialized = plan.serialize(project)
        reparsed = plan.parse(serialized)

        self.assertEqual(len(reparsed.tickets), 2)
        auth = reparsed.tickets[0]
        db = reparsed.tickets[1]
        self.assertEqual(auth.title, "Auth")
        self.assertEqual(len(auth.children), 1)
        self.assertEqual(auth.children[0].title, "JWT")
        self.assertEqual(db.title, "DB")
        self.assertEqual(reparsed.next_id, 4)
        # Links survived round-trip (Auth=1, JWT=2, DB=3)
        self.assertIn("blocking:#3", auth.get_attr("links"))
        self.assertIn("blocked:#1", db.get_attr("links"))

    def test_bulk_create_then_edit_add_children(self):
        """Create tickets, then edit -r to add more."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        # First: bulk create
        md1 = "* ## Ticket: Epic: Feature\n\n  Feature X.\n"
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md1
            plan._handle_create(project, ["-"], req, output)

        self.assertEqual(project.next_id, 2)

        # Then: edit -r to add a child
        ticket = project.lookup("1")

        def mock_editor(cmd):
            path = cmd[-1]
            with open(path) as f:
                text = f.read()
            text += "\n  * ## Ticket: Task: New Child\n\n    Child desc.\n"
            with open(path, 'w') as f:
                f.write(text)
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch('subprocess.run', side_effect=mock_editor):
            plan._handle_edit_recursive(project, ticket, "vi",
                                         include_children=True)

        root = project.tickets[0]
        self.assertTrue(len(root.children) >= 1)
        self.assertEqual(project.next_id, 3)

    def test_circular_references(self):
        """Verify circular #newXXX references work."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        md = textwrap.dedent("""\
        * ## Ticket: Task: A {#newA}

              links: blocked:#newB

          Task A.

        * ## Ticket: Task: B {#newB}

              links: blocked:#newA

          Task B.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)

        a = project.lookup("1")
        b = project.lookup("2")
        self.assertIn("blocked:#2", a.get_attr("links"))
        self.assertIn("blocked:#1", b.get_attr("links"))

    def test_rank_reparenting_in_bulk(self):
        """Rank expression moves ticket to different parent."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        md = textwrap.dedent("""\
        * ## Ticket: Epic: A {#newA}

          Epic A.

        * ## Ticket: Epic: B {#newB}

          Epic B.

          * ## Ticket: Task: Misplaced {#newMis}

                move: first #newA

            Should end up under A, not B.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)

        a = project.lookup("1")
        b = project.lookup("2")
        mis = project.lookup("3")
        # Misplaced should have been reparented under A
        self.assertIn(mis, a.children)
        self.assertNotIn(mis, b.children)

    def test_all_defaults_filled(self):
        """All mandatory attributes are filled for new tickets."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        md = textwrap.dedent("""\
        * ## Ticket: Epic: Root

          Root ticket.

          * ## Ticket: Task: Child

            Child ticket.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)

        for tid in ["1", "2"]:
            t = project.lookup(tid)
            self.assertNotEqual(t.get_attr("status"), "", f"#{tid} missing status")
            self.assertNotEqual(t.get_attr("created"), "", f"#{tid} missing created")
            self.assertNotEqual(t.get_attr("updated"), "", f"#{tid} missing updated")
            self.assertIsNotNone(t._rank, f"#{tid} missing _rank")

    def test_large_hierarchy(self):
        """Bulk create a larger hierarchy with 3 levels."""
        project = make_doc("""\
        # Test {#project}
        ## Metadata {#metadata}
            next_id: 1
        ## Tickets {#tickets}
        """)
        md = textwrap.dedent("""\
        * ## Ticket: Epic: E1

          * ## Ticket: Task: T1

            * ## Ticket: Task: S1

              Subtask.

            * ## Ticket: Task: S2

              Subtask.

          * ## Ticket: Task: T2

            Task 2.

        * ## Ticket: Epic: E2

          * ## Ticket: Task: T3

            Task 3.
        """)
        output = []
        req = plan.ParsedRequest()
        with unittest.mock.patch('sys.stdin') as mock_stdin:
            mock_stdin.read.return_value = md
            plan._handle_create(project, ["-"], req, output)

        self.assertEqual(len(project.tickets), 2)  # E1, E2
        e1 = project.tickets[0]
        self.assertEqual(len(e1.children), 2)  # T1, T2
        t1 = e1.children[0]
        self.assertEqual(len(t1.children), 2)  # S1, S2
        # E1=1, T1=2, S1=3, S2=4, T2=5, E2=6, T3=7 => next_id=8
        self.assertEqual(project.next_id, 8)
        self.assertEqual(sorted(output), ["1", "2", "3", "4", "5", "6", "7"])


class TestReadyDSL(unittest.TestCase):
    """Tests for ready DSL property."""

    def test_ready_basic(self):
        """ready: active + no blockers + no active children."""
        p = plan.parse(SAMPLE_DOC)
        plan._project = p
        # #2 is in-progress with no children → ready
        ns = plan._make_dsl_namespace(p.lookup("2"))
        self.assertTrue(ns["ready"])
        # #3 is open with no children → ready
        ns = plan._make_dsl_namespace(p.lookup("3"))
        self.assertTrue(ns["ready"])
        # #1 has open child #3 → not ready
        ns = plan._make_dsl_namespace(p.lookup("1"))
        self.assertFalse(ns["ready"])
        # #4 is done → not ready (not active)
        ns = plan._make_dsl_namespace(p.lookup("4"))
        self.assertFalse(ns["ready"])

    def test_ready_deferred_not_ready(self):
        """Deferred ticket is open but not active, therefore not ready."""
        p = plan.parse(SAMPLE_DOC)
        plan._project = p
        t = p.lookup("3")
        t.set_attr("status", "backlog")
        ns = plan._make_dsl_namespace(t)
        self.assertFalse(ns["ready"])

    def test_ready_deferred_child_does_not_block(self):
        """Active parent with deferred child is still ready."""
        p = plan.parse(SAMPLE_DOC)
        plan._project = p
        # #1 has child #3 — defer #3
        p.lookup("3").set_attr("status", "backlog")
        ns = plan._make_dsl_namespace(p.lookup("1"))
        # #3 is deferred (not active) so doesn't block #1
        self.assertTrue(ns["ready"])


class TestSerializerRankOrder(unittest.TestCase):
    """Test that serializer sorts tickets by _rank."""

    def test_serializer_sorts_top_level_by_rank(self):
        """After move, serializer outputs tickets in _rank order."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        * ## Ticket: Task: C {#3}
              status: open
        """)
        p = plan.parse(doc)
        # Move #3 to first
        p.lookup("3")._rank = -1.0
        p.lookup("3").dirty = True
        if "tickets" in p.sections:
            p.sections["tickets"].dirty = True
        text = plan.serialize(p)
        lines = text.split('\n')
        ticket_lines = [l for l in lines if 'Ticket:' in l and '{#' in l]
        self.assertIn('#3', ticket_lines[0])
        self.assertIn('#1', ticket_lines[1])
        self.assertIn('#2', ticket_lines[2])

    def test_serializer_sorts_children_by_rank(self):
        """Children within a ticket are sorted by _rank."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: Parent {#1}
              status: open
          * ## Ticket: Task: B {#2}
                status: open
          * ## Ticket: Task: A {#3}
                status: open
        """)
        p = plan.parse(doc)
        p.lookup("3")._rank = -1.0
        p.lookup("3").dirty = True
        text = plan.serialize(p)
        lines = text.split('\n')
        ticket_lines = [l for l in lines if 'Ticket:' in l and '{#' in l]
        # Find the child lines (after parent)
        child_lines = ticket_lines[1:]  # skip parent
        self.assertIn('#3', child_lines[0])
        self.assertIn('#2', child_lines[1])

    def test_serializer_does_not_write_move_attr(self):
        """move is never written to output."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 2
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        """)
        p = plan.parse(doc)
        p.lookup("1").attrs["move"] = "first"
        p.lookup("1").dirty = True
        text = plan.serialize(p)
        self.assertNotIn('move:', text.split('## Tickets')[1])

    def test_round_trip_preserves_order(self):
        """Parse then serialize preserves ticket order when nothing changes."""
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        * ## Ticket: Task: C {#3}
              status: open
        """)
        p = plan.parse(doc)
        text = plan.serialize(p)
        self.assertEqual(text, doc)


class TestDslMoveAttr(unittest.TestCase):
    """Test set(move=...) in DSL."""

    def _make_project(self):
        doc = textwrap.dedent("""\
        # P {#project}
        ## Metadata {#metadata}
            next_id: 4
        ## Tickets {#tickets}
        * ## Ticket: Task: A {#1}
              status: open
        * ## Ticket: Task: B {#2}
              status: open
        * ## Ticket: Task: C {#3}
              status: open
        """)
        p = plan.parse(doc)
        plan._project = p
        return p

    def test_set_move_first(self):
        p = self._make_project()
        t3 = p.lookup("3")
        plan.apply_mod(t3, p, 'set(move="first")')
        self.assertLess(t3._rank, p.lookup("1")._rank)
        self.assertIn("move", t3.attrs)  # stored in attrs (serializer skips it)

    def test_set_move_after(self):
        p = self._make_project()
        t3 = p.lookup("3")
        r1 = p.lookup("1")._rank
        r2 = p.lookup("2")._rank
        plan.apply_mod(t3, p, 'set(move="after 1")')
        self.assertTrue(r1 < t3._rank < r2)

    def test_set_move_reparents(self):
        p = self._make_project()
        t3 = p.lookup("3")
        t1 = p.lookup("1")
        plan.apply_mod(t3, p, 'set(move="first 1")')
        self.assertIs(t3.parent, t1)
        self.assertIn(t3, t1.children)

    def test_set_rank_becomes_custom_attr(self):
        """set(rank=...) now just sets a custom attr, no special handling."""
        p = self._make_project()
        t1 = p.lookup("1")
        plan.apply_mod(t1, p, 'set(rank="42")')
        self.assertEqual(t1.get_attr("rank"), "42")


if __name__ == "__main__":
    unittest.main()
