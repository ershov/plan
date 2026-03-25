#!/usr/bin/env python3
"""Tests for non-interactive edit support (--start, --restart, --accept, --abort)."""

import glob
import os
import sys
import tempfile
import textwrap
import unittest

# Import plan.py from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan


class TestEditFileEncodeDecode(unittest.TestCase):
    """Test _edit_file_encode and _edit_file_decode round-trip."""

    def test_encode_basic(self):
        result = plan._edit_file_encode(".PLAN.md","5", set(), "a1b2c3d4")
        self.assertEqual(result, ".PLAN-edit-5-a1b2c3d4.md")

    def test_encode_with_recursive_flag(self):
        result = plan._edit_file_encode(".PLAN.md","5", {"r"}, "a1b2c3d4")
        self.assertEqual(result, ".PLAN-edit-5-r-a1b2c3d4.md")

    def test_encode_with_multiple_flags(self):
        result = plan._edit_file_encode(".PLAN.md","42", {"r", "a"}, "deadbeef")
        # flags should be sorted
        self.assertEqual(result, ".PLAN-edit-42-a-r-deadbeef.md")

    def test_decode_basic(self):
        result = plan._edit_file_decode(".PLAN-edit-5-a1b2c3d4.md", ".PLAN.md")
        self.assertIsNotNone(result)
        ticket_id, flags, content_hash = result
        self.assertEqual(ticket_id, "5")
        self.assertEqual(flags, set())
        self.assertEqual(content_hash, "a1b2c3d4")

    def test_decode_with_flag(self):
        result = plan._edit_file_decode(".PLAN-edit-5-r-a1b2c3d4.md", ".PLAN.md")
        self.assertIsNotNone(result)
        ticket_id, flags, content_hash = result
        self.assertEqual(ticket_id, "5")
        self.assertEqual(flags, {"r"})
        self.assertEqual(content_hash, "a1b2c3d4")

    def test_decode_with_multiple_flags(self):
        result = plan._edit_file_decode(".PLAN-edit-42-a-r-deadbeef.md", ".PLAN.md")
        self.assertIsNotNone(result)
        ticket_id, flags, content_hash = result
        self.assertEqual(ticket_id, "42")
        self.assertEqual(flags, {"a", "r"})
        self.assertEqual(content_hash, "deadbeef")

    def test_round_trip(self):
        for tid, flags, chash in [
            ("5", set(), "a1b2c3d4"),
            ("123", {"r"}, "deadbeef"),
            ("7", {"a", "r"}, "cafebabe"),
        ]:
            encoded = plan._edit_file_encode(".PLAN.md", tid, flags, chash)
            decoded = plan._edit_file_decode(encoded, ".PLAN.md")
            self.assertIsNotNone(decoded, f"Failed to decode {encoded}")
            self.assertEqual(decoded[0], tid)
            self.assertEqual(decoded[1], flags)
            self.assertEqual(decoded[2], chash)

    def test_decode_invalid(self):
        self.assertIsNone(plan._edit_file_decode("random.md", ".PLAN.md"))
        self.assertIsNone(plan._edit_file_decode(".PLAN-edit-.md", ".PLAN.md"))
        self.assertIsNone(plan._edit_file_decode(".PLAN-edit-abc-12345678.md", ".PLAN.md"))
        self.assertIsNone(plan._edit_file_decode("foo.txt", ".PLAN.md"))
        self.assertIsNone(plan._edit_file_decode(".PLAN-edit-5-short.md", ".PLAN.md"))


class TestEditContentHash(unittest.TestCase):
    """Test _edit_content_hash."""

    def test_determinism(self):
        h1 = plan._edit_content_hash("hello world")
        h2 = plan._edit_content_hash("hello world")
        self.assertEqual(h1, h2)

    def test_length(self):
        h = plan._edit_content_hash("test content")
        self.assertEqual(len(h), 8)

    def test_hex(self):
        h = plan._edit_content_hash("test content")
        int(h, 16)  # should not raise

    def test_different_content(self):
        h1 = plan._edit_content_hash("content A")
        h2 = plan._edit_content_hash("content B")
        self.assertNotEqual(h1, h2)


