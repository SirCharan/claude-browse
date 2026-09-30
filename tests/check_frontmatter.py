"""Check frontmatter and line limits of the agent, command and skill files."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# path -> (required keys, max body lines)
FILES = {
    "agents/browser.md": (("name", "description", "tools", "model"), 120),
    "commands/browse.md": (("description",), 120),
    "commands/browse-ls.md": (("description",), 120),
    "skills/browse-router/SKILL.md": (("name", "description"), 40),
}


def parse(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = {}
            for ln in lines[1:i]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    fm[k.strip()] = v.strip()
            return fm, lines[i + 1:]
    return None, lines


def main():
    errs = []
    for rel, (keys, limit) in FILES.items():
        p = ROOT / rel
        if not p.exists():
            errs.append(f"{rel}: missing")
            continue
        fm, body = parse(p.read_text())
        if fm is None:
            errs.append(f"{rel}: no frontmatter")
            continue
        errs += [f"{rel}: missing key {k}" for k in keys if not fm.get(k)]
        if len(body) > limit:
            errs.append(f"{rel}: body {len(body)} lines > {limit}")
        if rel == "agents/browser.md" and fm.get("model") != "sonnet":
            errs.append(f"{rel}: model must be sonnet")
    for e in errs:
        print("FAIL", e)
    if not errs:
        print("ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
