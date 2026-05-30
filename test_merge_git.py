#!/usr/bin/env python3
"""Tests for the merge git plumbing layer (src/117-merge-git.py).

Run from the project root with:  python3 -m unittest test_merge_git

These tests exercise the REAL generated module (`plan.py`) against REAL throwaway
git repositories created with subprocess + tempfile. Each repo is initialized,
gets a local user.name/user.email, an initial `.PLAN.md` commit, then branches
diverge on both sides. Every function under test takes an explicit repo_root and
runs git with cwd=repo_root, so nothing here relies on the process cwd.

The whole module is skipped (SkipTest) when `git` is unavailable. Temp dirs are
always cleaned up.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

import plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


GIT_OK = _git_available()


PLAN_BASE = """\
# Project: T {#project}

## Metadata {#metadata}

    next_id: 3

## Tickets {#tickets}

  * ## Ticket: Task: First {#1}
        status: open
    Body of first.

  * ## Ticket: Task: Second {#2}
        status: open
    Body of second.
"""


def _run(args, cwd, input_text=None, check=True):
    proc = subprocess.run(
        args, cwd=cwd, input=input_text,
        capture_output=True, text=True, timeout=30,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            "command failed: %s\n%s" % (" ".join(args), proc.stderr))
    return proc


def _read(path):
    """Read a file's contents, '' if it doesn't exist."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


