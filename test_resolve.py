#!/usr/bin/env python3
"""End-to-end tests for `plan resolve` (two-way structural recovery).

`resolve` reconstructs the sides from a plan file containing raw git conflict
markers, runs the merge engine, and writes the reconciled file. When conflicts
remain it reuses the merge `.reject` flow (so `plan merge --resolve` can finish
per-field). Because the conflict path writes snapshots inside `.git`, these
tests drive the built CLI via subprocess inside throwaway git repos.

Run from the project root:  python3 -m unittest test_resolve
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

PLAN_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan.py")


def _run(args, cwd):
    """Run `plan <args>` in cwd; return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, PLAN_PY] + args,
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _RepoCase(unittest.TestCase):
    """Base: a temp git repo with a .PLAN.md the test writes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plan-resolve-")
        for args in (["init", "-q"],
                     ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "Tester"]):
            subprocess.run(["git"] + args, cwd=self.tmp, check=True,
                           capture_output=True, text=True)
        self.plan_path = os.path.join(self.tmp, ".PLAN.md")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_plan(self, text):
        with open(self.plan_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(text))

    def read_plan(self):
        with open(self.plan_path, encoding="utf-8") as f:
            return f.read()

    def reject_exists(self):
        return os.path.exists(self.plan_path + ".reject")

    def options_text(self):
        """Read the persisted merge options file (under the namespaced state dir).

        State now lives in '.git/plan-merge/<output-key>/', so search for the
        single 'options' file beneath '.git/plan-merge'.
        """
        base = os.path.join(self.tmp, ".git", "plan-merge")
        for root, _dirs, files in os.walk(base):
            if "options" in files:
                with open(os.path.join(root, "options"), encoding="utf-8") as f:
                    return f.read()
        return None

    def assertNoMarkers(self):
        text = self.read_plan()
        for marker in ("<<<<<<<", "=======", ">>>>>>>", "|||||||"):
            self.assertNotIn(marker, text,
                             "conflict marker %r left in file" % marker)


# ---------------------------------------------------------------------------
# No markers
# ---------------------------------------------------------------------------

class TestResolveNoMarkers(_RepoCase):
    def test_no_markers_is_noop(self):
        self.write_plan("""\
            # Project: Demo {#project}

            ## Metadata {#metadata}

                next_id: 2

            ## Tickets {#tickets}

            * ## Ticket: Task: Clean {#1}

                  status: open
            """)
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("no conflicts found", out)
        self.assertFalse(self.reject_exists())


# ---------------------------------------------------------------------------
# Non-conflicting markers -> clean merge
# ---------------------------------------------------------------------------

class TestResolveCleanMarkers(_RepoCase):
    def test_distinct_added_tickets_clean(self):
        # ours adds #2, theirs adds #3 (distinct ids) -> both kept, no conflict.
        self.write_plan("""\
            # Project: Demo {#project}

            ## Metadata {#metadata}

                next_id: 4

            ## Tickets {#tickets}

            * ## Ticket: Task: Shared {#1}

                  status: open

            <<<<<<< HEAD
            * ## Ticket: Task: MineOnly {#2}

                  status: open
            =======
            * ## Ticket: Task: TheirsOnly {#3}

                  status: done
            >>>>>>> branch
            """)
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertNoMarkers()
        self.assertFalse(self.reject_exists())
        text = self.read_plan()
        self.assertIn("MineOnly {#2}", text)
        self.assertIn("TheirsOnly {#3}", text)
        # reconciled file reparses
        rc2, _o, _e = _run(["1", "get", "title"], self.tmp)
        self.assertEqual(rc2, 0)


# ---------------------------------------------------------------------------
# Conflicting markers -> file cleaned to mine + .reject, then merge --resolve
# ---------------------------------------------------------------------------

class TestResolveConflictThenFinish(_RepoCase):
    CONFLICTED = """\
        # Project: Demo {#project}

        ## Metadata {#metadata}

            next_id: 2

        ## Tickets {#tickets}

        * ## Ticket: Task: Shared {#1}

        <<<<<<< HEAD
              status: in-progress
        =======
              status: done
        >>>>>>> branch
        """

    def test_conflict_writes_reject_exit1(self):
        self.write_plan(self.CONFLICTED)
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 1, "expected exit 1 on remaining conflicts")
        self.assertNoMarkers()                       # primary goal: file valid
        self.assertTrue(self.reject_exists())
        # file defaulted to mine
        self.assertIn("status: in-progress", self.read_plan())
        # best-effort messaging
        self.assertIn("could not be auto-resolved", err)

    def test_finish_with_merge_resolve_keep_theirs(self):
        self.write_plan(self.CONFLICTED)
        rc, _o, _e = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 1)
        # Edit the .reject to keep the `from` (theirs) side (delete the `to`
        # indicator line and its content).
        rp = self.plan_path + ".reject"
        with open(rp, encoding="utf-8") as f:
            lines = f.read().split("\n")
        kept = []
        drop = False
        for ln in lines:
            if ln.startswith("--- to"):
                drop = True
                continue
            if ln.startswith("--- from"):
                drop = False
                continue
            if drop:
                continue
            kept.append(ln)
        with open(rp, "w", encoding="utf-8") as f:
            f.write("\n".join(kept))

        rc2, out2, err2 = _run(["merge", "--resolve"], self.tmp)
        self.assertEqual(rc2, 0, err2)
        self.assertIn("status: done", self.read_plan())   # theirs won
        self.assertFalse(self.reject_exists())            # state cleaned up

    def test_options_persist_two_way(self):
        self.write_plan(self.CONFLICTED)
        rc, _o, _e = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 1)
        body = self.options_text()
        self.assertIsNotNone(body, "options file should exist")
        self.assertIn("two_way=true", body)


# ---------------------------------------------------------------------------
# diff3 (base section) -> three-way path
# ---------------------------------------------------------------------------

class TestResolveDiff3(_RepoCase):
    def test_diff3_clean_three_way(self):
        # base: open/nobody; mine changes status only; theirs changes assignee
        # only -> three-way merges cleanly (two-way would conflict on both).
        self.write_plan("""\
            # Project: Demo {#project}

            ## Metadata {#metadata}

                next_id: 2

            ## Tickets {#tickets}

            * ## Ticket: Task: Shared {#1}

            <<<<<<< HEAD
                  status: in-progress
                  assignee: nobody
            ||||||| base
                  status: open
                  assignee: nobody
            =======
                  status: open
                  assignee: bob
            >>>>>>> branch
            """)
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertNoMarkers()
        self.assertFalse(self.reject_exists())
        self.assertIn("three-way recovery", out)
        text = self.read_plan()
        self.assertIn("status: in-progress", text)   # mine-only change
        self.assertIn("assignee: bob", text)          # theirs-only change

    def test_diff3_genuine_conflict_uses_base(self):
        # Same field diverges on both relative to base -> conflict, .reject.
        self.write_plan("""\
            # Project: Demo {#project}

            ## Metadata {#metadata}

                next_id: 2

            ## Tickets {#tickets}

            * ## Ticket: Task: Shared {#1}

            <<<<<<< HEAD
                  status: in-progress
            ||||||| base
                  status: open
            =======
                  status: done
            >>>>>>> branch
            """)
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 1, err)
        self.assertNoMarkers()
        self.assertTrue(self.reject_exists())
        body = self.options_text()
        self.assertIsNotNone(body, "options file should exist")
        self.assertIn("two_way=false", body)  # three-way mode persisted


# ---------------------------------------------------------------------------
# In-progress guard
# ---------------------------------------------------------------------------

class TestResolveInProgressGuard(_RepoCase):
    def test_refuses_when_reject_present(self):
        self.write_plan("""\
            # Project: Demo {#project}

            ## Tickets {#tickets}

            * ## Ticket: Task: X {#1}

            <<<<<<< HEAD
                  status: open
            =======
                  status: done
            >>>>>>> b
            """)
        # Simulate a merge in progress.
        open(self.plan_path + ".reject", "w").close()
        rc, out, err = _run(["resolve"], self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("merge is already in progress", err)


if __name__ == "__main__":
    unittest.main()
