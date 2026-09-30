#!/usr/bin/env bash
# Symlink claude-browse into ~/.claude for local use (no plugin install). --uninstall removes.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
C="$HOME/.claude"
LINKS=(
  "$REPO/agents/browser.md|$C/agents/browser.md"
  "$REPO/commands/browse.md|$C/commands/browse.md"
  "$REPO/commands/browse-ls.md|$C/commands/browse-ls.md"
  "$REPO/skills/browse-router|$C/skills/browse-router"
  "$REPO/bin/browse|$HOME/.local/bin/browse"
)
remove() {
  for l in "${LINKS[@]}"; do
    dst=${l#*|}
    if [ -L "$dst" ]; then
      case "$(readlink "$dst")" in
        "$REPO"/*) rm "$dst"; echo "removed $dst" ;;
        *) echo "skip $dst: symlink not owned by this repo" ;;
      esac
    fi
  done
}
if [ "${1:-}" = "--uninstall" ]; then remove; exit 0; fi
if grep -q "claude-browse@" "$C/plugins/installed_plugins.json" 2>/dev/null; then
  echo "claude-browse plugin is installed; removing local symlinks to avoid duplicates"
  remove; exit 0
fi
for l in "${LINKS[@]}"; do
  src=${l%%|*}; dst=${l#*|}
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then echo "skip $dst: exists and is not a symlink"; continue; fi
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "linked $dst -> $src"
done
