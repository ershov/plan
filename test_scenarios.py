#!/usr/bin/env python3
"""Scenario tests for plan.py — deterministic end-to-end command sequences.

Runs plan.py commands via subprocess against a temp file, checking stdout,
stderr, exit code, and file state after each step.  Designed to catch
integration-level regressions that unit tests miss.

Usage:
    python3 test_scenarios.py [-v]
"""

import os
import re
import subprocess
import sys
import tempfile
import textwrap

PLAN_PY = os.path.join(os.path.dirname(__file__), "plan.py")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class ScenarioFailure(Exception):
    pass


class Plan:
    """Wrapper around a temp plan file for running commands and assertions."""

    def __init__(self, name):
        self.name = name
        self.fd, self.path = tempfile.mkstemp(suffix=".md", prefix="plan_test_")
        os.close(self.fd)
        os.unlink(self.path)  # start with no file
        self.step = 0
        self.errors = []

    def cleanup(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    # -- running commands --------------------------------------------------

    def run(self, *args, stdin=None):
        """Run plan.py with args, return (stdout, stderr, returncode)."""
        self.step += 1
        cmd = [sys.executable, PLAN_PY, "--file", self.path] + list(args)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            input=stdin,
        )
        return result.stdout, result.stderr, result.returncode

    def run_ok(self, *args, stdin=None):
        """Run and assert exit 0.  Returns stdout."""
        out, err, rc = self.run(*args, stdin=stdin)
        if rc != 0:
            self._fail(f"expected exit 0, got {rc}\n  args: {args}\n  stderr: {err}")
        return out

    def run_err(self, *args, stdin=None):
        """Run and assert non-zero exit.  Returns stderr."""
        out, err, rc = self.run(*args, stdin=stdin)
        if rc == 0:
            self._fail(f"expected error, got exit 0\n  args: {args}\n  stdout: {out}")
        return err

    # -- assertions --------------------------------------------------------

    def assert_out(self, out, *patterns):
        """Assert stdout contains all patterns (substring or regex)."""
        for pat in patterns:
            if isinstance(pat, re.Pattern):
                if not pat.search(out):
                    self._fail(f"stdout missing pattern {pat.pattern!r}\n  got: {out!r}")
            elif pat not in out:
                self._fail(f"stdout missing {pat!r}\n  got: {out!r}")

    def assert_not_out(self, out, *patterns):
        """Assert stdout does NOT contain any of the patterns."""
        for pat in patterns:
            if isinstance(pat, re.Pattern):
                if pat.search(out):
                    self._fail(f"stdout unexpectedly matched {pat.pattern!r}\n  got: {out!r}")
            elif pat in out:
                self._fail(f"stdout unexpectedly contains {pat!r}\n  got: {out!r}")

    def assert_out_exact(self, out, expected):
        """Assert stdout equals expected exactly."""
        if out != expected:
            self._fail(f"stdout mismatch\n  expected: {expected!r}\n  got:      {out!r}")

    def assert_out_lines(self, out, expected_lines):
        """Assert stdout lines match expected (ignoring trailing newline)."""
        got = out.rstrip("\n").split("\n") if out.strip() else []
        if got != expected_lines:
            self._fail(
                f"stdout lines mismatch\n"
                f"  expected: {expected_lines}\n"
                f"  got:      {got}"
            )

    def assert_err(self, err, *patterns):
        """Assert stderr contains all patterns."""
        for pat in patterns:
            if pat not in err:
                self._fail(f"stderr missing {pat!r}\n  got: {err!r}")

    def assert_file_contains(self, *patterns):
        """Assert the plan file contains all patterns."""
        text = self._read_file()
        for pat in patterns:
            if pat not in text:
                self._fail(f"file missing {pat!r}")

    def assert_file_not_contains(self, *patterns):
        """Assert the plan file does NOT contain any patterns."""
        text = self._read_file()
        for pat in patterns:
            if pat in text:
                self._fail(f"file unexpectedly contains {pat!r}")

    def assert_check_ok(self):
        """Run 'check' and assert it passes."""
        out = self.run_ok("check")
        if "ERROR" in out:
            self._fail(f"check found errors:\n{out}")

    # -- internal ----------------------------------------------------------

    def _read_file(self):
        with open(self.path) as f:
            return f.read()

    def _fail(self, msg):
        full = f"[{self.name} step {self.step}] {msg}"
        self.errors.append(full)


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