class TestNonInteractiveEditEndToEnd(unittest.TestCase):
    """End-to-end tests for non-interactive edit flows."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_file = os.path.join(self.tmpdir, ".PLAN.md")
        self.plan_content = textwrap.dedent("""\
            # Test Project {#project}

            ## metadata {#metadata}

                next_id: 3

            ## tickets {#tickets}

            * ## Ticket: Task: First ticket {#1}

                  status: open
                  created: 2025-01-01

              First ticket body text.

            * ## Ticket: Task: Second ticket {#2}

                  status: open
                  created: 2025-01-01

              Second ticket body text.
        """)
        with open(self.plan_file, "w") as f:
            f.write(self.plan_content)

    def tearDown(self):
        # Clean up all files
        for f in glob.glob(os.path.join(self.tmpdir, "*")):
            os.unlink(f)
        for f in glob.glob(os.path.join(self.tmpdir, ".*")):
            if os.path.isfile(f):
                os.unlink(f)
        os.rmdir(self.tmpdir)

    def _run_plan(self, *args):
        """Run plan.main with given args, capturing stdout."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            plan.main(list(args) + ["-f", self.plan_file])
        self._last_stderr = err.getvalue()
        return out.getvalue()

    def _edit_files(self):
        """Get list of edit files in the plan directory."""
        return glob.glob(os.path.join(self.tmpdir, ".PLAN-edit-*.md"))

    def test_start_creates_edit_file(self):
        output = self._run_plan("edit", "--start", "1")
        self.assertIn(".PLAN-edit-1-", output)
        self.assertIn("Edit", self._last_stderr)
        self.assertIn("-f", self._last_stderr)
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)
        # Verify file contents
        with open(edit_files[0]) as f:
            content = f.read()
        self.assertIn("First ticket", content)

    def test_start_rejects_when_edit_in_flight(self):
        self._run_plan("edit", "--start", "1")
        with self.assertRaises(SystemExit) as ctx:
            self._run_plan("edit", "--start", "1")
        self.assertIn("already in progress", str(ctx.exception))

    def test_abort_deletes_edit_file(self):
        self._run_plan("edit", "--start", "1")
        self.assertEqual(len(self._edit_files()), 1)
        self._run_plan("edit", "--abort", "1")
        self.assertEqual(len(self._edit_files()), 0)

    def test_abort_idempotent(self):
        # Should not raise an error even if no edit is in flight
        output = self._run_plan("edit", "--abort", "1")
        self.assertIn("No edit in flight", output)

    def test_restart_replaces_edit_file(self):
        self._run_plan("edit", "--start", "1")
        files1 = self._edit_files()
        self.assertEqual(len(files1), 1)
        self._run_plan("edit", "--restart", "1")
        files2 = self._edit_files()
        self.assertEqual(len(files2), 1)

    def test_accept_applies_changes(self):
        self._run_plan("edit", "--start", "1")
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)

        # Modify the edit file - change the body text
        with open(edit_files[0]) as f:
            content = f.read()
        new_content = content.replace("First ticket body text.", "Modified body text.")
        with open(edit_files[0], "w") as f:
            f.write(new_content)

        self._run_plan("edit", "--accept", "1")
        # Edit file should be deleted
        self.assertEqual(len(self._edit_files()), 0)

        # Verify the change was applied
        output = self._run_plan("1")
        self.assertIn("Modified body text", output)

    def test_accept_hash_mismatch(self):
        self._run_plan("edit", "--start", "1")
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)

        # Modify the plan directly (simulating concurrent change)
        with open(self.plan_file) as f:
            text = f.read()
        text = text.replace("First ticket body text.", "Changed directly.")
        with open(self.plan_file, "w") as f:
            f.write(text)

        with self.assertRaises(SystemExit) as ctx:
            self._run_plan("edit", "--accept", "1")
        self.assertIn("has changed since export", str(ctx.exception))
        # Edit file should still exist
        self.assertEqual(len(self._edit_files()), 1)

    def test_accept_auto_detect_single(self):
        """--accept without ID should auto-detect when exactly one edit is in flight."""
        self._run_plan("edit", "--start", "1")
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)

        # Don't modify, just accept (no-op edit)
        self._run_plan("edit", "--accept")
        self.assertEqual(len(self._edit_files()), 0)

    def test_accept_rejects_multiple(self):
        """--accept without ID should reject when multiple edits are in flight."""
        self._run_plan("edit", "--start", "1")
        self._run_plan("edit", "--start", "2")
        with self.assertRaises(SystemExit) as ctx:
            self._run_plan("edit", "--accept")
        self.assertIn("multiple edits", str(ctx.exception))

    def test_start_non_ticket_rejected(self):
        """--start on a non-ticket node should be rejected."""
        with self.assertRaises(SystemExit) as ctx:
            self._run_plan("edit", "--start", "project")
        self.assertIn("only supported for tickets", str(ctx.exception))

    def test_start_nonexistent_ticket(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run_plan("edit", "--start", "999")
        self.assertIn("not found", str(ctx.exception))

    def test_start_recursive(self):
        """--start -r should include children in export."""
        # Create a child ticket first
        self._run_plan("create", "1", "title=\"Child task\"")
        self._run_plan("edit", "--start", "1", "-r")
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)
        with open(edit_files[0]) as f:
            content = f.read()
        self.assertIn("First ticket", content)
        self.assertIn("Child task", content)
        # Filename should include 'r' flag
        fname = os.path.basename(edit_files[0])
        decoded = plan._edit_file_decode(fname, ".PLAN.md")
        self.assertIn("r", decoded[1])


