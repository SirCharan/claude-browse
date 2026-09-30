"""open, run, log and adopt commands for claude-browse."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

import ledger

STACKS = {"ab": "agent-browser", "bh": "browser-harness"}
NAV = ("open", "goto", "navigate")
CDP = "http://127.0.0.1:9222/json/version"


def _is_bh(entry):
    """True if the session uses browser-harness."""
    return entry.get("stack") in ("bh", "browser-harness")


def _split(s):
    """Split a comma string into a clean list."""
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _exec(cmd, env=None, stdin=None):
    """Run cmd, return (code, stdout, stderr, ms)."""
    t = time.monotonic()
    secs = float(os.environ.get("CLAUDE_BROWSE_TIMEOUT") or 120)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, input=stdin, env=env, timeout=secs)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "timeout after %gs" % secs
    except OSError as e:
        code, out, err = 127, "", str(e)
    return code, out, err, int((time.monotonic() - t) * 1000)


def _bh_env(name):
    """Environment for browser-harness calls."""
    return dict(os.environ, BU_NAME=name)


def _host_ok(host, allowed):
    """True if host equals or is a subdomain of an allowed domain."""
    host = (host or "").lower()
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed)


def _policy(url, allowed):
    """Reason string if url violates the allowlist, else None."""
    if "\\" in url or "@" in url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return "unsafe characters in url"
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        return "url scheme must be http or https"
    if not _host_ok(u.hostname, allowed):
        return "%s not in allowed_domains" % u.hostname
    return None


def _target(args):
    """Second arg when it looks like a selector or URL, else None."""
    if len(args) > 1 and (args[1][:1] in "@#.[" or "://" in args[1]):
        return args[1]
    return None


_NOISE = ("lifecycle", "restoreStatus", "saveStatus")


def _render(data):
    """Trimmed text for a parsed data payload: drop engine noise, unwrap scalars."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in _NOISE}
        for k in ("snapshot", "text", "title", "value", "url", "html"):
            if k in data:
                return str(data[k])
        if len(data) == 1:
            return str(next(iter(data.values())))
        if not data:
            return "ok"
    return json.dumps(data, indent=None)


def cmd_open(ns):
    """Create a ledger entry and open the session."""
    stack = STACKS.get(getattr(ns, "stack", None) or "ab")
    if not stack:
        print("browse: --stack must be ab or bh", file=sys.stderr)
        return 2
    allow = _split(ns.allow_domains)
    if allow and ns.url and _policy(ns.url, allow):
        print("policy: %s" % _policy(ns.url, allow))
        return 3
    entry = ledger.new_session(ns.name, ns.purpose, stack, ns.url, ns.profile,
                               _split(ns.allow_domains), _split(ns.allow_tools), ns.headed)
    if stack == "browser-harness":
        try:
            urllib.request.urlopen(CDP, timeout=2).close()
        except Exception:
            print("browser-harness: Chrome remote debugging not reachable on 9222. "
                  "Enable it (chrome://inspect/#remote-debugging) or use --stack ab.")
            return 4
        entry["state"] = "live"
        ledger.upsert(ns.name, **entry)
        if ns.url:
            code, out, err, ms = _exec([ledger.BH_BIN], _bh_env(ns.name),
                                       "print(new_tab(%r))" % ns.url)
            ledger.append_log(ns.name, {"action": "open", "args": ns.url, "ok": code == 0, "ms": ms,
                                        "err": None if code == 0 else err[-200:]})
            print(out, end="")
            return code
        ledger.append_log(ns.name, {"action": "open", "args": "", "ok": True, "ms": 0})
        return 0
    ledger.upsert(ns.name, **entry)
    code, out, err, ms = 0, "", "", 0
    if ns.url:
        cmd = [ledger.AB_BIN, "--session", ns.name]
        if ns.headed:
            cmd.append("--headed")
        if ns.profile:
            cmd += ["--profile", ns.profile]
        code, out, err, ms = _exec(cmd + ["--json", "open", ns.url])
    d = ledger.daemon_state(ns.name)
    ledger.upsert(ns.name, state="live" if code == 0 else "closed", pid=d["pid"] or 0,
                  daemon_version=d["version"], url=ns.url)
    ledger.append_log(ns.name, {"action": "open", "target": ns.url, "args": ns.url or "",
                                "ok": code == 0, "ms": ms, "url": ns.url,
                                "err": None if code == 0 else err[-200:]})
    if code:
        print(err or out, end="", file=sys.stderr)
    return code


