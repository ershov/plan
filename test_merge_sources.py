#!/usr/bin/env python3
"""End-to-end tests for Stage 9 — explicit `--to`/`--from`/`--base` sources,
`-o/--output`, and outside-git support.

Run from the project root with:  python3 -m unittest test_merge_sources

Drives the REAL generated CLI (`plan.py`) as a subprocess against both REAL
throwaway git repositories AND plain (non-git) temp directories. Plan files are
generated THROUGH the CLI so they round-trip on parse.

The git-repo cases are skipped when `git` is unavailable; the outside-git cases
do not need git. Temp dirs are always cleaned up; `$EDITOR=true` + `--no-edit`
ensure no editor blocks.
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


def _env():
    e = dict(os.environ)
    e["EDITOR"] = "true"
    return e


def run_plan(cwd, *args, check=False):
    """Run the CLI, returning the CompletedProcess."""
    proc = subprocess.run(
        [sys.executable, PLAN_PY, *args],
        cwd=cwd, capture_output=True, text=True, timeout=60, env=_env())
    if check and proc.returncode != 0:
        raise AssertionError(
            "plan %s exit %d:\n%s\n%s"
            % (args, proc.returncode, proc.stdout, proc.stderr))
    return proc


def make_plan(path, title):
    """Create a one-ticket plan file at `path` via the CLI."""
    run_plan(os.path.dirname(path) or ".", "--file", path,
             "create", 'title="%s"' % title, check=True)


def set_status(path, status):
    run_plan(os.path.dirname(path) or ".", "--file", path,
             "1", "status", status, check=True)


def statuses(path):
    proc = run_plan(os.path.dirname(path) or ".", "--file", path,
                    "list", "--format", 'f"#{id} [{status}] {title}"',
                    check=True)
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Outside-git: explicit file sources
# ---------------------------------------------------------------------------

class OutsideGitTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="plan-merge-nogit-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.to = os.path.join(self.dir, "to.PLAN.md")
        self.frm = os.path.join(self.dir, "from.PLAN.md")
        self.out = os.path.join(self.dir, "out.PLAN.md")
        # Not a git repo. `to` = done, `from` = in-progress, no base (two-way).
        make_plan(self.to, "Shared")
        set_status(self.to, "done")
        shutil.copy(self.to, self.frm)
        set_status(self.frm, "in-progress")

    def state_dir(self, out):
        return os.path.join(os.path.dirname(out), ".plan-merge")

    def test_outside_git_conflict_state_beside_output(self):
        proc = run_plan(self.dir, "merge", "--to", self.to, "--from", self.frm,
                        "-o", self.out, "--no-edit")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        # .reject + .plan-merge live beside the output, NOT in any .git.
        self.assertTrue(os.path.exists(self.out + ".reject"))
        self.assertTrue(os.path.isdir(self.state_dir(self.out)))
        self.assertFalse(os.path.isdir(os.path.join(self.dir, ".git")))
        # The input `to` file is untouched; the merged result lands in OUT.
        self.assertIn("[done]", "\n".join(statuses(self.to)))
        self.assertIn("[done]", "\n".join(statuses(self.out)))  # to default

    def test_outside_git_resolve_via_output(self):
        run_plan(self.dir, "merge", "--to", self.to, "--from", self.frm,
                 "-o", self.out, "--no-edit")
        # Keep the `from` side in the reject.
        self._keep_from(self.out + ".reject")
        proc = run_plan(self.dir, "merge", "--resolve", "-o", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[in-progress]", "\n".join(statuses(self.out)))
        self.assertFalse(os.path.exists(self.out + ".reject"))
        self.assertFalse(os.path.isdir(self.state_dir(self.out)))

    def test_outside_git_abort_via_output(self):
        run_plan(self.dir, "merge", "--to", self.to, "--from", self.frm,
                 "-o", self.out, "--no-edit")
        proc = run_plan(self.dir, "merge", "--abort", "-o", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # OUT restored to the `to` (mine) snapshot = done.
        self.assertIn("[done]", "\n".join(statuses(self.out)))
        self.assertFalse(os.path.exists(self.out + ".reject"))

    def test_outside_git_stage_is_noop(self):
        proc = run_plan(self.dir, "merge", "--to", self.to, "--from", self.frm,
                        "-o", self.out, "--stage", "--no-edit")
        # --stage outside git must not error; it just produces the conflict file.
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(os.path.exists(self.out + ".reject"))

    def test_outside_git_clean_merge_no_conflict(self):
        # Fresh, unambiguous setup: `to` and `from` share an identical #1; `from`
        # only ADDS a non-conflicting ticket -> two-way merge is clean.
        to = os.path.join(self.dir, "cto.PLAN.md")
        frm = os.path.join(self.dir, "cfrom.PLAN.md")
        out = os.path.join(self.dir, "cout.PLAN.md")
        make_plan(to, "Shared")
        shutil.copy(to, frm)
        run_plan(self.dir, "--file", frm, "create", 'title="Extra"', check=True)
        proc = run_plan(self.dir, "merge", "--to", to, "--from", frm,
                        "-o", out, "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.exists(out + ".reject"))
        joined = "\n".join(statuses(out))
        self.assertIn("Shared", joined)
        self.assertIn("Extra", joined)

    def test_default_output_is_to_file_when_no_dash_o(self):
        # No -o: with --to a FILE, the result is written back into the --to file.
        proc = run_plan(self.dir, "merge", "--to", self.to, "--from", self.frm,
                        "--prefer", "from", "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The `to` file now reflects the merge (prefer from -> in-progress).
        self.assertIn("[in-progress]", "\n".join(statuses(self.to)))

    def test_bad_source_outside_git_exit2(self):
        proc = run_plan(self.dir, "merge", "--to", self.to,
                        "--from", "no-such-thing", "-o", self.out)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a file or git ref", proc.stderr)

    def _keep_from(self, reject):
        out, skip = [], False
        for ln in read(reject).split("\n"):
            if ln.startswith("--- to ("):
                skip = True
                continue
            if ln.startswith("--- from ("):
                skip = False
                continue
            if skip:
                continue
            out.append(ln)
        with open(reject, "w", encoding="utf-8") as f:
            f.write("\n".join(out))


# ---------------------------------------------------------------------------
# In-repo: commit / file sources, --base, auto two-way vs three-way
# ---------------------------------------------------------------------------

class _GitRepoBase(unittest.TestCase):
    """Repo setup + helpers shared by the in-repo test classes (no test_ here)."""

    def setUp(self):
        if not GIT_OK:
            raise unittest.SkipTest("git is not available")
        self.repo = tempfile.mkdtemp(prefix="plan-merge-src-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.plan = os.path.join(self.repo, ".PLAN.md")
        self._git("init", "-q")
        self._git("config", "user.email", "t@e.com")
        self._git("config", "user.name", "T")
        self._git("config", "commit.gpgsign", "false")
        self._git("checkout", "-q", "-b", "main")

    def _git(self, *args, check=True):
        proc = subprocess.run(["git", "-C", self.repo, *args],
                              capture_output=True, text=True, timeout=30)
        if check and proc.returncode != 0:
            raise AssertionError("git %s failed: %s" % (args, proc.stderr))
        return proc

    def commit(self, msg):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg)

    def plan_cmd(self, *args, check=False):
        return run_plan(self.repo, "--file", self.plan, *args, check=check)

    def run_merge(self, *args, check=False):
        # merge ignores --file for sources but uses cwd for repo discovery.
        return run_plan(self.repo, "merge", *args, check=check)

    def diverge(self):
        """Base #1; feature -> in-progress, main -> done (status conflict)."""
        make_plan(self.plan, "Shared")
        self.commit("init")
        self._git("checkout", "-q", "-b", "feature")
        self.plan_cmd("1", "status", "in-progress", check=True)
        self.commit("feature")
        self._git("checkout", "-q", "main")
        self.plan_cmd("1", "status", "done", check=True)
        self.commit("main")


