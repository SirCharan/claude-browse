"""Tests for scripts/install-local.sh."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install-local.sh"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.cmd = self.home / ".claude" / "commands" / "browse.md"
        self.skill = self.home / ".claude" / "skills" / "browse-router"

    def tearDown(self):
        self.tmp.cleanup()

    def sh(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              env=dict(os.environ, HOME=str(self.home)))

    def test_regular_file_kept(self):
        self.cmd.parent.mkdir(parents=True)
        self.cmd.write_text("mine")
        r = self.sh()
        self.assertIn("exists and is not a symlink", r.stdout)
        self.assertEqual(self.cmd.read_text(), "mine")
        self.assertTrue(self.skill.is_symlink())

    def test_uninstall_only_removes_own_links(self):
        self.assertEqual(self.sh().returncode, 0)
        self.assertTrue(self.cmd.is_symlink())
        self.cmd.unlink()
        foreign = self.home / "foreign.md"
        foreign.write_text("x")
        self.cmd.symlink_to(foreign)
        self.sh("--uninstall")
        self.assertTrue(self.cmd.is_symlink())
        self.assertFalse(self.skill.is_symlink())


if __name__ == "__main__":
    unittest.main()
