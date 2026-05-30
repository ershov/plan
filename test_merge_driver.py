#!/usr/bin/env python3
"""End-to-end tests for the git merge DRIVER and `plan install local` config.

Run from the project root with:  python3 -m unittest test_merge_driver

Two groups:

1. The merge driver exercised through REAL `git merge` (and via direct
   invocation). The driver is configured WITHOUT `plan` on PATH: we point
   `merge.plan.driver` at `<python3> <abs>/plan.py merge-driver %O %A %B %P`
   and add `.PLAN.md merge=plan` to `.gitattributes`.

2. `plan install local` / `plan uninstall local` driver config, run as a
   subprocess with HOME redirected to a throwaway dir (so the real home is
   never touched), asserting only on the driver config (.gitattributes, git
   config merge.plan.driver, .gitignore) — not the binary/plugin/CLAUDE.md.

The whole module is skipped when `git` is unavailable. Temp dirs and env are
always cleaned up. Plan files are generated THROUGH the CLI so they round-trip.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PLAN_PY = os.path.join(REPO_ROOT, "plan.py")

# The driver command, configured to run our generated plan.py via this python,
# so the test needs neither `plan` nor `python3` on PATH to differ.
DRIVER_CMD = "%s %s merge-driver %%O %%A %%B %%P" % (
    sys.executable, PLAN_PY)


def _git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


GIT_OK = _git_available()


class _RepoCase(unittest.TestCase):
    """Base: a throwaway git repo on branch `main` with a CLI-built .PLAN.md."""

    def setUp(self):
        if not GIT_OK:
            raise unittest.SkipTest("git is not available")
        self.repo = tempfile.mkdtemp(prefix="plan-driver-")
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
        """Run the CLI on this repo's plan file. Returns the completed proc."""
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

    def reject_exists(self):
        return os.path.exists(self.plan_path + ".reject")

    def snapshot_dir_exists(self):
        return os.path.isdir(os.path.join(self.repo, ".git", "plan-merge"))

    def titles(self):
        """Return list of '#id title [status]' lines via the CLI."""
        proc = self.plan("list", "--format",
                         'f"#{id} {title} [{status}]"', check=True)
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    def configure_driver(self):
        """Configure the merge driver WITHOUT needing plan on PATH."""
        self._git("config", "merge.plan.name", "plan structure-aware merge")
        self._git("config", "merge.plan.driver", DRIVER_CMD)
        gitattr = os.path.join(self.repo, ".gitattributes")
        with open(gitattr, "w", encoding="utf-8") as f:
            f.write(".PLAN.md merge=plan\n")
        self.commit("configure plan merge driver")

    def build_base(self, titles):
        for t in titles:
            self.plan("create", 'title="%s"' % t, check=True)
        self.commit("initial plan")


# ---------------------------------------------------------------------------
# Driver end-to-end via real `git merge`
# ---------------------------------------------------------------------------

