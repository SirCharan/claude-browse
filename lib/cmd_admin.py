"""Admin commands for Claude Browse: ls, reap, check."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import ledger

_GRACE = 5
_EXTS = ("config", "engine", "pid", "sock", "stream", "version", "target")


def _ts(s):
    """Epoch seconds for an ISO string, 0 if unparseable."""
    t = ledger._parse_iso(s)
    return t.timestamp() if t else 0


def _human(sec):
    """Humanise a duration: 3d 4h, 2h 5m, 12m."""
    sec = int(max(sec, 0))
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _rows():
    """Merge ledger sessions and daemon state files into row dicts."""
    sessions = ledger.load(recover=False)["sessions"]
    ver = ledger.ab_version()
    now = time.time()
    rows = []
    for name in sorted(set(sessions) | set(ledger.list_daemons())):
        e, ds = sessions.get(name), ledger.daemon_state(name)
        mism = ds["alive"] and ds["version"] and ver and ds["version"] != ver
        if e and e.get("stack") in ("bh", "browser-harness"):
            state = "live" if e.get("state") in ("live", "starting") else "closed"
        elif e is None:
            state = "orphan" if not ds["alive"] else ("version-mismatch" if mism else "unmanaged")
        elif ds["alive"]:
            state = "version-mismatch" if mism else "live"
        else:
            state = "stale" if e.get("state") in ("live", "starting") else "closed"
        e = e or {}
        o = e.get("owner") or {}
        cs = o.get("claude_session")
        owner = cs[:8] if cs else ("cwd:" + os.path.basename(o["cwd"]) if o.get("cwd") else "-")
        lu = _ts(e.get("last_used")) or ledger.daemon_mtime(name)
        rows.append({
            "name": name, "stack": e.get("stack") or "-",
            "purpose": e.get("purpose") or "-", "owner": owner,
            "url": e.get("url") or "-",
            "age": _human(now - (_ts(e.get("created")) or ledger.daemon_mtime(name) or now)),
            "idle": _human(now - lu) if lu else "-",
            "pid": ds["pid"], "state": state,
            "_idle_s": now - lu if lu else None, "_e": e, "_ds": ds,
        })
    return rows


def cmd_ls(ns):
    """Print the session dashboard."""
    rows = _rows()
    if not getattr(ns, "all", False):
        rows = [r for r in rows if r["state"] != "closed"]
    rows.sort(key=lambda r: (r["state"] != "live", -_ts(r["_e"].get("last_used"))))
    cols = ["name", "stack", "purpose", "owner", "url", "age", "idle", "pid", "state"]
    if getattr(ns, "json", False):
        print(json.dumps([{k: r[k] for k in cols} for r in rows], indent=2))
        return 0
    def cell(r, c):
        v = "-" if r[c] is None else str(r[c])
        return v[:28] if c == "purpose" else v[:40] if c == "url" else v
    table = [[c.upper() for c in cols]] + [[cell(r, c) for c in cols] for r in rows]
    widths = [max(len(t[i]) for t in table) for i in range(len(cols))]
    for t in table:
        print("  ".join(v.ljust(w) for v, w in zip(t, widths)).rstrip())
    return 0


def _close(name, pid):
    """Close a daemon via agent-browser, SIGTERM if it survives the grace period."""
    try:
        subprocess.run([ledger.AB_BIN, "--session", name, "close"],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
    end = time.time() + _GRACE
    while time.time() < end and ledger.daemon_state(name)["alive"]:
        time.sleep(0.2)
    if pid and ledger.daemon_state(name)["alive"]:
        if not ledger._is_ab_process(pid):
            print(f"skip {name}: pid {pid} is not agent-browser")
            for x in _EXTS:
                (ledger.AB_DIR / f"{name}.{x}").unlink(missing_ok=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    ledger.upsert(name, state="closed")


def cmd_reap(ns):
    """Close idle daemons, remove orphan files, flag version mismatches."""
    dry = getattr(ns, "dry_run", False)
    quiet = getattr(ns, "quiet", False)
    limit = getattr(ns, "idle_hours", 4.0) * 3600
    closed = orphans = flagged = 0

    def say(msg):
        if not quiet:
            print(msg)

    for r in _rows():
        name, st, idle, e = r["name"], r["state"], r["_idle_s"], r["_e"]
        act = None
        bh = e.get("stack") in ("bh", "browser-harness")
        if bh:
            continue
        if st == "live" and idle is not None and idle > limit:
            act = f"close {name} (idle {r['idle']})"
        elif st == "version-mismatch":
            flagged += 1
            say(f"{'would ' if dry else ''}flag {name}: daemon {r['_ds']['version']} != agent-browser {ledger.ab_version()}")
            if getattr(ns, "restart_mismatch", False) and idle is not None and idle >= 600:
                act = f"close {name} (version mismatch)"
        elif st == "orphan":
            say(f"{'would ' if dry else ''}remove orphan files for {name}")
            if not dry:
                for x in _EXTS:
                    (ledger.AB_DIR / f"{name}.{x}").unlink(missing_ok=True)
            orphans += 1
        elif st == "stale":
            say(f"{'would ' if dry else ''}mark {name} closed (daemon dead)")
            if not dry:
                ledger.upsert(name, state="closed")
        if act:
            if (e.get("headed") or e.get("profile")) and not getattr(ns, "force", False):
                say(f"skip {name}: headed/profile (use --force)")
                continue
            say(("would " if dry else "") + act)
            if not dry:
                _close(name, r["_ds"]["pid"])
            closed += 1
    if not dry:
        ledger.prune()
    say(f"reap: closed {closed}, orphans removed {orphans}, flagged {flagged}" + (", dry-run" if dry else ""))
    return 0


def cmd_check(ns):
    """Run health checks, print PASS/WARN/FAIL lines, return 1 on any FAIL."""
    fails = 0

    def out(level, msg, fix=None):
        nonlocal fails
        fails += level == "FAIL"
        print(f"{level} {msg}" + (f" | fix: {fix}" if fix else ""))

    if shutil.which(ledger.AB_BIN):
        v = ledger.ab_version()
        out("PASS", f"agent-browser {v or '(version unknown)'}")
    else:
        out("FAIL", f"agent-browser not found ({ledger.AB_BIN})", "npm i -g agent-browser")
    if shutil.which(ledger.BH_BIN):
        out("PASS", "browser-harness on PATH")
    else:
        out("WARN", "browser-harness not found", "install browser-harness or set CLAUDE_BROWSE_BH_BIN")
    from cmd_run import cdp_up
    if cdp_up():
        out("PASS", "Chrome CDP 9222 reachable")
    else:
        out("WARN", "Chrome CDP 9222 not reachable", "start Chrome with --remote-debugging-port=9222")
    try:
        if ledger.LEDGER.exists():
            d = json.loads(ledger.LEDGER.read_text())
            if d.get("version") != 1:
                raise ValueError(f"version {d.get('version')}")
        out("PASS", "ledger ok")
    except (ValueError, OSError, AttributeError) as ex:
        out("FAIL", f"ledger unreadable: {ex}", f"move {ledger.LEDGER} aside")
    rows = _rows()
    names = lambda st: [r["name"] for r in rows if r["state"] == st]
    if names("unmanaged"):
        out("WARN", "unmanaged daemons: " + ", ".join(names("unmanaged")), "browse adopt")
    else:
        out("PASS", "no unmanaged daemons")
    if names("version-mismatch"):
        out("WARN", "version-mismatched daemons: " + ", ".join(names("version-mismatch")),
            "browse reap --restart-mismatch")
    else:
        out("PASS", "no version-mismatched daemons")
    if names("orphan"):
        out("WARN", f"{len(names('orphan'))} orphan state file sets", "browse reap")
    else:
        out("PASS", "no orphan state files")
    try:
        ledger.HOME.mkdir(parents=True, exist_ok=True)
        if not os.access(ledger.HOME, os.W_OK):
            raise OSError("not writable")
        out("PASS", f"{ledger.HOME} writable")
    except OSError:
        out("FAIL", f"{ledger.HOME} not writable", f"chmod u+w {ledger.HOME}")
    return 1 if fails else 0