def scenario_basic_lifecycle(p):
    """Create, read, update, close, delete a ticket."""

    # Create a ticket
    out = p.run_ok("create", 'title="Login bug"')
    p.assert_out(out, "1")
    p.assert_check_ok()

    # Get it back
    out = p.run_ok("1", "get")
    p.assert_out(out, "Login bug", "status: open")

    # List it
    out = p.run_ok("list")
    p.assert_out(out, "#1 [open] Login bug")

    # Update via mod
    p.run_ok("1", "~", 'set(estimate="3h")')
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "3h")

    # Add body text
    p.run_ok("1", "add", "Needs investigation.")
    out = p.run_ok("1", "get")
    p.assert_out(out, "Needs investigation")

    # Replace body text
    p.run_ok("1", "replace", "--force", "Fixed the issue.")
    out = p.run_ok("1", "get")
    p.assert_out(out, "Fixed the issue")
    p.assert_not_out(out, "Needs investigation")

    # Set status
    p.run_ok("1", "status", "in-progress")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")

    # Close
    p.run_ok("1", "close", "done")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "done")

    # Delete
    p.run_ok("1", "del")
    out = p.run_ok("list")
    p.assert_not_out(out, "Login bug")
    p.assert_check_ok()


def scenario_hierarchy(p):
    """Build a parent/child tree and verify list, list -r, get -r."""

    p.run_ok("create", 'title="Epic"')           # 1
    p.run_ok("create", "1", 'title="Task A"')    # 2
    p.run_ok("create", "1", 'title="Task B"')    # 3
    p.run_ok("create", "2", 'title="Sub A1"')    # 4
    p.run_ok("create", 'title="Standalone"')       # 5

    # List all tickets (bare list shows full tree)
    out = p.run_ok("list")
    p.assert_out_lines(out, [
        "#1 [open] Epic",
        "  #2 [open] Task A",
        "    #4 [open] Sub A1",
        "  #3 [open] Task B",
        "#5 [open] Standalone",
    ])

    # List children of #1
    out = p.run_ok("children_of(1)", "list")
    p.assert_out(out, "#2 [open] Task A", "#3 [open] Task B")
    p.assert_not_out(out, "#4", "#5")

    # List #1 and descendants recursively
    out = p.run_ok("1", "-r", "list")
    p.assert_out(out, "#1 [open] Epic", "#2 [open] Task A",
                 "#4 [open] Sub A1", "#3 [open] Task B")
    p.assert_not_out(out, "#5")

    # List just ticket #1
    out = p.run_ok("1", "list")
    p.assert_out(out, "#1 [open] Epic")

    # List #1 -r: self + descendants
    out = p.run_ok("1", "-r", "list")
    p.assert_out_lines(out, [
        "#1 [open] Epic",
        "  #2 [open] Task A",
        "    #4 [open] Sub A1",
        "  #3 [open] Task B",
    ])

    # List #2 -r: self + descendants
    out = p.run_ok("2", "-r", "list")
    p.assert_out_lines(out, [
        "  #2 [open] Task A",
        "    #4 [open] Sub A1",
    ])

    # List leaf node
    out = p.run_ok("4", "list")
    p.assert_out(out, "#4 [open] Sub A1")

    # get -r: subtree dump
    out = p.run_ok("1", "-r", "get")
    p.assert_out(out, "Epic {#1}", "Task A {#2}", "Sub A1 {#4}", "Task B {#3}")

    # get -r on leaf is just that ticket
    out = p.run_ok("4", "-r", "get")
    p.assert_out(out, "Sub A1 {#4}")
    p.assert_not_out(out, "Task A", "Epic")

    p.assert_check_ok()


def scenario_semicolon_chaining(p):
    """Multiple commands in one invocation via ';'."""

    # Create + list in one shot
    out = p.run_ok("create", 'title="Alpha"', ";", "list")
    p.assert_out(out, "1", "#1 [open] Alpha")

    # Create child + get parent
    out = p.run_ok("create", "1", 'title="Beta"', ";", "1", "get")
    p.assert_out(out, "2", "Alpha")

    # Status + get in one shot
    p.run_ok("1", "status", "in-progress", ";", "1", "get")

    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")

    # Three creates in one shot
    out = p.run_ok(
        "create", 'title="C1"', ";",
        "create", 'title="C2"', ";",
        "create", 'title="C3"',
    )
    p.assert_out(out, "3", "4", "5")
    out = p.run_ok("list")
    p.assert_out(out, "#1 [in-progress] Alpha", "#3 [open] C1",
                 "#4 [open] C2", "#5 [open] C3")

    p.assert_check_ok()


