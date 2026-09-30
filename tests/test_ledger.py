"""Tests for lib/ledger.py using a temp HOME and AB_DIR."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._saved = {k: os.environ.get(k) for k in
                       ("CLAUDE_BROWSE_HOME", "CLAUDE_BROWSE_AB_DIR", "CLAUDE_CODE_SESSION_ID")}
        os.environ["CLAUDE_BROWSE_HOME"] = str(root / "home")
        os.environ["CLAUDE_BROWSE_AB_DIR"] = str(root / "ab")
        (root / "ab").mkdir()
        import ledger
        self.ledger = importlib.reload(ledger)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_load_creates_default(self):
        self.assertEqual(self.ledger.load(), {"version": 1, "sessions": {}})

    def test_save_load_roundtrip(self):
        d = {"version": 1, "sessions": {"a": {"x": 1}}}
        self.ledger.save(d)
        self.assertEqual(self.ledger.load(), d)

    def test_locked_writes_back(self):
        with self.ledger.locked() as d:
            d["sessions"]["a"] = {"n": 1}
        with self.ledger.locked() as d:
            d["sessions"]["a"]["n"] += 1
        self.assertEqual(self.ledger.get("a"), {"n": 2})

    def test_locked_unchanged_keeps_file(self):
        self.ledger.save({"version": 1, "sessions": {}})
        before = self.ledger.LEDGER.stat().st_mtime_ns
        with self.ledger.locked():
            pass
        self.assertEqual(self.ledger.LEDGER.stat().st_mtime_ns, before)

    def test_new_session_owner_from_env(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-123"
        s = self.ledger.new_session("n", "p", "agent-browser", allowed_domains=["a.com"])
        self.assertEqual(s["owner"]["claude_session"], "sess-123")
        self.assertEqual(s["state"], "starting")
        self.assertEqual(s["pid"], 0)
        self.assertIsNone(s["daemon_version"])
        self.assertEqual(s["created"], s["last_used"])
        self.assertEqual(s["allowed_domains"], ["a.com"])
        self.assertIs(s["headed"], False)

    def test_upsert_get_remove(self):
        self.ledger.upsert("a", state="live")
        self.assertEqual(self.ledger.upsert("a", url="u")["state"], "live")
        self.assertEqual(self.ledger.get("a")["url"], "u")
        self.ledger.remove("a")
        self.assertIsNone(self.ledger.get("a"))

    def test_log_order_and_n(self):
        for i in range(5):
            self.ledger.append_log("a", {"i": i})
        log = self.ledger.read_log("a", n=3)
        self.assertEqual([e["i"] for e in log], [2, 3, 4])
        self.assertIn("ts", log[0])
        self.assertEqual(self.ledger.read_log("missing"), [])

    def test_daemon_state(self):
        ab = Path(os.environ["CLAUDE_BROWSE_AB_DIR"])
        (ab / "dead.pid").write_text("999999")
        (ab / "dead.version").write_text("0.31.2")
        (ab / "live.pid").write_text(str(os.getpid()))
        (ab / "live.sock").write_text("")
        (ab / "live.target").write_text(json.dumps({"targetId": "T", "url": "u", "pinned": True}))
        (ab / "browsers").mkdir()
        (ab / "cfg.config").write_text("{}")
        dead = self.ledger.daemon_state("dead")
        self.assertEqual((dead["pid"], dead["alive"], dead["version"], dead["sock"]),
                         (999999, False, "0.31.2", False))
        live = self.ledger.daemon_state("live")
        self.assertTrue(live["alive"])
        self.assertTrue(live["sock"])
        self.assertEqual(live["target"]["targetId"], "T")
        none = self.ledger.daemon_state("nope")
        self.assertEqual(none, {"pid": None, "alive": False, "version": None,
                                "sock": False, "target": None})
        self.assertEqual(self.ledger.list_daemons(), ["cfg", "dead", "live"])

    def test_prune(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.ledger.locked() as d:
            d["sessions"]["old"] = {"state": "closed", "last_used": old}
            d["sessions"]["new"] = {"state": "closed", "last_used": self.ledger.now_iso()}
            d["sessions"]["liveold"] = {"state": "live", "last_used": old}
        self.ledger.append_log("old", {"a": 1})
        self.ledger.append_log("new", {"a": 1})
        p = self.ledger.LOGS / "old.jsonl"
        t = p.stat().st_mtime - 40 * 86400
        os.utime(p, (t, t))
        res = self.ledger.prune()
        self.assertEqual(res["sessions_removed"], ["old"])
        self.assertEqual(res["logs_removed"], ["old"])
        self.assertEqual(sorted(self.ledger.load()["sessions"]), ["liveold", "new"])
        self.assertTrue((self.ledger.LOGS / "new.jsonl").exists())

    def test_corrupt_recovered(self):
        self.ledger.HOME.mkdir(parents=True, exist_ok=True)
        self.ledger.LEDGER.write_text("{not json")
        self.assertEqual(self.ledger.load(), {"version": 1, "sessions": {}})
        self.assertEqual(len(list(self.ledger.HOME.glob("sessions.json.corrupt-*"))), 1)
        self.assertFalse(self.ledger.LEDGER.exists())


if __name__ == "__main__":
    unittest.main()
