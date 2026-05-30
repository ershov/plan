#!/usr/bin/env python3
"""End-to-end CLI tests for `plan merge` (Stage 4 — CLI wiring).

Run from the project root with:  python3 -m unittest test_merge_cli

These tests drive the REAL generated CLI (`plan.py`) as a subprocess against
REAL throwaway git repositories built with subprocess + tempfile. Each test:
commits a `.PLAN.md`, branches and diverges, then invokes
    plan merge <branch> [flags]   /   plan merge --resolve / --abort
and asserts on the exit code, stdout/stderr and the resulting file contents.

Plan files are generated THROUGH the CLI (so bullet indentation is consistent
and parses round-trip), then mutated through the CLI on each branch.

The whole module is skipped when `git` is unavailable. Temp dirs are always
cleaned up. `$EDITOR` is forced to `true` (and --no-edit is also used) so no
editor ever blocks.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PLAN_PY = os.path.join(REPO_ROOT, "plan.py")


def _git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


GIT_OK = _git_available()


class MergeCliTestCase(unittest.TestCase):
    """Base class: a fresh throwaway git repo with a CLI-built .PLAN.md."""

    def setUp(self):
        if not GIT_OK:
            raise unittest.SkipTest("git is not available")
        self.repo = tempfile.mkdtemp(prefix="plan-merge-cli-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.plan_path = os.path.join(self.repo, ".PLAN.md")
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")
        self._git("config", "commit.gpgsign", "false")
        self._git("checkout", "-q", "-b", "main")

    # -- git / plan helpers ------------------------------------------------

    def _git(self, *args, check=True):
        proc = subprocess.run(
            ["git", "-C", self.repo, *args],
            capture_output=True, text=True, timeout=30,
        )
        if check and proc.returncode != 0:
            raise AssertionError("git %s failed:\n%s" % (args, proc.stderr))
        return proc

    def plan(self, *args, check=False):
        """Run the CLI on this repo's plan file, env EDITOR=true. Returns proc."""
        env = dict(os.environ)
        env["EDITOR"] = "true"
        proc = subprocess.run(
            [sys.executable, PLAN_PY, "--file", self.plan_path, *args],
            cwd=self.repo, capture_output=True, text=True, timeout=60, env=env,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                "plan %s exit %d:\n%s\n%s"
                % (args, proc.returncode, proc.stdout, proc.stderr))
        return proc

    def commit(self, msg):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg)

    def read_plan(self):
        with open(self.plan_path, encoding="utf-8") as f:
            return f.read()

    def read_reject(self):
        with open(self.plan_path + ".reject", encoding="utf-8") as f:
            return f.read()

    def write_reject(self, text):
        with open(self.plan_path + ".reject", "w", encoding="utf-8") as f:
            f.write(text)

    def reject_exists(self):
        return os.path.exists(self.plan_path + ".reject")

    def snapshot_dir_exists(self):
        return os.path.isdir(os.path.join(self.repo, ".git", "plan-merge"))

    def titles(self):
        """Return list of '#id title [status]' lines via the CLI."""
        proc = self.plan("list", "--format",
                         'f"#{id} {title} [{status}]"', check=True)
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    # -- scenario builders -------------------------------------------------

    def build_base(self, titles):
        """Create the listed tickets via the CLI and commit as the base."""
        for t in titles:
            self.plan("create", 'title="%s"' % t, check=True)
        self.commit("initial plan")

    def diverge_status_conflict(self):
        """Base #1; feature sets #1 in-progress, main sets #1 done (conflict)."""
        self.build_base(["Shared"])
        self._git("checkout", "-q", "-b", "feature")
        self.plan("1", "status", "in-progress", check=True)
        self.commit("feature edits status")
        self._git("checkout", "-q", "main")
        self.plan("1", "status", "done", check=True)
        self.commit("main edits status")

    def diverge_id_collision(self):
        """Base #1; both branches create a new ticket that collides on #2."""
        self.build_base(["Base"])
        self._git("checkout", "-q", "-b", "feature")
        self.plan("create", 'title="FeatureNew"', check=True)
        self.commit("feature new ticket")
        self._git("checkout", "-q", "main")
        self.plan("create", 'title="MainNew"', check=True)
        self.commit("main new ticket")