def scenario_multi_create_tree(p):
    """Build a full tree with chained creates — reproduces the original report."""

    out = p.run_ok(
        "create", 'title="qwe"', ";",
        "create", "1", 'title="asd"', ";",
        "create", "2", 'title="zxc"', ";",
        "create", 'title="qwe2"', ";",
        "create", "4", 'title="asd2"',
    )
    p.assert_out(out, "1", "2", "3", "4", "5")

    # list: full tree
    out = p.run_ok("list")
    p.assert_out_lines(out, [
        "#1 [open] qwe",
        "  #2 [open] asd",
        "    #3 [open] zxc",
        "#4 [open] qwe2",
        "  #5 [open] asd2",
    ])

    # Every node: list shows the ticket, -r shows self + descendants
    for node, self_only, with_descendants in [
        ("1", ["#1 [open] qwe"],
              ["#1 [open] qwe", "  #2 [open] asd", "    #3 [open] zxc"]),
        ("2", ["  #2 [open] asd"],
              ["  #2 [open] asd", "    #3 [open] zxc"]),
        ("3", ["    #3 [open] zxc"],
              ["    #3 [open] zxc"]),
        ("4", ["#4 [open] qwe2"],
              ["#4 [open] qwe2", "  #5 [open] asd2"]),
        ("5", ["  #5 [open] asd2"],
              ["  #5 [open] asd2"]),
    ]:
        out = p.run_ok(f"{node}", "list")
        p.assert_out_lines(out, self_only)

        out = p.run_ok(f"{node}", "-r", "list")
        p.assert_out_lines(out, with_descendants)

    # get -r shows subtree
    out = p.run_ok("1", "-r", "get")
    p.assert_out(out, "qwe {#1}", "asd {#2}", "zxc {#3}")
    p.assert_not_out(out, "qwe2", "asd2")

    out = p.run_ok("4", "-r", "get")
    p.assert_out(out, "qwe2 {#4}", "asd2 {#5}")
    p.assert_not_out(out, "qwe {#1}")

    p.assert_check_ok()


def scenario_move_and_rank(p):
    """Move tickets between parents and reorder via rank."""

    p.run_ok("create", 'title="P1"')   # 1
    p.run_ok("create", 'title="P2"')   # 2
    p.run_ok("create", "1", 'title="C1"')  # 3
    p.run_ok("create", "1", 'title="C2"')  # 4

    # Children of #1
    out = p.run_ok("children_of(1)", "list")
    p.assert_out(out, "#3 [open] C1", "#4 [open] C2")

    # Move C2 to P2
    p.run_ok("move", "4", "last", "2")
    out = p.run_ok("children_of(1)", "list")
    p.assert_out(out, "#3 [open] C1")
    p.assert_not_out(out, "#4")
    out = p.run_ok("children_of(2)", "list")
    p.assert_out(out, "#4 [open] C2")

    # Move C2 before P1 (makes it a top-level sibling)
    p.run_ok("move", "4", "before", "1")
    out = p.run_ok("list")
    p.assert_out(out, "#1 [open] P1", "#2 [open] P2", "#4 [open] C2")

    # Move P2 first
    p.run_ok("2", "move", "first")
    out = p.run_ok("list")
    lines = out.rstrip("\n").split("\n")
    if lines[0] != "#2 [open] P2":
        p._fail(f"move first: expected #2 first, got {lines[0]!r}")

    # Move P1 after P2
    p.run_ok("1", "move", "after", "2")
    out = p.run_ok("list")
    lines = out.rstrip("\n").split("\n")
    # P2 first, then P1
    if lines[0] != "#2 [open] P2" or lines[1] != "#1 [open] P1":
        p._fail(f"move after: expected [P2, P1, ...], got {lines}")

    p.assert_check_ok()


def scenario_comments(p):
    """Add, read, delete comments."""

    p.run_ok("create", 'title="Ticket"')

    # Add comments
    p.run_ok("1", "comment", "add", "First comment.")
    p.run_ok("1", "comment", "add", "Second comment.")

    # Read comments
    out = p.run_ok("1", "comment", "get")
    p.assert_out(out, "First comment", "Second comment")

    # Comment shows in get
    out = p.run_ok("1", "get")
    p.assert_out(out, "Ticket")

    # Delete comments
    p.run_ok("1", "comment", "del")
    out = p.run_ok("1", "comment", "get")
    p.assert_not_out(out, "First comment", "Second comment")

    p.assert_check_ok()