class DriverGitMergeTest(_RepoCase):

    def test_nonconflicting_divergence_merges_both_sides(self):
        # base #1; each branch adds its own ticket -> both get id #2 (collision).
        self.build_base(["Base"])
        self.configure_driver()

        self._git("checkout", "-q", "-b", "feature")
        self.plan("create", 'title="FeatureOnly"', check=True)
        self.commit("feature adds a ticket")

        self._git("checkout", "-q", "main")
        self.plan("create", 'title="MainOnly"', check=True)
        self.commit("main adds a ticket")

        # git merge invokes the driver; it should resolve cleanly (exit 0).
        proc = self._git("merge", "feature", "-m", "merge feature",
                         check=False)
        self.assertEqual(proc.returncode, 0,
                         "git merge should succeed:\n%s\n%s"
                         % (proc.stdout, proc.stderr))

        # Both sides' tickets survive (collision renumbered -> 3 tickets).
        titles = self.titles()
        joined = "\n".join(titles)
        self.assertIn("Base", joined)
        self.assertIn("FeatureOnly", joined)
        self.assertIn("MainOnly", joined)
        self.assertEqual(len(titles), 3, "expected 3 tickets, got: %r" % titles)
        # The colliding id was renumbered (distinct ids), file is clean.
        self.assertNotIn("<<<<<<<", self.read_plan())
        self.assertFalse(self.reject_exists())

    def test_conflicting_divergence_marks_unmerged_then_resolve(self):
        # base #1; both branches edit the SAME field (status) differently.
        self.build_base(["Shared"])
        self.configure_driver()

        self._git("checkout", "-q", "-b", "feature")
        self.plan("1", "status", "in-progress", check=True)
        self.commit("feature: status in-progress")

        self._git("checkout", "-q", "main")
        self.plan("1", "status", "done", check=True)
        self.commit("main: status done")

        # Conflict: git merge fails (driver exit 1 -> path unmerged).
        proc = self._git("merge", "feature", "-m", "merge feature",
                         check=False)
        self.assertNotEqual(proc.returncode, 0,
                            "git merge should fail on conflict")

        # git records the path unmerged.
        status = self._git("status", "--porcelain").stdout
        self.assertRegex(status, r"(?m)^(UU|AA|DD|U.|.U) .*\.PLAN\.md")

        # The driver dropped a .reject and snapshots; working file is valid
        # with mine (main, "done") defaults and no raw conflict markers.
        self.assertTrue(self.reject_exists())
        self.assertTrue(self.snapshot_dir_exists())
        plan_text = self.read_plan()
        self.assertNotIn("<<<<<<<", plan_text)
        self.assertIn("status: done", plan_text)

        # Edit the .reject to KEEP the `from` side (feature: in-progress):
        # delete the `to` indicator + its content line, leave only `from`.
        reject = self.plan_path + ".reject"
        with open(reject, encoding="utf-8") as f:
            lines = f.read().split("\n")
        kept = []
        skip = False
        for ln in lines:
            if ln.startswith("--- to "):
                skip = True
                continue
            if ln.startswith("--- from "):
                skip = False
                continue
            if skip:
                # drop the `to` side's content line(s) until the `from` indicator
                continue
            kept.append(ln)
        with open(reject, "w", encoding="utf-8") as f:
            f.write("\n".join(kept))

        # Finish via the built CLI.
        res = self.plan("merge", "--resolve")
        self.assertEqual(res.returncode, 0,
                         "--resolve should succeed:\n%s\n%s"
                         % (res.stdout, res.stderr))
        self.assertFalse(self.reject_exists())
        self.assertFalse(self.snapshot_dir_exists())
        self.assertIn("status: in-progress", self.read_plan())

        # git add + commit succeeds now that the path is resolved.
        self._git("add", "-A")
        commit = self._git("commit", "-m", "resolved merge", check=False)
        self.assertEqual(commit.returncode, 0,
                         "commit after resolve should succeed:\n%s\n%s"
                         % (commit.stdout, commit.stderr))

    def test_direct_invocation_rewrites_ours_to_merged(self):
        # Build base/ours/theirs as real CLI plan files, then invoke the driver
        # directly with crafted temp files (no git merge in flight).
        base = os.path.join(self.repo, "base.md")
        ours = os.path.join(self.repo, "ours.md")
        theirs = os.path.join(self.repo, "theirs.md")

        def cli(path, *args):
            proc = subprocess.run(
                [sys.executable, PLAN_PY, "--file", path, *args],
                cwd=self.repo, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc

        cli(base, "create", 'title="Base"')
        shutil.copy(base, ours)
        shutil.copy(base, theirs)
        # Non-conflicting: each side adds a distinct ticket (collide on id #2).
        cli(ours, "create", 'title="OursOnly"')
        cli(theirs, "create", 'title="TheirsOnly"')

        proc = subprocess.run(
            [sys.executable, PLAN_PY, "merge-driver", base, ours, theirs,
             ".PLAN.md"],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         "clean driver run should exit 0:\n%s" % proc.stderr)
        with open(ours, encoding="utf-8") as f:
            merged = f.read()
        self.assertIn("OursOnly", merged)
        self.assertIn("TheirsOnly", merged)
        self.assertIn("Base", merged)
        self.assertNotIn("<<<<<<<", merged)

        # Conflicting direct run: both edit status of #1 -> exit 1, ours valid.
        o2 = os.path.join(self.repo, "o2.md")
        t2 = os.path.join(self.repo, "t2.md")
        shutil.copy(base, o2)
        shutil.copy(base, t2)
        cli(o2, "1", "status", "in-progress")
        cli(t2, "1", "status", "blocked")
        proc = subprocess.run(
            [sys.executable, PLAN_PY, "merge-driver", base, o2, t2, ".PLAN.md"],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1,
                         "conflicting driver run should exit 1:\n%s"
                         % proc.stderr)
        with open(o2, encoding="utf-8") as f:
            o2_text = f.read()
        # %A (ours) rewritten to the merged content with mine defaults, valid.
        self.assertNotIn("<<<<<<<", o2_text)
        self.assertIn("status: in-progress", o2_text)

    def test_wrong_arg_count_errors(self):
        proc = subprocess.run(
            [sys.executable, PLAN_PY, "merge-driver", "only", "three", "args"],
            cwd=self.repo, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("merge-driver", proc.stderr)

    def test_empty_ours_takes_theirs_clean(self):
        # Fail-safe: %A (ours/MINE) is empty and the file is new on theirs. The
        # driver must write THEIRS' full content into %A (not an empty file or a
        # skeleton missing theirs' title/sections) and exit 0.
        base = os.path.join(self.repo, "base.md")   # empty base file
        ours = os.path.join(self.repo, "ours.md")   # empty ours (%A)
        theirs = os.path.join(self.repo, "theirs.md")
        open(base, "w").close()
        open(ours, "w").close()
        # Build a real plan file for theirs via the CLI.
        proc = subprocess.run(
            [sys.executable, PLAN_PY, "--file", theirs, "create",
             'title="TheirsNew"'],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        proc = subprocess.run(
            [sys.executable, PLAN_PY, "merge-driver", base, ours, theirs,
             ".PLAN.md"],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         "empty-ours driver run should exit 0:\n%s" % proc.stderr)
        with open(ours, encoding="utf-8") as f:
            merged = f.read()
        self.assertTrue(merged.strip(), "merged %A must not be empty")
        self.assertIn("TheirsNew", merged)
        self.assertNotIn("<<<<<<<", merged)


# ---------------------------------------------------------------------------
# install / uninstall driver config
# ---------------------------------------------------------------------------

class InstallDriverConfigTest(_RepoCase):

    def _run_install(self, action):
        """Run `plan <install|uninstall> local` with HOME redirected to temp."""
        home = tempfile.mkdtemp(prefix="plan-home-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env = dict(os.environ)
        env["HOME"] = home
        proc = subprocess.run(
            [sys.executable, PLAN_PY, action, "local"],
            cwd=self.repo, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(proc.returncode, 0,
                         "%s local exit %d:\n%s\n%s"
                         % (action, proc.returncode, proc.stdout, proc.stderr))
        return proc

    def _gitattributes(self):
        path = os.path.join(self.repo, ".gitattributes")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _gitignore(self):
        path = os.path.join(self.repo, ".gitignore")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _driver_config(self):
        proc = self._git("config", "--get", "merge.plan.driver", check=False)
        return proc.stdout.strip()

    def test_install_then_uninstall_driver_config(self):
        self._run_install("install")

        self.assertIn(".PLAN.md merge=plan", self._gitattributes())
        driver = self._driver_config()
        self.assertEqual(driver, "plan merge-driver %O %A %B %P", driver)
        self.assertIn(".PLAN.md.reject", self._gitignore())

        self._run_install("uninstall")

        self.assertNotIn(".PLAN.md merge=plan", self._gitattributes())
        self.assertEqual(self._driver_config(), "")
        self.assertNotIn(".PLAN.md.reject", self._gitignore())

    def test_install_is_idempotent(self):
        self._run_install("install")
        self._run_install("install")
        # Still exactly one attribute line, one ignore line.
        self.assertEqual(
            self._gitattributes().count(".PLAN.md merge=plan"), 1)
        self.assertEqual(
            self._gitignore().count(".PLAN.md.reject"), 1)


# ---------------------------------------------------------------------------
# Standalone `install git` / `uninstall git` target (driver only)
# ---------------------------------------------------------------------------

class InstallGitTargetTest(_RepoCase):
    """The `git` target configures ONLY the merge driver in the current repo."""

    def _run(self, action, cwd, expect_rc=0):
        """Run `plan <action> git` in `cwd`, HOME redirected to a temp dir."""
        home = tempfile.mkdtemp(prefix="plan-home-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        env = dict(os.environ)
        env["HOME"] = home
        proc = subprocess.run(
            [sys.executable, PLAN_PY, action, "git"],
            cwd=cwd, capture_output=True, text=True, timeout=60, env=env)
        if expect_rc is not None:
            self.assertEqual(
                proc.returncode, expect_rc,
                "%s git in %s: exit %d (expected %d)\n%s\n%s"
                % (action, cwd, proc.returncode, expect_rc,
                   proc.stdout, proc.stderr))
        return proc

    def _read(self, name):
        path = os.path.join(self.repo, name)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _driver_config(self):
        proc = self._git("config", "--get", "merge.plan.driver", check=False)
        return proc.stdout.strip()

    def test_install_git_configures_only_driver(self):
        self._run("install", self.repo)

        # The three driver artifacts are present.
        self.assertIn(".PLAN.md merge=plan", self._read(".gitattributes"))
        self.assertEqual(self._driver_config(), "plan merge-driver %O %A %B %P")
        self.assertIn(".PLAN.md.reject", self._read(".gitignore"))

        # And NOTHING from a full install: no binary, plugin, CLAUDE.md, AGENTS.
        self.assertFalse(os.path.exists(os.path.join(self.repo, "plan")),
                         "git target must not install the binary")
        self.assertFalse(os.path.isdir(os.path.join(self.repo, ".claude")),
                         "git target must not install the plugin")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "CLAUDE.md")),
                         "git target must not touch CLAUDE.md")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "AGENTS.md")),
                         "git target must not touch AGENTS.md")

    def test_uninstall_git_removes_driver(self):
        self._run("install", self.repo)
        self._run("uninstall", self.repo)
        self.assertNotIn(".PLAN.md merge=plan", self._read(".gitattributes"))
        self.assertEqual(self._driver_config(), "")
        self.assertNotIn(".PLAN.md.reject", self._read(".gitignore"))

    def test_install_git_outside_repo_errors(self):
        # A temp dir that is NOT a git repo: install git must fail loudly.
        nonrepo = tempfile.mkdtemp(prefix="plan-nonrepo-")
        self.addCleanup(shutil.rmtree, nonrepo, ignore_errors=True)
        proc = self._run("install", nonrepo, expect_rc=None)
        self.assertNotEqual(proc.returncode, 0,
                            "install git outside a repo must NOT succeed")
        self.assertIn("git", (proc.stderr + proc.stdout).lower())
        # It must not have created any artifacts in the non-repo dir.
        self.assertFalse(os.path.exists(os.path.join(nonrepo, ".gitattributes")))
        self.assertFalse(os.path.exists(os.path.join(nonrepo, "plan")))

    def test_uninstall_git_outside_repo_errors(self):
        nonrepo = tempfile.mkdtemp(prefix="plan-nonrepo-")
        self.addCleanup(shutil.rmtree, nonrepo, ignore_errors=True)
        proc = self._run("uninstall", nonrepo, expect_rc=None)
        self.assertNotEqual(proc.returncode, 0,
                            "uninstall git outside a repo must NOT succeed")

    def test_install_git_is_idempotent(self):
        self._run("install", self.repo)
        self._run("install", self.repo)
        self.assertEqual(
            self._read(".gitattributes").count(".PLAN.md merge=plan"), 1)
        self.assertEqual(
            self._read(".gitignore").count(".PLAN.md.reject"), 1)


if __name__ == "__main__":
    unittest.main()