def cmd_run(ns):
    """Run one engine command inside a named session."""
    args = list(ns.args)
    entry = ledger.get(ns.name)
    if entry is None:
        print("browse: no session %r. Create it with: browse open %s --purpose ..." % (ns.name, ns.name))
        return 2
    if not args:
        print("browse run: missing command", file=sys.stderr)
        return 2
    pid = ledger.daemon_state(ns.name)["pid"] or entry.get("pid", 0)
    ledger.upsert(ns.name, last_used=ledger.now_iso(), pid=pid)
    allowed = entry.get("allowed_domains") or []
    if _is_bh(entry):
        for url in re.findall(r"https?://[^\s'\"]+", " ".join(args)) if allowed else []:
            why = _policy(url, allowed)
            if why:
                print("policy: %s" % why)
                ledger.append_log(ns.name, {"action": "bh", "args": url[:200], "ok": False,
                                            "ms": 0, "err": "policy"})
                return 3
        code, out, err, ms = _exec([ledger.BH_BIN], _bh_env(ns.name), " ".join(args))
        ledger.append_log(ns.name, {"action": "bh", "args": " ".join(args)[:200], "ok": code == 0,
                                    "ms": ms, "err": None if code == 0 else err[-200:]})
        print(out, end="")
        if code:
            print(err, end="", file=sys.stderr)
        return code
    verb = next((a for a in args if not a.startswith("-")), args[0])
    rest = args[args.index(verb) + 1:]
    raw = next((a for a in rest if not a.startswith("-")), None)
    if verb in NAV and allowed and raw:
        why = _policy(raw, allowed)
        if why:
            print("policy: %s" % why)
            ledger.append_log(ns.name, {"action": verb, "target": raw, "args": raw[:200],
                                        "ok": False, "ms": 0, "err": "policy"})
            return 3
    code, out, err, ms = _exec([ledger.AB_BIN, "--session", ns.name, "--json", *args])
    ok, data, log = code == 0, None, {}
    try:
        env = json.loads(out)
        data = env.get("data") if isinstance(env, dict) else env
        if isinstance(env, dict) and env.get("success") is False:
            ok = False
        print(_render(data))
    except ValueError:
        print(out, end="")
    if isinstance(data, dict):
        log["url"] = data.get("url")
        if "snapshot" in data:
            log["snapshot_ref"] = hashlib.sha1(str(data["snapshot"]).encode()).hexdigest()[:8]
    shot = None
    if args[0] == "screenshot" and len(args) > 1 and not args[1].startswith("-"):
        shot = args[1]
    ledger.append_log(ns.name, {"action": args[0], "target": _target(args),
                                "args": " ".join(args[1:])[:200], "ok": ok, "ms": ms,
                                "url": log.get("url"), "snapshot_ref": log.get("snapshot_ref"),
                                "screenshot": shot, "err": None if ok else err[-200:]})
    upd = {}
    if log.get("url"):
        upd["url"] = log["url"]
    if args[0] == "close":
        upd["state"] = "closed"
    if upd:
        ledger.upsert(ns.name, **upd)
    if err and not ok:
        print(err, end="", file=sys.stderr)
    return code if code else (0 if ok else 1)


def cmd_log(ns):
    """Print the last n log entries for a session."""
    rows = ledger.read_log(ns.name, ns.n)
    for r in rows:
        if ns.json:
            print(json.dumps(r))
        else:
            print("%-20s %-10s %-4s %5sms %s" % (r.get("ts", ""), r.get("action", ""),
                  "ok" if r.get("ok") else "FAIL", r.get("ms", ""), r.get("args") or r.get("target") or ""))
    return 0


def cmd_adopt(ns):
    """Register unmanaged daemons in the ledger."""
    known = ledger.load()["sessions"]
    count = 0
    for name in ledger.list_daemons():
        if name in known:
            continue
        d = ledger.daemon_state(name)
        e = ledger.new_session(name, "legacy (unknown)", "agent-browser")
        e.update(state="live" if d["alive"] else "closed", pid=d["pid"] or 0, daemon_version=d["version"])
        ledger.upsert(name, **e)
        count += 1
    print("adopted %d" % count)
    return 0