def scenario_attributes(p):
    """Get, set, replace, delete attributes."""

    p.run_ok("create", 'title="Task", estimate="3h"')

    # Get attribute
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "3h")

    # Replace attribute (value before --force)
    p.run_ok("1", "attr", "estimate", "replace", "1h", "--force")
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "1h")

    # Add links
    p.run_ok("create", 'title="Other"')
    p.run_ok("1", "attr", "links", "add", "blocked:#2")
    out = p.run_ok("1", "attr", "links", "get")
    p.assert_out(out, "blocked:#2")

    # Mirror link created
    out = p.run_ok("2", "attr", "links", "get")
    p.assert_out(out, "blocking:#1")

    # Delete attribute
    p.run_ok("1", "attr", "estimate", "del")
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_not_out(out, "1h")

    p.assert_check_ok()


def scenario_mod_dsl(p):
    """Test mod/~ with various DSL expressions."""

    p.run_ok("create", 'title="Modable", status="open"')

    # set single
    p.run_ok("1", "~", 'set(estimate="2h")')
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "2h")

    # set multiple
    p.run_ok("1", "~", 'set(estimate="1h", status="in-progress")')
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "1h")

    # add text
    p.run_ok("1", "~", 'add(text="Added via DSL.")')
    out = p.run_ok("1", "get")
    p.assert_out(out, "Added via DSL")

    # set text (replace)
    p.run_ok("1", "~", 'set(text="Replaced via DSL.")')
    out = p.run_ok("1", "get")
    p.assert_out(out, "Replaced via DSL")
    p.assert_not_out(out, "Added via DSL")

    # delete attribute
    p.run_ok("1", "~", 'delete("assignee")')
    # (no error even if missing)

    # chained expressions
    p.run_ok("1", "~", '[set(estimate="4h"), set(status="open")]')
    out = p.run_ok("1", "attr", "estimate", "get")
    p.assert_out(out, "4h")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "open")

    p.assert_check_ok()


def scenario_list_filters(p):
    """Test list with various filters."""

    p.run_ok("create", 'title="Bug in login", estimate="1h", status="open"')
    p.run_ok("create", 'title="Feature request", estimate="3h", status="open"')
    p.run_ok("create", 'title="Bug in API", estimate="2h", status="done"')

    # --title filter
    out = p.run_ok("list", "--title", "Bug")
    p.assert_out(out, "#1 [open] Bug in login", "#3 [done] Bug in API")
    p.assert_not_out(out, "Feature")

    # -q filter
    out = p.run_ok("list", "-q", 'estimate == "1h"')
    p.assert_out(out, "#1 [open] Bug in login")
    p.assert_not_out(out, "#2", "#3")

    out = p.run_ok("list", "-q", 'status == "done"')
    p.assert_out(out, "#3 [done] Bug in API")
    p.assert_not_out(out, "#1", "#2")

    # -n limit
    out = p.run_ok("list", "-n", "1")
    lines = out.rstrip("\n").split("\n")
    if len(lines) != 1:
        p._fail(f"-n 1: expected 1 line, got {len(lines)}")

    # --format
    out = p.run_ok("list", "--format", 'f"[{status}] #{id} {title}"')
    p.assert_out(out, "[open] #1 Bug in login")
    p.assert_out(out, "[done] #3 Bug in API")

    # Add body text for --text filter
    p.run_ok("1", "add", "Reproduction steps available.")
    out = p.run_ok("list", "--text", "Reproduction")
    p.assert_out(out, "#1 [open] Bug in login")
    p.assert_not_out(out, "#2", "#3")

    p.assert_check_ok()


def scenario_recursive_delete(p):
    """Delete with and without -r flag."""

    p.run_ok("create", 'title="Parent"')
    p.run_ok("create", "1", 'title="Child"')
    p.run_ok("create", "2", 'title="Grandchild"')

    # Cannot delete parent without -r
    err = p.run_err("1", "del")
    p.assert_err(err, "child ticket", "-r")

    # Child with children also blocked
    err = p.run_err("2", "del")
    p.assert_err(err, "child ticket", "-r")

    # Leaf can be deleted without -r
    p.run_ok("3", "del")
    out = p.run_ok("list", "-r")
    p.assert_not_out(out, "Grandchild")

    # Now #2 is a leaf, can be deleted
    p.run_ok("2", "del")

    # Now #1 is a leaf
    p.run_ok("1", "del")

    out = p.run_ok("list")
    p.assert_out_exact(out, "")

    p.assert_check_ok()