# ---------------------------------------------------------------------------
# Clean merge
# ---------------------------------------------------------------------------

class CleanMergeTest(MergeCliTestCase):

    def test_clean_merge_no_overlap_with_collision_renumber(self):
        # Base #1; feature edits #1's status only + adds a ticket (#2),
        # main edits a DIFFERENT field source by adding its own ticket (#2).
        self.build_base(["Shared"])
        self._git("checkout", "-q", "-b", "feature")
        self.plan("1", "status", "in-progress", check=True)
        self.plan("create", 'title="Feature ticket"', check=True)
        self.commit("feature")
        self._git("checkout", "-q", "main")
        # Touch #1 via a comment (a non-conflicting addition) + add a ticket.
        self.plan("1", "comment", "add", "main note", check=True)
        self.plan("create", 'title="Main ticket"', check=True)
        self.commit("main")

        proc = self.plan("merge", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("clean", proc.stdout)
        self.assertFalse(self.reject_exists())

        titles = self.titles()
        joined = "\n".join(titles)
        # Both sides' tickets present.
        self.assertIn("Shared", joined)
        self.assertIn("Feature ticket", joined)
        self.assertIn("Main ticket", joined)
        # Status change from feature applied (only side that changed status).
        self.assertIn("[in-progress]", joined)
        # Collision renumber: feature's new ticket (id 2) moved off main's id 2.
        ids = sorted(int(ln.split()[0].lstrip("#")) for ln in titles)
        self.assertEqual(ids, [1, 2, 3])  # 4 distinct? -> #1, main #2, feat #3

    def test_clean_merge_id_collision_renumbered(self):
        self.diverge_id_collision()
        proc = self.plan("merge", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.reject_exists())
        joined = "\n".join(self.titles())
        self.assertIn("Base", joined)
        self.assertIn("MainNew", joined)
        self.assertIn("FeatureNew", joined)
        # 3 distinct ids -> the collision was renumbered, not duplicated.
        ids = sorted(int(ln.split()[0].lstrip("#")) for ln in self.titles())
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)


# ---------------------------------------------------------------------------
# Conflict -> .reject -> --resolve / --abort
# ---------------------------------------------------------------------------

