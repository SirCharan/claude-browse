"""Tests for bin/browse open, run, log and adopt."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROWSE = ROOT / "bin" / "browse"
FAKE = ROOT / "tests" / "fixtures" / "fake-agent-browser"


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.ab, self.calls = t / "home", t / "ab", t / "calls.log"
        self.ab.mkdir()
        self.env = dict(os.environ, CLAUDE_BROWSE_HOME=str(self.home), CLAUDE_BROWSE_AB_DIR=str(self.ab),
                        CLAUDE_BROWSE_AB_BIN=str(FAKE), FAKE_AB_LOG=str(self.calls))
        self.env.pop("FAKE_AB_FAIL", None)

    def tearDown(self):
        self.tmp.cleanup()

    def browse(self, *args, **extra):
        return subprocess.run([sys.executable, str(BROWSE), *args], capture_output=True, text=True,
                              env=dict(self.env, **extra))

    def ledger(self):
        return json.loads((self.home / "sessions.json").read_text())["sessions"]

    def log(self, name):
        return [json.loads(x) for x in (self.home / "logs" / f"{name}.jsonl").read_text().splitlines()]

    def open(self, name="s1", *extra):
        r = self.browse("open", name, "--purpose", "t", "--url", "https://example.com", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_open_creates_entry_and_calls_shim(self):
        self.open()
        e = self.ledger()["s1"]
        self.assertEqual((e["state"], e["stack"], e["url"]), ("live", "agent-browser", "https://example.com"))
        call = self.calls.read_text()
        self.assertIn("--session s1", call)
        self.assertIn("--json", call)
        self.assertIn("open https://example.com", call)

    def test_run_snapshot_prints_only_text_and_logs_ref(self):
        self.open()
        r = self.browse("run", "s1", "snapshot", "-i")
        self.assertEqual(r.stdout.strip(), '- button "Go" [ref=e1]')
        last = self.log("s1")[-1]
        self.assertEqual(last["action"], "snapshot")
        self.assertEqual(len(last["snapshot_ref"]), 8)
        self.assertTrue(last["ok"])

    def test_allowlist_blocks_and_allows_subdomain(self):
        self.open("s2", "--allow-domains", "example.com")
        r = self.browse("run", "s2", "open", "https://evil.org/x")
        self.assertEqual(r.returncode, 3)
        self.assertIn("policy: evil.org not in allowed_domains", r.stdout)
        last = self.log("s2")[-1]
        self.assertEqual((last["ok"], last["err"]), (False, "policy"))
        r = self.browse("run", "s2", "open", "https://docs.example.com/a")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_allowlist_rejects_backslash_at_and_scheme(self):
        self.open("s2", "--allow-domains", "example.com")
        for u in ("https://evil.com\\@example.com", "https://example.com@evil.com", "ftp://example.com"):
            self.assertEqual(self.browse("run", "s2", "open", u).returncode, 3, u)
        self.assertEqual(self.log("s2")[-1]["err"], "policy")

    def test_allowlist_with_leading_flag(self):
        self.open("n", "--allow-domains", "example.com")
        self.assertEqual(self.browse("run", "n", "--headed", "open", "https://evil.com").returncode, 3)

    def test_open_url_checked_against_allowlist(self):
        r = self.browse("open", "o1", "--purpose", "t", "--url", "https://evil.com",
                        "--allow-domains", "example.com")
        self.assertEqual(r.returncode, 3)
        self.assertFalse((self.home / "sessions.json").exists())

    def test_bh_snippet_urls_checked(self):
        self.home.mkdir()
        (self.home / "sessions.json").write_text(json.dumps({"version": 1, "sessions": {
            "b": {"stack": "browser-harness", "allowed_domains": ["example.com"], "state": "live"}}}))
        r = self.browse("run", "b", "print(new_tab('https://evil.com/x'))")
        self.assertEqual(r.returncode, 3)

    def test_invalid_session_name_exits_2(self):
        r = self.browse("open", "../../foo", "--purpose", "t")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: invalid session name", r.stderr)
        self.assertFalse((self.home / "sessions.json").exists())
        self.assertFalse((Path(self.tmp.name).parent / "foo").exists())
        self.assertEqual(self.browse("open", "sessions", "--purpose", "t").returncode, 2)

    def test_timeout_exits_124(self):
        self.open()
        r = self.browse("run", "s1", "snapshot", FAKE_AB_SLEEP="3", CLAUDE_BROWSE_TIMEOUT="0.5")
        self.assertEqual(r.returncode, 124)
        self.assertIn("timeout after 0.5s", r.stderr)
        self.assertFalse(self.log("s1")[-1]["ok"])

    def test_run_unknown_session_exits_2(self):
        self.assertEqual(self.browse("run", "nope", "snapshot").returncode, 2)

    def test_run_close_sets_closed(self):
        self.open()
        self.assertEqual(self.browse("run", "s1", "close").returncode, 0)
        self.assertEqual(self.ledger()["s1"]["state"], "closed")

    def test_adopt_registers_daemon(self):
        (self.ab / "legacy.pid").write_text(str(os.getpid()))
        r = self.browse("adopt")
        self.assertIn("adopted 1", r.stdout)
        e = self.ledger()["legacy"]
        self.assertEqual((e["purpose"], e["state"]), ("legacy (unknown)", "live"))
        self.assertIn("adopted 0", self.browse("adopt").stdout)

    def test_log_n1_returns_last_line(self):
        self.open()
        self.browse("run", "s1", "snapshot")
        self.browse("run", "s1", "close")
        r = self.browse("log", "s1", "-n", "1", "--json")
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["action"], "close")

    def test_failure_logs_ok_false(self):
        self.open()
        r = self.browse("run", "s1", "click", "@e1", FAKE_AB_FAIL="1")
        self.assertEqual(r.returncode, 1)
        last = self.log("s1")[-1]
        self.assertFalse(last["ok"])
        self.assertIn("boom", last["err"])


if __name__ == "__main__":
    unittest.main()