def scenario_recursive_delete_forced(p):
    """Delete subtree with -r."""

    p.run_ok("create", 'title="Root"')
    p.run_ok("create", "1", 'title="Child"')
    p.run_ok("create", "2", 'title="Grandchild"')
    p.run_ok("create", 'title="Survivor"')

    # Delete root with -r: removes entire subtree
    p.run_ok("1", "-r", "del")

    out = p.run_ok("list")
    p.assert_out(out, "#4 [open] Survivor")
    p.assert_not_out(out, "Root", "Child", "Grandchild")

    # Deleted IDs should not be found
    err = p.run_err("1", "get")
    p.assert_err(err, "not found")

    p.assert_check_ok()


def scenario_project_sections(p):
    """Manage project-level sections."""

    p.run_ok("create", 'title="placeholder"')

    # Project info shows header
    out = p.run_ok("project")
    p.assert_out(out, "Project")

    # Add a section
    p.run_ok("project", "description", "add", "Project overview.")
    out = p.run_ok("project", "description", "get")
    p.assert_out(out, "Project overview")

    # Section shows in file
    p.assert_file_contains("## Description")

    # Replace section
    p.run_ok("project", "description", "replace", "--force", "New overview.")
    out = p.run_ok("project", "description", "get")
    p.assert_out(out, "New overview")
    p.assert_not_out(out, "Project overview")

    # Append to section
    p.run_ok("project", "description", "add", "Extra details.")
    out = p.run_ok("project", "description", "get")
    p.assert_out(out, "New overview", "Extra details")

    p.assert_check_ok()


def scenario_multi_target(p):
    """Operations on multiple targets at once."""

    p.run_ok("create", 'title="T1"')
    p.run_ok("create", 'title="T2"')
    p.run_ok("create", 'title="T3"')

    # Multi-get
    out = p.run_ok("1", "2", "get")
    p.assert_out(out, "T1", "T2")
    p.assert_not_out(out, "T3")

    # Multi-status
    p.run_ok("1", "2", "status", "in-progress")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")
    out = p.run_ok("2", "attr", "status", "get")
    p.assert_out(out, "in-progress")
    out = p.run_ok("3", "attr", "status", "get")
    p.assert_out(out, "open")

    # Multi-close
    p.run_ok("1", "2", "3", "close", "done")
    for i in ["1", "2", "3"]:
        out = p.run_ok(f"{i}", "attr", "status", "get")
        p.assert_out(out, "done")

    # Multi-mod
    p.run_ok("1", "2", "~", 'set(estimate="5h")')
    for i in ["1", "2"]:
        out = p.run_ok(f"{i}", "attr", "estimate", "get")
        p.assert_out(out, "5h")
    out = p.run_ok("3", "attr", "estimate", "get")
    p.assert_not_out(out, "5h")

    p.assert_check_ok()


def scenario_id_forms(p):
    """Bare integer ID form works."""
    p.run_ok("create", 'title="Target"')
    # bare N form
    out = p.run_ok("1", "get")
    p.assert_out(out, "Target")
    # bare N in commands
    p.run_ok("1", "status", "in-progress")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")


def scenario_errors(p):
    """Error handling for invalid commands."""

    p.run_ok("create", 'title="Task"')

    # Unknown ID
    err = p.run_err("999", "get")
    p.assert_err(err, "not found")

    # Replace without --force
    err = p.run_err("1", "replace", "text")
    p.assert_err(err, "--force")

    # Create without title
    err = p.run_err("create", 'estimate="1h"')
    p.assert_err(err, "title")

    # Delete ticket with children without -r
    p.run_ok("create", "1", 'title="Child"')
    err = p.run_err("1", "del")
    p.assert_err(err, "-r")


def scenario_create_quiet(p):
    """--quiet suppresses ticket ID output."""

    out = p.run_ok("create", "--quiet", 'title="Silent"')
    p.assert_out_exact(out, "")

    # But ticket was created
    out = p.run_ok("list")
    p.assert_out(out, "#1 [open] Silent")


def scenario_help(p):
    """Help system works."""

    # General help
    out = p.run_ok("help")
    p.assert_out(out, "Markdown Ticket Tracker")

    # Per-command help
    out = p.run_ok("help", "list")
    p.assert_out(out, "plan list")

    out = p.run_ok("help", "create")
    p.assert_out(out, "plan create")

    # DSL help
    out = p.run_ok("help", "dsl")
    p.assert_out(out, "set(")

    # h alias
    out = p.run_ok("h")
    p.assert_out(out, "Markdown Ticket Tracker")

    # Unknown command: error only, no general help dump
    out = p.run_ok("help", "nonexistent")
    p.assert_out(out, "Unknown command")
    p.assert_not_out(out, "Markdown Ticket Tracker")