class GitRepoTestCase(unittest.TestCase):
    """Base class providing a fresh throwaway git repo per test."""

    def setUp(self):
        if not GIT_OK:
            raise unittest.SkipTest("git is not available")
        self.repo = tempfile.mkdtemp(prefix="plan-merge-git-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.plan_path = os.path.join(self.repo, ".PLAN.md")
        _run(["git", "init", "-q"], self.repo)
        _run(["git", "config", "user.email", "t@example.com"], self.repo)
        _run(["git", "config", "user.name", "Tester"], self.repo)
        _run(["git", "config", "commit.gpgsign", "false"], self.repo)
        # Stable default branch name regardless of git's init.defaultBranch.
        _run(["git", "checkout", "-q", "-b", "main"], self.repo, check=False)

    # -- repo construction utilities --

    def write_plan(self, text):
        with open(self.plan_path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_plan(self):
        with open(self.plan_path, encoding="utf-8") as f:
            return f.read()

    def commit(self, msg):
        _run(["git", "add", "-A"], self.repo)
        _run(["git", "commit", "-q", "-m", msg], self.repo)

    def commit_initial(self, text=PLAN_BASE):
        self.write_plan(text)
        self.commit("initial plan")

    def checkout_new(self, name):
        _run(["git", "checkout", "-q", "-b", name], self.repo)

    def checkout(self, name):
        _run(["git", "checkout", "-q", name], self.repo)


# ---------------------------------------------------------------------------
# Basic git query helpers
# ---------------------------------------------------------------------------

class GitQueryHelpersTest(GitRepoTestCase):

    def test_repo_root(self):
        self.commit_initial()
        root = plan.git_repo_root(self.repo)
        self.assertEqual(os.path.realpath(root), os.path.realpath(self.repo))

    def test_ref_exists_and_rev_parse(self):
        self.commit_initial()
        self.assertTrue(plan.git_ref_exists(self.repo, "HEAD"))
        self.assertTrue(plan.git_ref_exists(self.repo, "main"))
        self.assertFalse(plan.git_ref_exists(self.repo, "nope-no-such"))
        full = plan.git_rev_parse(self.repo, "HEAD")
        short = plan.git_short_sha(self.repo, "HEAD")
        self.assertEqual(len(full), 40)
        self.assertTrue(full.startswith(short))

    def test_current_branch(self):
        self.commit_initial()
        self.assertEqual(plan.git_current_branch(self.repo), "main")
        # Detached HEAD -> None.
        head = plan.git_rev_parse(self.repo, "HEAD")
        _run(["git", "checkout", "-q", head], self.repo)
        self.assertIsNone(plan.git_current_branch(self.repo))

    def test_git_show_present_and_absent(self):
        self.commit_initial()
        text = plan.git_show(self.repo, "HEAD", ".PLAN.md")
        self.assertEqual(text, PLAN_BASE)
        self.assertIsNone(plan.git_show(self.repo, "HEAD", "does-not-exist.md"))

    def test_merge_base(self):
        self.commit_initial()
        base_sha = plan.git_rev_parse(self.repo, "HEAD")
        self.checkout_new("feature")
        self.write_plan(PLAN_BASE.replace("Body of first.", "Edited on feature."))
        self.commit("feature edit")
        self.checkout("main")
        self.write_plan(PLAN_BASE.replace("Body of second.", "Edited on main."))
        self.commit("main edit")
        mb = plan.git_merge_base(self.repo, "HEAD", "feature")
        self.assertEqual(mb, base_sha)


# ---------------------------------------------------------------------------
# Snapshots & in-progress state
# ---------------------------------------------------------------------------

class SnapshotTest(GitRepoTestCase):

    def test_write_read_roundtrip(self):
        self.commit_initial()
        d = plan.write_snapshots(self.repo, "BASE", "MINE", "THEIRS")
        self.assertEqual(d, os.path.join(self.repo, ".git", "plan-merge"))
        b, m, t = plan.read_snapshots(self.repo)
        self.assertEqual((b, m, t), ("BASE", "MINE", "THEIRS"))

    def test_none_side_written_empty(self):
        self.commit_initial()
        plan.write_snapshots(self.repo, None, "MINE", "THEIRS")
        b, m, t = plan.read_snapshots(self.repo)
        self.assertEqual(b, "")          # None -> empty file
        self.assertEqual(m, "MINE")
        self.assertEqual(t, "THEIRS")

    def test_paths(self):
        self.assertEqual(plan.reject_path("/x/.PLAN.md"), "/x/.PLAN.md.reject")
        self.assertEqual(plan.snapshot_dir(self.repo),
                         os.path.join(self.repo, ".git", "plan-merge"))

    def test_merge_in_progress_toggles(self):
        self.commit_initial()
        self.assertFalse(plan.merge_in_progress(self.plan_path))
        with open(plan.reject_path(self.plan_path), "w") as f:
            f.write("# reject\n")
        self.assertTrue(plan.merge_in_progress(self.plan_path))

    def test_clear_merge_state(self):
        self.commit_initial()
        plan.write_snapshots(self.repo, "B", "M", "T")
        with open(plan.reject_path(self.plan_path), "w") as f:
            f.write("# reject\n")
        self.assertTrue(plan.merge_in_progress(self.plan_path))
        self.assertTrue(os.path.isdir(plan.snapshot_dir(self.repo)))
        plan.clear_merge_state(self.repo, self.plan_path)
        self.assertFalse(plan.merge_in_progress(self.plan_path))
        self.assertFalse(os.path.isdir(plan.snapshot_dir(self.repo)))
        # Idempotent on a clean repo.
        plan.clear_merge_state(self.repo, self.plan_path)


# ---------------------------------------------------------------------------
# annotate_conflict_lines
# ---------------------------------------------------------------------------

class AnnotateTest(GitRepoTestCase):

    def test_spans_point_at_node_headers(self):
        # Build a real conflict via merge_trees: both sides edit ticket #1's
        # status differently, so #1 conflicts.
        base = plan.parse(PLAN_BASE)
        mine = plan.parse(PLAN_BASE.replace(
            "status: open\n    Body of first.",
            "status: in-progress\n    Body of first."))
        theirs = plan.parse(PLAN_BASE.replace(
            "status: open\n    Body of first.",
            "status: done\n    Body of first."))
        result = plan.merge_trees(base, mine, theirs)
        self.assertTrue(result.conflicts, "expected at least one conflict")

        mine_text = plan.serialize(mine)
        theirs_text = plan.serialize(theirs)
        plan.annotate_conflict_lines(result.conflicts, mine_text, theirs_text)

        c = result.conflicts[0]
        self.assertEqual(str(c.node_id), "1")
        self.assertIsNotNone(c.mine_lines)
        self.assertIsNotNone(c.theirs_lines)
        # The span's first line in mine_text contains the node id token.
        m_lines = mine_text.split("\n")
        start, end = c.mine_lines
        self.assertIn("{#1}", m_lines[start - 1])
        self.assertGreaterEqual(end, start)

    def test_absent_side_left_none(self):
        # modify-delete: theirs deletes #1, mine edits it -> conflict; the node
        # is absent from theirs_text, so theirs_lines must be None.
        base = plan.parse(PLAN_BASE)
        mine = plan.parse(PLAN_BASE.replace(
            "status: open\n    Body of first.",
            "status: in-progress\n    Body of first."))
        # theirs: remove ticket #1 entirely.
        theirs_text_src = (
            "# Project: T {#project}\n\n"
            "## Metadata {#metadata}\n\n    next_id: 3\n\n"
            "## Tickets {#tickets}\n\n"
            "  * ## Ticket: Task: Second {#2}\n"
            "        status: open\n    Body of second.\n")
        theirs = plan.parse(theirs_text_src)
        result = plan.merge_trees(base, mine, theirs)
        md = [c for c in result.conflicts if c.ctype == "modify-delete"]
        self.assertTrue(md, "expected a modify-delete conflict")
        mine_text = plan.serialize(mine)
        plan.annotate_conflict_lines(result.conflicts, mine_text, theirs_text_src)
        c = md[0]
        self.assertIsNotNone(c.mine_lines)   # present in mine
        self.assertIsNone(c.theirs_lines)    # absent in theirs

    def test_never_raises_on_garbage(self):
        c = plan.Conflict(1, "1", "ticket", "status", "field",
                          "open", "a", "b")
        # No exception even with None text / unrelated text.
        plan.annotate_conflict_lines([c], None, "garbage with no headers")
        self.assertIsNone(c.mine_lines)
        self.assertIsNone(c.theirs_lines)


# ---------------------------------------------------------------------------
# Index / conflict-state management
# ---------------------------------------------------------------------------

class IndexStateTest(GitRepoTestCase):

    def test_mark_unmerged_then_resolved(self):
        self.commit_initial()
        rel = ".PLAN.md"
        plan.mark_unmerged(self.repo, self.plan_path,
                           "BASE\n", "MINE\n", "THEIRS\n")
        # ls-files -u shows three stages for the path.
        out = _run(["git", "ls-files", "-u", "--", rel], self.repo).stdout
        stages = sorted(line.split()[2] for line in out.splitlines() if line.strip())
        self.assertEqual(stages, ["1", "2", "3"])
        # status --porcelain shows the path conflicted (UU for both-modified).
        st = _run(["git", "status", "--porcelain", "--", rel], self.repo).stdout
        self.assertTrue(st.lstrip().startswith("UU") or "UU" in st, st)

        # mark_resolved clears the stages.
        plan.mark_resolved(self.repo, self.plan_path)
        out2 = _run(["git", "ls-files", "-u", "--", rel], self.repo).stdout
        self.assertEqual(out2.strip(), "")

    def test_mark_unmerged_with_added_side(self):
        # base None (added on one side) -> AA in status, stages 2 and 3 only.
        self.commit_initial()
        rel = ".PLAN.md"
        plan.mark_unmerged(self.repo, self.plan_path, None, "MINE\n", "THEIRS\n")
        out = _run(["git", "ls-files", "-u", "--", rel], self.repo).stdout
        stages = sorted(line.split()[2] for line in out.splitlines() if line.strip())
        self.assertEqual(stages, ["2", "3"])
        st = _run(["git", "status", "--porcelain", "--", rel], self.repo).stdout
        self.assertIn("AA", st)

    def test_in_merge_or_rebase_clean_false(self):
        self.commit_initial()
        self.assertFalse(plan.in_merge_or_rebase(self.repo))

    def test_in_merge_or_rebase_fake_merge_head_true(self):
        self.commit_initial()
        # Fabricate a MERGE_HEAD inside the real git dir.
        git_dir = _run(["git", "rev-parse", "--git-dir"], self.repo).stdout.strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(self.repo, git_dir)
        with open(os.path.join(git_dir, "MERGE_HEAD"), "w") as f:
            f.write(plan.git_rev_parse(self.repo, "HEAD") + "\n")
        self.assertTrue(plan.in_merge_or_rebase(self.repo))


# ---------------------------------------------------------------------------
# Install-config helpers
# ---------------------------------------------------------------------------

class ConfigHelpersTest(GitRepoTestCase):

    def test_gitattributes_idempotent_and_remove(self):
        self.commit_initial()
        ga = os.path.join(self.repo, ".gitattributes")
        plan.ensure_gitattributes(self.repo, ".PLAN.md")
        plan.ensure_gitattributes(self.repo, ".PLAN.md")  # idempotent
        self.assertEqual(_read(ga).count(".PLAN.md merge=plan"), 1)
        plan.remove_gitattributes(self.repo, ".PLAN.md")
        self.assertNotIn(".PLAN.md merge=plan", _read(ga))

    def test_gitattributes_preserves_other_lines(self):
        ga = os.path.join(self.repo, ".gitattributes")
        with open(ga, "w") as f:
            f.write("*.txt text\n")
        plan.ensure_gitattributes(self.repo, ".PLAN.md")
        content = _read(ga)
        self.assertIn("*.txt text", content)
        self.assertIn(".PLAN.md merge=plan", content)
        plan.remove_gitattributes(self.repo, ".PLAN.md")
        content = _read(ga)
        self.assertIn("*.txt text", content)
        self.assertNotIn(".PLAN.md merge=plan", content)

    def test_merge_driver_set_and_unset(self):
        self.commit_initial()
        plan.set_merge_driver(self.repo)
        plan.set_merge_driver(self.repo)  # idempotent
        drv = _run(["git", "config", "--get", "merge.plan.driver"],
                   self.repo).stdout.strip()
        self.assertEqual(drv, "plan merge-driver %O %A %B %P")
        name = _run(["git", "config", "--get", "merge.plan.name"],
                    self.repo).stdout.strip()
        self.assertTrue(name)
        # unset removes the section.
        self.assertTrue(plan.unset_merge_driver(self.repo))
        gone = _run(["git", "config", "--get", "merge.plan.driver"],
                    self.repo, check=False)
        self.assertNotEqual(gone.returncode, 0)
        # unset is tolerant of an absent section.
        self.assertTrue(plan.unset_merge_driver(self.repo))

    def test_gitignore_idempotent_and_remove(self):
        gi = os.path.join(self.repo, ".gitignore")
        plan.ensure_gitignore(self.repo, ".PLAN.md.reject")
        plan.ensure_gitignore(self.repo, ".PLAN.md.reject")  # idempotent
        self.assertEqual(_read(gi).count(".PLAN.md.reject"), 1)
        plan.remove_gitignore(self.repo, ".PLAN.md.reject")
        self.assertNotIn(".PLAN.md.reject", _read(gi))

    def test_gitignore_preserves_other_lines(self):
        gi = os.path.join(self.repo, ".gitignore")
        with open(gi, "w") as f:
            f.write("*.pyc\nnode_modules/\n")
        plan.ensure_gitignore(self.repo, "*.reject")
        content = _read(gi)
        self.assertIn("*.pyc", content)
        self.assertIn("node_modules/", content)
        self.assertIn("*.reject", content)
        plan.remove_gitignore(self.repo, "*.reject")
        content = _read(gi)
        self.assertIn("*.pyc", content)
        self.assertNotIn("*.reject", content)


if __name__ == "__main__":
    unittest.main()
