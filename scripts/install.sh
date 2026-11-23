#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_BIN="${NODE_BIN:-$HOME/.local/node-22/bin}"
MCP_LINK_DIR="$HOME/.local/share/mcp-servers"
MCP_LINK="$MCP_LINK_DIR/playwright-orchestrator"
LOCAL_BIN="$HOME/.local/bin"
CLI_VERSION="0.1.25"

mkdir -p "$MCP_LINK_DIR" "$LOCAL_BIN" "$HOME/.config/opencode/agent" "$HOME/.config/opencode/command" \
  "$HOME/.config/opencode/skills/playwright-cli" "$HOME/.config/opencode/skills/playwright-orchestrator" \
  "$HOME/.claude/agents" "$HOME/.claude/commands" "$HOME/.claude/skills/playwright-cli" \
  "$HOME/.claude/skills/playwright-orchestrator"

if [[ ! -x "$NODE_BIN/npm" ]]; then
  echo "Node 22 is required at $NODE_BIN" >&2
  exit 1
fi

export PATH="$NODE_BIN:$PATH"
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 "$NODE_BIN/npm" install -g "@playwright/cli@$CLI_VERSION"
NPM_PREFIX="$("$NODE_BIN/npm" prefix -g)"
CLI_JS="$NPM_PREFIX/lib/node_modules/@playwright/cli/playwright-cli.js"
for cli_path in "$LOCAL_BIN/playwright-cli" "$NPM_PREFIX/bin/playwright-cli"; do
  rm -f "$cli_path"
  cat > "$cli_path" <<EOF
#!/usr/bin/env bash
export PATH="$NODE_BIN:\$PATH"
exec "$NODE_BIN/node" "$CLI_JS" "\$@"
EOF
  chmod 0755 "$cli_path"
done
INSTALLED_CLI_VERSION="$("$LOCAL_BIN/playwright-cli" --version)"
if [[ "$INSTALLED_CLI_VERSION" != "$CLI_VERSION" ]]; then
  echo "Playwright CLI version $INSTALLED_CLI_VERSION is installed; expected $CLI_VERSION" >&2
  exit 1
fi

if [[ -e "$MCP_LINK" || -L "$MCP_LINK" ]]; then
  rm -rf "$MCP_LINK"
fi
ln -s "$REPO_DIR" "$MCP_LINK"

rm -rf "$REPO_DIR/.venv"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -e "$REPO_DIR"
ln -sfn "$REPO_DIR/.venv/bin/playwright-profile" "$LOCAL_BIN/playwright-profile"

install -m 0644 "$REPO_DIR/templates/opencode/agent/playwright-worker.md" "$HOME/.config/opencode/agent/playwright-worker.md"
install -m 0644 "$REPO_DIR/templates/opencode/command/playwright.md" "$HOME/.config/opencode/command/playwright.md"
install -m 0644 "$REPO_DIR/templates/opencode/skills/playwright-orchestrator/SKILL.md" "$HOME/.config/opencode/skills/playwright-orchestrator/SKILL.md"
install -m 0644 "$REPO_DIR/templates/common/skills/playwright-cli/SKILL.md" "$HOME/.config/opencode/skills/playwright-cli/SKILL.md"

install -m 0644 "$REPO_DIR/templates/claude/agents/playwright-worker.md" "$HOME/.claude/agents/playwright-worker.md"
install -m 0644 "$REPO_DIR/templates/claude/commands/playwright.md" "$HOME/.claude/commands/playwright.md"
install -m 0644 "$REPO_DIR/templates/claude/skills/playwright-orchestrator/SKILL.md" "$HOME/.claude/skills/playwright-orchestrator/SKILL.md"
install -m 0644 "$REPO_DIR/templates/common/skills/playwright-cli/SKILL.md" "$HOME/.claude/skills/playwright-cli/SKILL.md"

if command -v opencode >/dev/null 2>&1; then
  opencode mcp add playwright-orchestrator --global -- \
    "$REPO_DIR/.venv/bin/python" -m playwright_orchestrator.server
fi

python3 <<'PY'
import json
from pathlib import Path

path = Path.home() / ".config/opencode/opencode.jsonc"
data = json.loads(path.read_text(encoding="utf-8"))
legacy = data.pop("permission", {})
current = data.get("permissions", {})
if isinstance(current, list):
    rules = list(current)
else:
    source = dict(current)
    for key, value in legacy.items():
        source.setdefault(key, value)
    rules = []
    for action, value in source.items():
        if action == "browser_*":
            continue
        if isinstance(value, dict):
            rules.extend(
                {"action": action, "resource": resource, "effect": effect}
                for resource, effect in value.items()
            )
        else:
            rules.append({"action": action, "resource": "*", "effect": value})

rules = [rule for rule in rules if rule.get("action") != "browser"]
rules.extend(
    [
        {"action": "browser", "resource": "*", "effect": "deny"},
        {"action": "browser_close_all", "resource": "*", "effect": "deny"},
        {"action": "browser_close_profile", "resource": "*", "effect": "deny"},
        {"action": "browser_preview", "resource": "*", "effect": "deny"},
        {"action": "browser_profiles", "resource": "*", "effect": "deny"},
    ]
)
data["permissions"] = rules
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

python3 - "$REPO_DIR/.venv/bin/python" <<'PY'
import json
import sys
from pathlib import Path

path = Path.home() / ".claude.json"
data = json.loads(path.read_text(encoding="utf-8"))
servers = data.setdefault("mcpServers", {})
servers["playwright-orchestrator"] = {
    "type": "stdio",
    "command": sys.argv[1],
    "args": ["-m", "playwright_orchestrator.server"],
    "env": {},
}
path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