class ConflictResolveTest(MergeCliTestCase):

    def _keep_theirs_in_reject(self):
        """Edit the .reject in place to keep the `from` (theirs) side of every block."""
        lines = self.read_reject().split("\n")
        out, skip = [], False
        for ln in lines:
            if ln.startswith("--- to ("):
                skip = True
                continue
            if ln.startswith("--- from ("):
                skip = False
                continue
            if skip:
                continue
            out.append(ln)
        self.write_reject("\n".join(out))

    def test_conflict_writes_reject_with_mine_default(self):
        self.diverge_status_conflict()
        proc = self.plan("merge", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("conflict", proc.stderr)
        self.assertIn(".reject", proc.stderr)
        self.assertTrue(self.reject_exists())
        self.assertTrue(self.snapshot_dir_exists())
        # In-tree default is MINE (main = done).
        self.assertIn("[done]", "\n".join(self.titles()))

    def test_resolve_keep_theirs(self):
        self.diverge_status_conflict()
        self.plan("merge", "feature", "--no-edit")
        self.assertTrue(self.reject_exists())
        self._keep_theirs_in_reject()
        proc = self.plan("merge", "--resolve")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[in-progress]", "\n".join(self.titles()))
        # state cleared
        self.assertFalse(self.reject_exists())
        self.assertFalse(self.snapshot_dir_exists())

    def test_abort_restores_mine(self):
        self.diverge_status_conflict()
        self.plan("merge", "feature", "--no-edit")
        # In-tree currently MINE default (done). Abort should restore the
        # pre-merge working tree (which was main = done).
        proc = self.plan("merge", "--abort")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[done]", "\n".join(self.titles()))
        self.assertFalse(self.reject_exists())
        self.assertFalse(self.snapshot_dir_exists())

    def test_merge_already_in_progress(self):
        self.diverge_status_conflict()
        self.plan("merge", "feature", "--no-edit")
        proc = self.plan("merge", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("already in progress", proc.stderr)


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------

class CheckTest(MergeCliTestCase):

    def test_check_conflict_count_writes_nothing(self):
        self.diverge_status_conflict()
        before = self.read_plan()
        proc = self.plan("merge", "feature", "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("conflict", proc.stdout)
        self.assertIn("1", proc.stdout)
        self.assertFalse(self.reject_exists())
        self.assertEqual(self.read_plan(), before)  # file untouched

    def test_check_clean_exit_zero_writes_nothing(self):
        self.diverge_id_collision()  # no field conflict, only collision
        before = self.read_plan()
        proc = self.plan("merge", "feature", "--check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("clean", proc.stdout)
        self.assertEqual(self.read_plan(), before)


# ---------------------------------------------------------------------------
# --prefer
# ---------------------------------------------------------------------------

class PreferTest(MergeCliTestCase):

    def test_prefer_from_resolves_without_reject(self):
        self.diverge_status_conflict()
        proc = self.plan("merge", "feature", "--prefer", "from", "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.reject_exists())
        self.assertIn("[in-progress]", "\n".join(self.titles()))

    def test_prefer_to_resolves_without_reject(self):
        self.diverge_status_conflict()
        proc = self.plan("merge", "feature", "--prefer", "to", "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.reject_exists())
        self.assertIn("[done]", "\n".join(self.titles()))


# ---------------------------------------------------------------------------
# --renumber
# ---------------------------------------------------------------------------

class RenumberTest(MergeCliTestCase):

    def _merge_and_titles(self, *extra):
        self.diverge_id_collision()
        proc = self.plan("merge", "feature", "--no-edit", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {ln.split(maxsplit=1)[1].rsplit(" [", 1)[0]:
                int(ln.split()[0].lstrip("#"))
                for ln in self.titles()}

    def test_default_renumber_from_moves_feature(self):
        m = self._merge_and_titles()
        # Default 'from' (engine 'theirs') => feature's colliding new ticket
        # gets the new id.
        self.assertEqual(m["MainNew"], 2)
        self.assertEqual(m["FeatureNew"], 3)

    def test_renumber_to_moves_main(self):
        m = self._merge_and_titles("--renumber", "to")
        # 'to' (engine 'mine') => main's colliding new ticket gets the new id;
        # feature keeps 2.
        self.assertEqual(m["FeatureNew"], 2)
        self.assertEqual(m["MainNew"], 3)


# ---------------------------------------------------------------------------
# --resolve error paths
# ---------------------------------------------------------------------------

class ResolveErrorTest(MergeCliTestCase):

    def test_resolve_unresolved_block_exit2(self):
        self.diverge_status_conflict()
        self.plan("merge", "feature", "--no-edit")
        # Leave the .reject untouched (both sides present) -> not resolved.
        proc = self.plan("merge", "--resolve")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("conflict #1", proc.stderr)

    def test_resolve_edited_content_exit2(self):
        self.diverge_status_conflict()
        self.plan("merge", "feature", "--no-edit")
        # Keep only the `to` (mine) side but corrupt its content -> matches no side.
        lines = self.read_reject().split("\n")
        out, skip = [], False
        for ln in lines:
            if ln.startswith("--- from ("):
                skip = True
                continue
            if skip and ln.startswith(">>> END"):
                skip = False
            if skip:
                continue
            if ln == "done":
                out.append("garbage-value")
                continue
            out.append(ln)
        self.write_reject("\n".join(out))
        proc = self.plan("merge", "--resolve")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("conflict #1", proc.stderr)

    def test_resolve_no_merge_in_progress_exit2(self):
        self.build_base(["x"])
        proc = self.plan("merge", "--resolve")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no merge in progress", proc.stderr)

    def test_abort_no_merge_in_progress_exit2(self):
        self.build_base(["x"])
        proc = self.plan("merge", "--abort")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no merge in progress", proc.stderr)


# ---------------------------------------------------------------------------
# Error: not a git repo / bad branch
# ---------------------------------------------------------------------------

class ErrorPathTest(unittest.TestCase):

    def setUp(self):
        if not GIT_OK:
            raise unittest.SkipTest("git is not available")

    def _plan(self, cwd, *args):
        env = dict(os.environ)
        env["EDITOR"] = "true"
        return subprocess.run(
            [sys.executable, PLAN_PY, *args],
            cwd=cwd, capture_output=True, text=True, timeout=60, env=env)

    def test_not_a_git_repo_exit2(self):
        # Stage 9: outside git a bare positional <branch> is treated as a source
        # spec. With no repo it resolves to neither a file nor a ref -> exit 2
        # with the uniform source error (mentioning we are not in a git repo).
        d = tempfile.mkdtemp(prefix="plan-merge-nogit-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan_path = os.path.join(d, ".PLAN.md")
        self._plan(d, "--file", plan_path, "create", 'title="x"')
        proc = self._plan(d, "--file", plan_path, "merge", "somebranch")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a file or git ref", proc.stderr)
        self.assertIn("not inside a git repository", proc.stderr)

    def test_bad_branch_exit2(self):
        d = tempfile.mkdtemp(prefix="plan-merge-badbr-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        for cfg in (("user.email", "t@e.com"), ("user.name", "T"),
                    ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", d, "config", *cfg], check=True)
        subprocess.run(["git", "-C", d, "checkout", "-q", "-b", "main"])
        plan_path = os.path.join(d, ".PLAN.md")
        self._plan(d, "--file", plan_path, "create", 'title="x"')
        subprocess.run(["git", "-C", d, "add", "-A"], check=True)
        subprocess.run(["git", "-C", d, "commit", "-q", "-m", "init"],
                       check=True)
        # Stage 9: a bare name that is neither an existing file nor a resolvable
        # ref is an unresolved source -> exit 2 with the uniform source error.
        proc = self._plan(d, "--file", plan_path, "merge", "no-such-branch")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a file or git ref", proc.stderr)

    def test_merge_missing_branch_arg_exit2(self):
        d = tempfile.mkdtemp(prefix="plan-merge-noarg-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        for cfg in (("user.email", "t@e.com"), ("user.name", "T"),
                    ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", d, "config", *cfg], check=True)
        subprocess.run(["git", "-C", d, "checkout", "-q", "-b", "main"])
        plan_path = os.path.join(d, ".PLAN.md")
        self._plan(d, "--file", plan_path, "create", 'title="x"')
        subprocess.run(["git", "-C", d, "add", "-A"], check=True)
        subprocess.run(["git", "-C", d, "commit", "-q", "-m", "init"],
                       check=True)
        proc = self._plan(d, "--file", plan_path, "merge")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("branch", proc.stderr.lower())


# ---------------------------------------------------------------------------
# --stage: git index shows the path unmerged
# ---------------------------------------------------------------------------

class StageTest(MergeCliTestCase):

    def test_stage_marks_path_unmerged(self):
        self.diverge_status_conflict()
        proc = self.plan("merge", "feature", "--stage", "--no-edit")
        self.assertEqual(proc.returncode, 1)
        ls = self._git("ls-files", "-u").stdout
        # Path appears with unmerged stages (1/2/3) in the index.
        self.assertIn(".PLAN.md", ls)
        self.assertTrue(ls.strip(), "expected unmerged index entries")

    def test_standalone_default_does_not_stage(self):
        self.diverge_status_conflict()
        proc = self.plan("merge", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 1)
        ls = self._git("ls-files", "-u").stdout
        # Default standalone merge does NOT touch the index.
        self.assertEqual(ls.strip(), "")


if __name__ == "__main__":
    unittest.main()