def scenario_check_fix(p):
    """Check and fix detect and repair issues."""

    p.run_ok("create", 'title="Good ticket"')
    out = p.run_ok("check")
    p.assert_out(out, "OK")

    # Manually corrupt the file: duplicate next_id
    text = open(p.path).read()
    text = text.replace("next_id: 2", "next_id: 1")
    with open(p.path, "w") as f:
        f.write(text)

    out = p.run_ok("check")
    p.assert_out(out, "ERROR")

    # Fix it
    p.run_ok("fix")
    out = p.run_ok("check")
    p.assert_out(out, "OK")


def scenario_body_indentation(p):
    """Body text is properly indented in the file."""

    p.run_ok("create", 'title="Root", text="Root body text."')
    p.run_ok("create", "1", 'title="Child"')
    p.run_ok("2", "add", "Child body text.")

    p.assert_check_ok()

    # Verify indentation in file
    text = open(p.path).read()
    for line in text.split("\n"):
        if "Root body text" in line:
            indent = len(line) - len(line.lstrip())
            if indent < 2:
                p._fail(f"Root body indent {indent} < 2: {line!r}")
        if "Child body text" in line:
            indent = len(line) - len(line.lstrip())
            if indent < 4:
                p._fail(f"Child body indent {indent} < 4: {line!r}")


def scenario_multiline_text(p):
    """Multiline body text roundtrips correctly."""

    p.run_ok("create", 'title="Multi"')
    p.run_ok("1", "add", "Line one.")
    p.run_ok("1", "add", "Line two.")
    p.run_ok("1", "add", "Line three.")

    out = p.run_ok("1", "get")
    p.assert_out(out, "Line one", "Line two", "Line three")

    # Replace with multiline via mod
    p.run_ok("1", "~", r'set(text="Alpha\nBeta\nGamma")')
    out = p.run_ok("1", "get")
    p.assert_out(out, "Alpha", "Beta", "Gamma")
    p.assert_not_out(out, "Line one")

    p.assert_check_ok()


def scenario_list_ready(p):
    """List ready: open tickets with no open blockers."""

    p.run_ok("create", 'title="Blocked"')
    p.run_ok("create", 'title="Blocker"')
    p.run_ok("1", "attr", "links", "add", "blocked:#2")

    # #1 is blocked by #2 (open), so not ready
    out = p.run_ok("list", "ready")
    p.assert_out(out, "#2 [open] Blocker")
    p.assert_not_out(out, "Blocked")

    # Close blocker
    p.run_ok("2", "close")
    out = p.run_ok("list", "ready")
    p.assert_out(out, "#1 [open] Blocked")


def scenario_stdin_file_input(p):
    """Add and replace from stdin (-)."""

    p.run_ok("create", 'title="Target"')

    # Add from stdin
    p.run_ok("1", "add", "-", stdin="From stdin.")
    out = p.run_ok("1", "get")
    p.assert_out(out, "From stdin")

    # Replace from stdin
    p.run_ok("1", "replace", "--force", "-", stdin="Replaced from stdin.")
    out = p.run_ok("1", "get")
    p.assert_out(out, "Replaced from stdin")
    p.assert_not_out(out, "From stdin.")

    p.assert_check_ok()


