"""Tests for browse ls, reap and check."""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import ledger  # noqa: E402
import cmd_admin  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SHIM = """#!/bin/sh
echo "$@" >> "$0.argv"
[ "$1" = "--version" ] && echo "agent-browser 0.38.1"
exit 0
"""


def iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(fn, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(argparse.Namespace(**kw))
    return rc, buf.getvalue()


class ReapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ab = self.tmp / "ab"
        self.ab.mkdir()
        self.shim = self.tmp / "fake-ab"
        self.shim.write_text(SHIM)
        self.shim.chmod(self.shim.stat().st_mode | stat.S_IXUSR)
        home = self.tmp / "home"
        for k, v in [("HOME", home), ("LEDGER", home / "sessions.json"), ("LOGS", home / "logs"),
                     ("AB_DIR", self.ab), ("AB_BIN", str(self.shim))]:
            p = mock.patch.object(ledger, k, v)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ledger, "_ab_version", None)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(cmd_admin, "_GRACE", 0)
        p.start()
        self.addCleanup(p.stop)
        self.is_ab = mock.patch.object(ledger, "_is_ab_process", return_value=True)
        self.is_ab.start()
        self.addCleanup(self.is_ab.stop)
        self.kills = []
        real = os.kill

        def kill(pid, sig):
            if sig == 0:
                return real(pid, 0)
            self.kills.append((pid, sig))
        p = mock.patch("os.kill", kill)
        p.start()
        self.addCleanup(p.stop)
        me = os.getpid()
        self.mk("idle", me, "0.38.1", 10)
        self.mk("busy", me, "0.38.1", 0)
        self.mk("mism", me, "0.31.2", 1)
        self.mk("prof", me, "0.38.1", 10, profile="work")
        self.mk("orph", 999999, "0.38.1", None)
        (self.ab / "browsers").mkdir()
        self.decoy = self.ab / "browsers" / "x"
        self.decoy.write_text("keep")

    def mk(self, name, pid, ver, hours, **kw):
        (self.ab / f"{name}.pid").write_text(str(pid))
        (self.ab / f"{name}.version").write_text(ver)
        (self.ab / f"{name}.sock").write_text("")
        if hours is not None:
            e = ledger.new_session(name, "p", "agent-browser", **kw)
            e.update(last_used=iso(hours), state="live", pid=pid)
            ledger.upsert(name, **e)

    def argv(self):
        f = Path(str(self.shim) + ".argv")
        return f.read_text().splitlines() if f.exists() else []

    def states(self):
        _, o = run(cmd_admin.cmd_ls, json=True, all=True)
        return {r["name"]: r["state"] for r in json.loads(o)}

    def reap(self, **kw):
        a = dict(idle_hours=4.0, dry_run=False, restart_mismatch=False, force=False, quiet=False)
        a.update(kw)
        return run(cmd_admin.cmd_reap, **a)

    def test_ls_states(self):
        self.assertEqual(self.states(), {"idle": "live", "busy": "live", "mism": "version-mismatch",
                                         "prof": "live", "orph": "orphan"})

    def test_ls_stale_unmanaged_closed(self):
        ledger.upsert("gone", **ledger.new_session("gone", "p", "x"))
        ledger.upsert("shut", state="closed", last_used=iso(1))
        (self.ab / "free.pid").write_text(str(os.getpid()))
        s = self.states()
        self.assertEqual((s["gone"], s["shut"], s["free"]), ("stale", "closed", "unmanaged"))
        _, o = run(cmd_admin.cmd_ls, json=True, all=False)
        self.assertNotIn("shut", [r["name"] for r in json.loads(o)])

    def test_close_skips_non_agent_browser_pid(self):
        with mock.patch.object(ledger, "_is_ab_process", return_value=False):
            _, o = self.reap()
        self.assertEqual(self.kills, [])
        self.assertIn("skip idle: pid", o)
        self.assertFalse((self.ab / "idle.pid").exists())

    def test_bh_entry_survives_reap_live(self):
        e = ledger.new_session("bh1", "p", "browser-harness")
        e.update(last_used=iso(50), state="live")
        ledger.upsert("bh1", **e)
        self.reap()
        self.assertEqual(ledger.get("bh1")["state"], "live")
        self.assertEqual(self.states()["bh1"], "live")

    def test_ls_does_not_rename_corrupt_ledger(self):
        ledger.LEDGER.write_text("{bad")
        run(cmd_admin.cmd_ls, json=True, all=True)
        self.assertEqual(ledger.LEDGER.read_text(), "{bad")
        self.assertEqual(ledger.load(recover=False), {"version": 1, "sessions": {}})
        self.assertTrue(ledger.LEDGER.exists())

    def test_list_daemons_skips_invalid_names(self):
        (self.ab / "..bad name.pid").write_text("1")
        self.assertNotIn("..bad name", ledger.list_daemons())

    def test_ls_table(self):
        _, o = run(cmd_admin.cmd_ls, json=False, all=False)
        self.assertTrue(o.startswith("NAME"))
        self.assertIn("version-mismatch", o)

    def test_dry_run_changes_nothing(self):
        before = sorted(p.name for p in self.ab.iterdir())
        rc, o = self.reap(dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in self.ab.iterdir()), before)
        self.assertFalse([a for a in self.argv() if a.endswith("close")])
        self.assertEqual(self.kills, [])
        self.assertIn("would close idle", o)
        self.assertIn("dry-run", o)
        self.assertEqual(ledger.get("idle")["state"], "live")

    def test_reap_real(self):
        rc, o = self.reap()
        self.assertEqual(rc, 0)
        self.assertIn("--session idle close", self.argv())
        self.assertNotIn("--session busy close", self.argv())
        self.assertNotIn("--session prof close", self.argv())
        self.assertNotIn("--session mism close", self.argv())
        self.assertIn("skip prof: headed/profile (use --force)", o)
        self.assertEqual(ledger.get("idle")["state"], "closed")
        self.assertEqual(ledger.get("busy")["state"], "live")
        self.assertIn((os.getpid(), 15), self.kills)
        self.assertFalse((self.ab / "orph.pid").exists())
        self.assertFalse((self.ab / "orph.sock").exists())
        self.assertTrue(self.decoy.exists())
        self.assertIn("flag mism", o)
        self.assertIn("reap: closed 1, orphans removed 1, flagged 1", o)

    def test_force_closes_profiled(self):
        self.reap(force=True)
        self.assertIn("--session prof close", self.argv())

    def test_restart_mismatch(self):
        self.reap(restart_mismatch=True)
        self.assertIn("--session mism close", self.argv())

    def test_restart_mismatch_skips_recent(self):
        ledger.upsert("mism", last_used=iso(0))
        self.reap(restart_mismatch=True)
        self.assertNotIn("--session mism close", self.argv())

    def test_stale_marked_closed(self):
        ledger.upsert("gone", **ledger.new_session("gone", "p", "x"))
        self.reap()
        self.assertEqual(ledger.get("gone")["state"], "closed")

    def test_check(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError):
            rc, o = run(cmd_admin.cmd_check)
            self.assertEqual(rc, 0, o)
            self.assertIn("PASS agent-browser 0.38.1", o)
            self.assertIn("WARN version-mismatched daemons: mism", o)
            self.assertIn("browse reap --restart-mismatch", o)
            with mock.patch.object(ledger, "AB_BIN", str(self.tmp / "nope")):
                rc, o = run(cmd_admin.cmd_check)
            self.assertEqual(rc, 1)
            self.assertIn("FAIL agent-browser not found", o)

    def test_doctor_alias(self):
        spec = importlib.util.spec_from_loader("browse_cli", importlib.machinery.SourceFileLoader("browse_cli", str(ROOT / "bin" / "browse")))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        self.assertEqual(cli.CMDS["doctor"], cli.CMDS["check"])


if __name__ == "__main__":
    unittest.main()