class TestEditRoundTripIndentation(unittest.TestCase):
    """Round-trip edit must not alter indentation of unedited content."""

    PLAN_WITH_NESTED = textwrap.dedent("""\
        # Project {#project}

        ## Metadata {#metadata}

            next_id: 100

        ## Tickets {#tickets}

        * ## Ticket: Task: 1 {#1}

          qwe asd zxc

          * ## Ticket: Task: 2 {#2}

            asdzxc cvb

            * ## Ticket: Task: C/C++ Backend (future) {#3}

            qwe ert rty

            - aaaaa
              zzzzz
              xxxxx
    """)

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_file = os.path.join(self.tmpdir, ".PLAN.md")
        with open(self.plan_file, "w") as f:
            f.write(self.PLAN_WITH_NESTED)

    def tearDown(self):
        for f in glob.glob(os.path.join(self.tmpdir, "*")):
            os.unlink(f)
        for f in glob.glob(os.path.join(self.tmpdir, ".*")):
            if os.path.isfile(f):
                os.unlink(f)
        os.rmdir(self.tmpdir)

    def _run_plan(self, *args):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            plan.main(list(args) + ["-f", self.plan_file])
        return out.getvalue()

    def _edit_files(self):
        return glob.glob(os.path.join(self.tmpdir, ".PLAN-edit-*.md"))

    def _round_trip(self, ticket_id, recursive=False):
        """Start edit, append a line, accept, return plan content."""
        args = ["edit", "--start", ticket_id]
        if recursive:
            args.append("-r")
        self._run_plan(*args)
        edit_files = self._edit_files()
        self.assertEqual(len(edit_files), 1)
        with open(edit_files[0], "a") as f:
            f.write("added line\n")
        self._run_plan("edit", "--accept", ticket_id)
        with open(self.plan_file) as f:
            return f.read()

    def test_nonrecursive_preserves_child_indent(self):
        """Non-recursive edit of parent must not alter children indentation."""
        original = self.PLAN_WITH_NESTED
        result = self._round_trip("1")
        # The only difference should be the added line in ticket 1's body
        for line in original.splitlines():
            if line.strip():
                self.assertIn(line, result,
                    f"Original line missing or altered: {line!r}")

    def test_recursive_preserves_body_indent(self):
        """Recursive edit must preserve body indentation of nested tickets."""
        original = self.PLAN_WITH_NESTED
        result = self._round_trip("1", recursive=True)
        for line in original.splitlines():
            if line.strip():
                self.assertIn(line, result,
                    f"Original line missing or altered: {line!r}")


class TestEditFileGlob(unittest.TestCase):
    """Test _edit_file_glob helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in glob.glob(os.path.join(self.tmpdir, "*")):
            os.unlink(f)
        for f in glob.glob(os.path.join(self.tmpdir, ".*")):
            if os.path.isfile(f):
                os.unlink(f)
        os.rmdir(self.tmpdir)

    def test_finds_edit_files(self):
        path = os.path.join(self.tmpdir, ".PLAN-edit-5-a1b2c3d4.md")
        with open(path, "w") as f:
            f.write("test")
        results = plan._edit_file_glob(self.tmpdir, ".PLAN.md")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], ".PLAN-edit-5-a1b2c3d4.md")

    def test_filters_by_ticket_id(self):
        for name in [".PLAN-edit-5-a1b2c3d4.md", ".PLAN-edit-6-deadbeef.md"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("test")
        results = plan._edit_file_glob(self.tmpdir, ".PLAN.md", ticket_id="5")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], ".PLAN-edit-5-a1b2c3d4.md")

    def test_ignores_non_edit_files(self):
        for name in [".PLAN.md", "README.md", ".PLAN-edit-bad.md"]:
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("test")
        results = plan._edit_file_glob(self.tmpdir, ".PLAN.md")
        self.assertEqual(len(results), 0)


class TestCustomPlanFilename(unittest.TestCase):
    """Test that edit files use the actual plan filename as prefix."""

    def test_encode_custom_name(self):
        result = plan._edit_file_encode("MYPLAN.md", "5", set(), "a1b2c3d4")
        self.assertEqual(result, "MYPLAN-edit-5-a1b2c3d4.md")

    def test_encode_no_md_extension(self):
        result = plan._edit_file_encode("MYPLAN", "5", set(), "a1b2c3d4")
        self.assertEqual(result, "MYPLAN-edit-5-a1b2c3d4")

    def test_decode_custom_name(self):
        result = plan._edit_file_decode("MYPLAN-edit-5-a1b2c3d4.md", "MYPLAN.md")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "5")

    def test_decode_wrong_prefix(self):
        result = plan._edit_file_decode(".PLAN-edit-5-a1b2c3d4.md", "MYPLAN.md")
        self.assertIsNone(result)

    def test_round_trip_custom(self):
        for plan_name in [".PLAN.md", "MYPLAN.md", "tasks.md", ".PLAN"]:
            encoded = plan._edit_file_encode(plan_name, "42", {"r"}, "deadbeef")
            decoded = plan._edit_file_decode(encoded, plan_name)
            self.assertIsNotNone(decoded, f"Failed round-trip for {plan_name}")
            self.assertEqual(decoded[0], "42")
            self.assertEqual(decoded[1], {"r"})
            self.assertEqual(decoded[2], "deadbeef")


if __name__ == "__main__":
    unittest.main()