def scenario_recursive_verbs_and_commands(p):
    """Test -r and -q flags on verbs and target commands."""

    # Build tree: #1 -> #2 (Bug), #1 -> #3, #2 -> #4
    p.run_ok("create", 'title="Epic"')
    p.run_ok("create", "1", 'title="Bug fix", type="Bug"')
    p.run_ok("create", "1", 'title="Feature"')
    p.run_ok("create", "2", 'title="Sub-bug", type="Bug"')

    # ----- mod -r: set estimate on entire subtree -----
    p.run_ok("1", "-r", "~", 'set(estimate="2h")')
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "attr", "estimate", "get")
        p.assert_out(out, "2h")

    # ----- mod -r -q: set estimate only on Bugs -----
    p.run_ok("1", "-r", "-q", 'type=="Bug"', "~", 'set(estimate="1h")')
    # Bugs (#2, #4) get estimate 1h; others stay at 2h
    for tid, expected in [("1", "2h"), ("2", "1h"), ("3", "2h"), ("4", "1h")]:
        out = p.run_ok(f"{tid}", "attr", "estimate", "get")
        p.assert_out(out, expected)

    # ----- status -r: set status on subtree -----
    p.run_ok("1", "-r", "status", "in-progress")
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "attr", "status", "get")
        p.assert_out(out, "in-progress")

    # ----- close -r -q: close only Bugs -----
    p.run_ok("1", "-r", "-q", 'type=="Bug"', "close", "fixed")
    out = p.run_ok("2", "attr", "status", "get")
    p.assert_out(out, "fixed")
    out = p.run_ok("4", "attr", "status", "get")
    p.assert_out(out, "fixed")
    # Non-bugs still in-progress
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")
    out = p.run_ok("3", "attr", "status", "get")
    p.assert_out(out, "in-progress")

    # ----- add -r: add body text to all -----
    p.run_ok("1", "-r", "add", "Sprint 5 note.")
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "get")
        p.assert_out(out, "Sprint 5 note")

    # ----- replace -r --force: replace body on all -----
    p.run_ok("1", "-r", "replace", "--force", "Cleared.")
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "get")
        p.assert_out(out, "Cleared")
        p.assert_not_out(out, "Sprint 5 note")

    # ----- comment add -r: add comment to all -----
    p.run_ok("1", "-r", "comment", "add", "Reviewed.")
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "comment", "get")
        p.assert_out(out, "Reviewed")

    # ----- attr replace -r: set attr on all -----
    p.run_ok("1", "-r", "attr", "estimate", "replace", "--force", "3h")
    for tid in ["1", "2", "3", "4"]:
        out = p.run_ok(f"{tid}", "attr", "estimate", "get")
        p.assert_out(out, "3h")

    # ----- attr get -r: get attr from all -----
    out = p.run_ok("1", "-r", "attr", "estimate", "get")
    lines = [l for l in out.strip().split("\n") if l.strip()]
    if len(lines) != 4:
        p._fail(f"attr get -r: expected 4 lines, got {len(lines)}: {lines}")

    # ----- get -r -q: show only matching tickets -----
    out = p.run_ok("1", "-r", "-q", 'type=="Bug"', "get")
    p.assert_out(out, "Bug fix")
    p.assert_out(out, "Sub-bug")
    p.assert_not_out(out, "Epic")
    p.assert_not_out(out, "Feature")

    # ----- del -r -q: delete only closed (Bug) tickets -----
    p.run_ok("1", "-r", "-q", 'status=="fixed"', "del")
    # #2 and #4 (fixed) should be gone
    err = p.run_err("2", "get")
    p.assert_err(err, "not found")
    err = p.run_err("4", "get")
    p.assert_err(err, "not found")
    # #1 and #3 survive
    out = p.run_ok("1", "get")
    p.assert_out(out, "Epic")
    out = p.run_ok("3", "get")
    p.assert_out(out, "Feature")

    p.assert_check_ok()


def scenario_q_without_r(p):
    """Test -q flag without -r: filters existing targets."""

    p.run_ok("create", 'title="A", type="Bug"')
    p.run_ok("create", 'title="B", type="Feature"')
    p.run_ok("create", 'title="C", type="Bug"')

    # Close only bugs among the 3 targets
    p.run_ok("1", "2", "3", "-q", 'type=="Bug"', "close")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "done")
    out = p.run_ok("2", "attr", "status", "get")
    p.assert_out(out, "open")  # Feature not matched
    out = p.run_ok("3", "attr", "status", "get")
    p.assert_out(out, "done")

    p.assert_check_ok()


def scenario_move_before_after(p):
    """Move ticket before/after sibling."""

    p.run_ok("create", 'title="A"')
    p.run_ok("create", 'title="B"')
    p.run_ok("create", 'title="C"')

    # Move C before A
    p.run_ok("move", "3", "before", "1")
    out = p.run_ok("list")
    lines = out.rstrip("\n").split("\n")
    titles = [l.rsplit("] ", 1)[-1] for l in lines]
    if titles.index("C") > titles.index("A"):
        p._fail(f"move before: C should be before A, got {titles}")

    # Move A after C
    p.run_ok("move", "1", "after", "3")
    out = p.run_ok("list")
    lines = out.rstrip("\n").split("\n")
    titles = [l.rsplit("] ", 1)[-1] for l in lines]
    if titles.index("C") > titles.index("A"):
        p._fail(f"move after: A should be after C, got {titles}")

    p.assert_check_ok()