class InRepoSourcesTest(_GitRepoBase):

    def test_from_commit_default_to_worktree_threeway(self):
        # Real merge-base exists -> three-way -> a real field conflict.
        self.diverge()
        proc = self.run_merge("--from", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(os.path.exists(self.plan + ".reject"))
        # State lives in .git (inside a repo).
        self.assertTrue(os.path.isdir(
            os.path.join(self.repo, ".git", "plan-merge")))
        # Base header carries a merge-base short sha (three-way).
        self.assertIn("(merge-base)", read(self.plan + ".reject"))
        self.run_merge("--abort")

    def test_to_commit_from_commit_with_explicit_base(self):
        self.diverge()
        # Explicit --base = main..feature merge-base ref; here use 'main~0'? Use
        # the very first commit as base via 'main' before divergence is hard;
        # instead use --base main (HEAD) so both sides vs that base.
        proc = self.run_merge("--to", "git:main", "--from", "git:feature",
                              "--base", "git:main", "-o",
                              os.path.join(self.repo, "merged.md"),
                              "--no-edit")
        # to==base==main(done); from==feature(in-progress) -> from changed only
        # -> clean (takes in-progress).
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = os.path.join(self.repo, "merged.md")
        self.assertIn("[in-progress]", "\n".join(statuses(merged)))

    def test_omitted_base_two_files_is_two_way(self):
        # Two file sources, no commits, no --base -> two-way (no merge-base).
        self.diverge()
        a = os.path.join(self.repo, "a.md")
        b = os.path.join(self.repo, "b.md")
        make_plan(a, "Shared")
        set_status(a, "done")
        shutil.copy(a, b)
        set_status(b, "in-progress")
        out = os.path.join(self.repo, "two.md")
        proc = self.run_merge("--to", a, "--from", b, "-o", out, "--no-edit")
        # Two-way: shared id #1 diverged -> conflict.
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("(none — two-way)", read(out + ".reject"))

    def test_file_source_wins_over_branch(self):
        # A name that is BOTH a branch and an existing file -> file wins.
        self.diverge()
        feat_file = os.path.join(self.repo, "feature")  # same name as branch
        make_plan(feat_file, "Shared")
        set_status(feat_file, "blocked")
        proc = self.run_merge("--from", "feature", "--prefer", "from",
                              "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Took the FILE's blocked status, not the branch's in-progress.
        self.assertIn("[blocked]", "\n".join(statuses(self.plan)))

    def test_git_prefix_forces_ref(self):
        self.diverge()
        feat_file = os.path.join(self.repo, "feature")
        make_plan(feat_file, "Shared")
        set_status(feat_file, "blocked")
        proc = self.run_merge("--from", "git:feature", "--prefer", "from",
                              "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Took the BRANCH's in-progress status, ignoring the file.
        self.assertIn("[in-progress]", "\n".join(statuses(self.plan)))

    def test_file_prefix_forces_file(self):
        self.diverge()
        # file:<branchname> with no such file -> absent file -> 'from' is empty.
        # Use an actual file path to be meaningful.
        f = os.path.join(self.repo, "explicit.md")
        make_plan(f, "Shared")
        set_status(f, "blocked")
        proc = self.run_merge("--from", "file:" + f, "--prefer", "from",
                              "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[blocked]", "\n".join(statuses(self.plan)))

    def test_output_elsewhere_leaves_to_untouched(self):
        self.diverge()
        before = read(self.plan)
        out = os.path.join(self.repo, "elsewhere.md")
        proc = self.run_merge("--from", "feature", "--prefer", "from",
                              "-o", out, "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The working-tree `to` (.PLAN.md) is untouched; result is in OUT.
        self.assertEqual(read(self.plan), before)
        self.assertIn("[in-progress]", "\n".join(statuses(out)))

    def test_both_branch_and_from_is_error(self):
        self.diverge()
        proc = self.run_merge("feature", "--from", "feature")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("branch OR --from", proc.stderr)

    def test_resolve_writes_persisted_output(self):
        # -o output is persisted; --resolve -o output writes the right file.
        self.diverge()
        out = os.path.join(self.repo, "persisted.md")
        self.run_merge("--from", "feature", "-o", out, "--no-edit")
        self.assertTrue(os.path.exists(out + ".reject"))
        # Keep `from`.
        rej = out + ".reject"
        kept, skip = [], False
        for ln in read(rej).split("\n"):
            if ln.startswith("--- to ("):
                skip = True
                continue
            if ln.startswith("--- from ("):
                skip = False
                continue
            if skip:
                continue
            kept.append(ln)
        with open(rej, "w", encoding="utf-8") as f:
            f.write("\n".join(kept))
        proc = self.run_merge("--resolve", "-o", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[in-progress]", "\n".join(statuses(out)))


# ---------------------------------------------------------------------------
# MAJOR 1: commit sources must not silently produce an empty merge
# ---------------------------------------------------------------------------

class CommitSourceContentTest(_GitRepoBase):

    def test_commit_from_with_o_reads_canonical_plan_not_output_basename(self):
        # Regression: with -o <other>, a commit --from must read the CANONICAL
        # plan file at that ref (.PLAN.md), NOT '<output-basename>' (absent on
        # the ref) which used to yield a silent EMPTY merge with exit 0.
        self.diverge()
        out = os.path.join(self.repo, "weird", "out.md")
        os.makedirs(os.path.dirname(out))
        proc = self.run_merge("--from", "feature", "-o", out, "--prefer", "from",
                              "--no-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The merged result is a real plan (ticket present), not empty.
        body = read(out)
        self.assertTrue(body.strip(), "merged output must not be empty")
        self.assertIn("{#1}", body)
        self.assertIn("[in-progress]", "\n".join(statuses(out)))  # from won

    def test_explicit_from_commit_absent_at_path_errors_not_empty(self):
        # An explicit --from commit whose canonical plan path is absent at that
        # ref must ERROR (exit 2), never write a silent empty merged file.
        # Build a ref that has NO .PLAN.md at all.
        self.diverge()
        self._git("checkout", "-q", "--orphan", "noplan")
        self._git("rm", "-q", "-rf", ".", check=False)
        readme = os.path.join(self.repo, "README.md")
        with open(readme, "w") as f:
            f.write("no plan here\n")
        self.commit("orphan without plan")
        self._git("checkout", "-q", "main")
        out = os.path.join(self.repo, "out.md")
        proc = self.run_merge("--from", "git:noplan", "-o", out, "--no-edit")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("no content", proc.stderr)
        # No silent empty merged file (the lock may create an empty file; the
        # KEY guarantee is we did NOT write a serialized-but-empty plan).
        if os.path.exists(out):
            self.assertEqual(read(out).strip(), "")

    def test_undeterminable_relpath_for_commit_source_errors(self):
        # resolve_source with relpath=None on a commit source errors clearly
        # (rather than reading the wrong/absent path).
        self.diverge()
        import plan
        repo = plan.git_repo_root(self.repo)
        with self.assertRaises(plan.SourceError) as ctx:
            plan.resolve_source("git:feature", repo, None)
        self.assertIn("cannot determine the plan file path", str(ctx.exception))


# ---------------------------------------------------------------------------
# MINOR 3: per-output namespaced state dir (concurrent -o merges don't collide)
# ---------------------------------------------------------------------------

class NamespacedStateTest(_GitRepoBase):

    def _keep_from(self, reject):
        out, skip = [], False
        for ln in read(reject).split("\n"):
            if ln.startswith("--- to ("):
                skip = True
                continue
            if ln.startswith("--- from ("):
                skip = False
                continue
            if skip:
                continue
            out.append(ln)
        with open(reject, "w", encoding="utf-8") as f:
            f.write("\n".join(out))

    def test_two_inflight_merges_keep_separate_state(self):
        self.diverge()
        outA = os.path.join(self.repo, "outA.md")
        outB = os.path.join(self.repo, "outB.md")
        # Both conflict (default `to` = working tree = done; from = in-progress).
        self.assertEqual(
            self.run_merge("--from", "feature", "-o", outA, "--no-edit").returncode, 1)
        self.assertEqual(
            self.run_merge("--from", "feature", "-o", outB, "--no-edit").returncode, 1)
        # Two distinct namespaced subdirs under .git/plan-merge.
        base = os.path.join(self.repo, ".git", "plan-merge")
        subdirs = sorted(os.listdir(base))
        self.assertEqual(len(subdirs), 2, subdirs)
        self.assertTrue(os.path.exists(outA + ".reject"))
        self.assertTrue(os.path.exists(outB + ".reject"))
        # Resolve merge A only -> A's state gone, B's preserved.
        self._keep_from(outA + ".reject")
        self.assertEqual(self.run_merge("--resolve", "-o", outA).returncode, 0)
        self.assertFalse(os.path.exists(outA + ".reject"))
        self.assertTrue(os.path.exists(outB + ".reject"),
                        "resolving A must not disturb B's in-progress merge")
        self.assertEqual(len(os.listdir(base)), 1)  # only B's subdir remains
        self.assertIn("[in-progress]", "\n".join(statuses(outA)))  # A: from won

    def test_clear_removes_empty_parent_when_last_merge_done(self):
        self.diverge()
        proc = self.run_merge("--from", "feature", "--no-edit")
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(os.path.isdir(
            os.path.join(self.repo, ".git", "plan-merge")))
        self.run_merge("--abort")
        # The only in-flight merge is gone -> the empty parent is cleaned up too.
        self.assertFalse(os.path.isdir(
            os.path.join(self.repo, ".git", "plan-merge")))


# ---------------------------------------------------------------------------
# MAJOR 2: merge takes an exclusive lock on the output file
# ---------------------------------------------------------------------------

class OutputLockTest(_GitRepoBase):

    def test_merge_blocks_when_output_exclusively_locked(self):
        # A concurrent holder of LOCK_EX on the output must make `plan merge`
        # fail to acquire (mutual exclusion with other `plan` writers).
        try:
            import fcntl  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("fcntl/flock unavailable on this platform")
        self.diverge()
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import fcntl,sys,time;"
             "f=open(sys.argv[1],'a');"
             "fcntl.flock(f,fcntl.LOCK_EX);"
             "sys.stdout.write('locked\\n');sys.stdout.flush();"
             "time.sleep(4)", self.plan],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            proc = self.run_merge("--from", "feature", "--no-edit")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("could not acquire lock", proc.stderr)
        finally:
            holder.wait()
            holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
