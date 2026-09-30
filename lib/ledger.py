"""Session ledger and log I/O for claude-browse."""
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_BROWSE_HOME", "~/.claude-browse")).expanduser()
AB_DIR = Path(os.environ.get("CLAUDE_BROWSE_AB_DIR", "~/.agent-browser")).expanduser()
AB_BIN = os.environ.get("CLAUDE_BROWSE_AB_BIN", "agent-browser")
BH_BIN = os.environ.get("CLAUDE_BROWSE_BH_BIN", "browser-harness")
LEDGER = HOME / "sessions.json"
LOGS = HOME / "logs"
SHOTS = HOME / "shots"

_ab_version = None


def now_iso():
    """Current UTC time, seconds precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    """Parse a now_iso string, returning None on failure."""
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def valid_name(name):
    """True if name is a safe session name."""
    return bool(_NAME_RE.match(name or "")) and name not in ("browsers", "sessions")


def _is_ab_process(pid):
    """True if pid is an agent-browser process."""
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "agent-browser" in r.stdout


def load(recover=True):
    """Read the ledger; recover=False is read-only and never renames a corrupt file."""
    if recover:
        HOME.mkdir(parents=True, exist_ok=True)
    if LEDGER.exists():
        try:
            data = json.loads(LEDGER.read_text())
            if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
                return data
        except (ValueError, OSError):
            pass
        if recover:
            LEDGER.rename(LEDGER.with_name(f"sessions.json.corrupt-{int(time.time() * 1000)}"))
    return {"version": 1, "sessions": {}}


def save(data):
    """Write the ledger atomically via tmp file and os.replace."""
    HOME.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=HOME, prefix=".sessions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, LEDGER)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextmanager
def locked():
    """Hold the ledger flock, yield the data dict, write back if changed."""
    HOME.mkdir(parents=True, exist_ok=True)
    with open(HOME / ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        data = load()
        before = json.dumps(data, sort_keys=True)
        yield data
        if json.dumps(data, sort_keys=True) != before or not LEDGER.exists():
            save(data)


def new_session(name, purpose, stack, url=None, profile=None, allowed_domains=(),
                allowed_tools=(), headed=False):
    """Build a fresh ledger entry for a session."""
    ts = now_iso()
    return {
        "purpose": purpose,
        "owner": {
            "claude_session": os.environ.get("CLAUDE_CODE_SESSION_ID"),
            "job_dir": os.environ.get("CLAUDE_JOB_DIR"),
            "cwd": os.getcwd(),
            "ppid": os.getppid(),
        },
        "stack": stack,
        "url": url,
        "profile": profile,
        "allowed_domains": list(allowed_domains),
        "allowed_tools": list(allowed_tools),
        "headed": bool(headed),
        "created": ts,
        "last_used": ts,
        "pid": 0,
        "daemon_version": None,
        "state": "starting",
    }


def upsert(name, **fields):
    """Merge fields into a session entry, creating it if absent."""
    with locked() as data:
        entry = data["sessions"].setdefault(name, {})
        entry.update(fields)
        return dict(entry)


def get(name):
    """Return a session entry or None."""
    return load()["sessions"].get(name)


def remove(name):
    """Delete a session entry if present."""
    with locked() as data:
        data["sessions"].pop(name, None)


def append_log(name, entry):
    """Append one JSON line to the session log."""
    LOGS.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("ts", now_iso())
    with open(LOGS / f"{name}.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_log(name, n=20):
    """Return the last n log entries, oldest first."""
    p = LOGS / f"{name}.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-n:] if n else out


def _read(name, ext):
    """Read a daemon state file, None if absent."""
    try:
        return (AB_DIR / f"{name}.{ext}").read_text().strip()
    except OSError:
        return None


def daemon_state(name):
    """Report pid, liveness, version, socket and target for an agent-browser daemon."""
    pid = None
    raw = _read(name, "pid")
    if raw and raw.isdigit():
        pid = int(raw)
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except PermissionError:
            alive = True
        except OSError:
            alive = False
    target = None
    raw = _read(name, "target")
    if raw:
        try:
            target = json.loads(raw)
        except ValueError:
            target = None
    return {"pid": pid, "alive": alive, "version": _read(name, "version") or None,
            "sock": (AB_DIR / f"{name}.sock").exists(), "target": target}


def list_daemons():
    """Names in AB_DIR with a .pid, .sock or .config file."""
    if not AB_DIR.is_dir():
        return []
    names = {p.stem for p in AB_DIR.iterdir()
             if p.suffix in (".pid", ".sock", ".config") and valid_name(p.stem)}
    return sorted(names)


def ab_version():
    """Semver reported by agent-browser --version, cached; None if unavailable."""
    global _ab_version
    if _ab_version is None:
        try:
            r = subprocess.run([AB_BIN, "--version"], capture_output=True, text=True, timeout=10)
            m = re.search(r"\d+\.\d+\.\d+", r.stdout + r.stderr)
            _ab_version = m.group(0) if m else ""
        except (OSError, subprocess.SubprocessError):
            _ab_version = ""
    return _ab_version or None


def prune(days_closed=7, log_days=30):
    """Drop closed entries older than days_closed and logs older than log_days."""
    removed, logs_removed = [], []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_closed)
    with locked() as data:
        for name, e in list(data["sessions"].items()):
            t = _parse_iso(e.get("last_used"))
            if e.get("state") == "closed" and t and t < cutoff:
                del data["sessions"][name]
                removed.append(name)
    if LOGS.is_dir():
        limit = time.time() - log_days * 86400
        for p in LOGS.glob("*.jsonl"):
            if p.stat().st_mtime < limit:
                p.unlink()
                logs_removed.append(p.stem)
    return {"sessions_removed": removed, "logs_removed": logs_removed}


def daemon_mtime(name):
    """Epoch mtime of the daemon pid file, or None. Proxy for age/idle of unmanaged daemons."""
    for ext in ("pid", "config"):
        f = AB_DIR / f"{name}.{ext}"
        if f.exists():
            return f.stat().st_mtime
    return None