def scenario_verb_selector_order(p):
    """Selectors and verbs can appear in either order."""

    p.run_ok("create", 'title="Alpha"')
    p.run_ok("create", 'title="Beta"')
    p.run_ok("create", "1", 'title="Child"')

    # get: both orders
    out1 = p.run_ok("1", "get")
    out2 = p.run_ok("get", "1")
    p.assert_out(out1, "Alpha")
    p.assert_out(out2, "Alpha")

    # list: both orders show the ticket itself
    out1 = p.run_ok("1", "list")
    out2 = p.run_ok("list", "1")
    p.assert_out(out1, "#1 [open] Alpha")
    p.assert_out(out2, "#1 [open] Alpha")

    # list with -r: both orders show ticket + descendants
    out1 = p.run_ok("1", "-r", "list")
    out2 = p.run_ok("list", "1", "-r")
    p.assert_out(out1, "#3 [open] Child")
    p.assert_out(out2, "#3 [open] Child")

    # del: verb first
    p.run_ok("create", 'title="Temp"')
    p.run_ok("del", "4")
    err = p.run_err("get", "4")
    p.assert_err(err, "not found")

    # multi-target get: verb first
    out = p.run_ok("get", "1", "2")
    p.assert_out(out, "Alpha", "Beta")

    # add: verb first with arg then targets
    p.run_ok("add", "Extra line.", "1", "2")
    out = p.run_ok("get", "1")
    p.assert_out(out, "Extra line.")
    out = p.run_ok("get", "2")
    p.assert_out(out, "Extra line.")

    # comment: verb first
    p.run_ok("add", "A note.", "1", "comment")
    out = p.run_ok("get", "1", "comment")
    p.assert_out(out, "A note.")

    # attr: verb first
    out = p.run_ok("get", "1", "attr", "status")
    p.assert_out(out, "open")

    # mod: verb first
    p.run_ok("~", 'set(estimate="7h")', "1")
    out = p.run_ok("get", "1", "attr", "estimate")
    p.assert_out(out, "7h")

    # status: verb first with selectors
    p.run_ok("status", "1", "in-progress")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "in-progress")

    # status: verb first, multi-target
    p.run_ok("status", "1", "2", "planned")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "planned")
    out = p.run_ok("2", "attr", "status", "get")
    p.assert_out(out, "planned")

    # close: verb first with selector
    p.run_ok("close", "1", "done")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "done")

    # close: verb first, no reason (default done)
    p.run_ok("1", "reopen")
    p.run_ok("close", "1")
    out = p.run_ok("1", "attr", "status", "get")
    p.assert_out(out, "done")

    p.assert_check_ok()


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

ALL_SCENARIOS = [
    scenario_basic_lifecycle,
    scenario_hierarchy,
    scenario_semicolon_chaining,
    scenario_multi_create_tree,
    scenario_move_and_rank,
    scenario_comments,
    scenario_attributes,
    scenario_mod_dsl,
    scenario_list_filters,
    scenario_recursive_delete,
    scenario_recursive_delete_forced,
    scenario_project_sections,
    scenario_multi_target,
    scenario_id_forms,
    scenario_errors,
    scenario_create_quiet,
    scenario_help,
    scenario_check_fix,
    scenario_body_indentation,
    scenario_multiline_text,
    scenario_list_ready,
    scenario_stdin_file_input,
    scenario_move_before_after,
    scenario_recursive_verbs_and_commands,
    scenario_q_without_r,
    scenario_verb_selector_order,
]


def main():
    verbose = "-v" in sys.argv

    total = 0
    passed = 0
    failed = 0
    all_errors = []

    for fn in ALL_SCENARIOS:
        name = fn.__name__
        total += 1
        p = Plan(name)
        try:
            fn(p)
            if p.errors:
                failed += 1
                all_errors.extend(p.errors)
                status = "FAIL"
            else:
                passed += 1
                status = "ok"
        except Exception as e:
            failed += 1
            all_errors.append(f"[{name}] EXCEPTION: {e}")
            status = "FAIL"
        finally:
            p.cleanup()

        if verbose or status == "FAIL":
            print(f"  {name} ... {status}")
            if status == "FAIL" and p.errors:
                for err in p.errors:
                    print(f"    {err}")

    print()
    print(f"{total} scenarios, {passed} passed, {failed} failed")

    if all_errors:
        print()
        print("Failures:")
        for err in all_errors:
            print(f"  {err}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
