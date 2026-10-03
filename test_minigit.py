"""End-to-end tests for the educational MiniGit command-line client."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROGRAM = Path(__file__).with_name("minigit.py")


class MiniGitTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_command(self, *arguments):
        return subprocess.run(
            [sys.executable, str(PROGRAM), *arguments],
            cwd=self.repository,
            text=True,
            capture_output=True,
        )

    def initialize(self):
        result = self.run_command("init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def read_object(self, object_id):
        payload = (self.repository / ".minigit" / "objects" / object_id).read_bytes()
        kind, content = payload.split(b"\0", maxsplit=1)
        return kind.decode("utf-8"), content

    def test_init_creates_the_repository_layout(self):
        self.initialize()
        metadata = self.repository / ".minigit"
        self.assertTrue((metadata / "objects").is_dir())
        self.assertEqual(json.loads((metadata / "index.json").read_text()), {})
        self.assertEqual((metadata / "HEAD").read_text(), "")

    def test_init_can_be_run_twice_without_erasing_data(self):
        self.initialize()
        (self.repository / ".minigit" / "HEAD").write_text("existing-commit\n")

        result = self.run_command("init")

        self.assertEqual(result.returncode, 0)
        self.assertIn("already exists", result.stdout)
        self.assertEqual(
            (self.repository / ".minigit" / "HEAD").read_text(), "existing-commit\n"
        )

    def test_add_stages_a_nested_file_as_a_sha256_blob(self):
        self.initialize()
        notes = self.repository / "notes"
        notes.mkdir()
        document = notes / "ideas.txt"
        document.write_text("small snapshot\n")

        result = self.run_command("add", "notes/ideas.txt")

        self.assertEqual(result.returncode, 0, result.stderr)
        index = json.loads((self.repository / ".minigit" / "index.json").read_text())
        expected_id = hashlib.sha256(b"blob\0small snapshot\n").hexdigest()
        self.assertEqual(index, {"notes/ideas.txt": expected_id})
        self.assertEqual(self.read_object(expected_id), ("blob", b"small snapshot\n"))

    def test_commit_records_a_tree_and_updates_head(self):
        self.initialize()
        (self.repository / "hello.txt").write_text("hello\n")
        self.assertEqual(self.run_command("add", "hello.txt").returncode, 0)

        result = self.run_command("commit", "-m", "First snapshot")

        self.assertEqual(result.returncode, 0, result.stderr)
        commit_id = (self.repository / ".minigit" / "HEAD").read_text().strip()
        kind, raw_commit = self.read_object(commit_id)
        commit = json.loads(raw_commit)
        self.assertEqual(kind, "commit")
        self.assertEqual(commit["message"], "First snapshot")
        self.assertIsNone(commit["parent"])
        tree_kind, raw_tree = self.read_object(commit["tree"])
        self.assertEqual(tree_kind, "tree")
        self.assertIn("hello.txt", json.loads(raw_tree))

    def test_second_commit_references_the_first_commit(self):
        self.initialize()
        document = self.repository / "hello.txt"
        document.write_text("version one\n")
        self.assertEqual(self.run_command("add", "hello.txt").returncode, 0)
        self.assertEqual(self.run_command("commit", "-m", "First").returncode, 0)
        first_commit = (self.repository / ".minigit" / "HEAD").read_text().strip()

        document.write_text("version two\n")
        self.assertEqual(self.run_command("add", "hello.txt").returncode, 0)
        self.assertEqual(self.run_command("commit", "-m", "Second").returncode, 0)
        second_commit = (self.repository / ".minigit" / "HEAD").read_text().strip()

        _, raw_commit = self.read_object(second_commit)
        self.assertEqual(json.loads(raw_commit)["parent"], first_commit)

    def test_errors_are_clear_for_missing_or_unstaged_files(self):
        self.initialize()
        empty_commit = self.run_command("commit", "-m", "No files")
        missing_file = self.run_command("add", "missing.txt")

        self.assertNotEqual(empty_commit.returncode, 0)
        self.assertIn("Nothing staged", empty_commit.stderr)
        self.assertNotEqual(missing_file.returncode, 0)
        self.assertIn("not a file", missing_file.stderr)

    def test_add_rejects_a_file_outside_the_repository(self):
        self.initialize()
        with tempfile.TemporaryDirectory() as external_directory:
            external_file = Path(external_directory) / "outside.txt"
            external_file.write_text("do not stage me\n")
            result = self.run_command("add", str(external_file))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside this repository", result.stderr)

    def test_add_rejects_internal_repository_metadata(self):
        self.initialize()
        result = self.run_command("add", ".minigit/HEAD")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inside .minigit", result.stderr)

    def test_log_lists_commits_newest_first(self):
        self.initialize()
        document = self.repository / "journal.txt"
        document.write_text("first\n")
        self.assertEqual(self.run_command("add", "journal.txt").returncode, 0)
        self.assertEqual(self.run_command("commit", "-m", "First entry").returncode, 0)
        first_commit = (self.repository / ".minigit" / "HEAD").read_text().strip()

        document.write_text("second\n")
        self.assertEqual(self.run_command("add", "journal.txt").returncode, 0)
        self.assertEqual(self.run_command("commit", "-m", "Second entry").returncode, 0)
        second_commit = (self.repository / ".minigit" / "HEAD").read_text().strip()
        result = self.run_command("log")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index(second_commit), result.stdout.index(first_commit))
        self.assertLess(result.stdout.index("Second entry"), result.stdout.index("First entry"))

    def test_status_reports_staged_modified_and_untracked_files(self):
        self.initialize()
        tracked = self.repository / "tracked.txt"
        tracked.write_text("first version\n")
        self.assertEqual(self.run_command("add", "tracked.txt").returncode, 0)
        staged_status = self.run_command("status")
        self.assertIn("Changes staged for commit", staged_status.stdout)
        self.assertIn("staged: tracked.txt", staged_status.stdout)

        self.assertEqual(self.run_command("commit", "-m", "Track file").returncode, 0)
        tracked.write_text("second version\n")
        (self.repository / "new.txt").write_text("untracked\n")
        changed_status = self.run_command("status")

        self.assertEqual(changed_status.returncode, 0, changed_status.stderr)
        self.assertIn("modified: tracked.txt", changed_status.stdout)
        self.assertIn("Untracked files", changed_status.stdout)
        self.assertIn("new.txt", changed_status.stdout)


if __name__ == "__main__":
    unittest.main()
