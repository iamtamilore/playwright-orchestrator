# Playwright Orchestrator

Profile-safe Playwright CLI orchestration for OpenCode and Claude Code.

## What it provides

- One global Playwright CLI based on Microsoft `@playwright/cli` `0.1.25`.
- One restricted worker agent for each client.
- One global `/playwright` command for each client.
- One lean stdio MCP server with six tools.
- Atomic per-profile `flock` protection.
- Parallel ephemeral browser work.
- Persistent signed-in profiles with a live lock registry.
- Snapshot artifacts bounded by age and total size.
- Human takeover on `DISPLAY=:0` and `DISPLAY=:99`.
- Compatibility hooks for the Zenpai posting and Instagram hygiene paths. The existing Zenpai browser broker remains a documented legacy exception under the same profile lock.

## Install

```bash
bash scripts/install.sh
```

The installer:

1. installs `@playwright/cli@0.1.25` under Node 22;
2. creates the local Python environment;
3. links the MCP server into `~/.local/share/mcp-servers/`;
4. installs the OpenCode and Claude Code agent, skill, and command files;
5. registers the MCP server in both clients;
6. denies the raw browser broker globally. The worker uses Playwright CLI and the narrow profile lock wrapper instead.

It does not download a new Chromium build. Signed-in profiles keep using the existing Chromium `1234` build because their cookie encryption is build-sensitive.

## MCP tools

- `pw_run_session`
- `pw_parallel_batch`
- `pw_snapshot`
- `pw_profile_locks`
- `pw_dashboard_status`
- `pw_interactive_handoff`

## CLI

Run one ordered sequence under a persistent profile lock:

```bash
playwright-profile run \
  --profile linkedin_main \
  --step "open https://example.com" \
  --step "snapshot" \
  --step "close"
```

Save a snapshot and read its refs:

```bash
playwright-profile snapshot --profile linkedin_main --url https://example.com
```

List live profile locks:

```bash
playwright-profile locks
```

## Test

```bash
uv run --with pytest --with-editable . pytest -q
```

The suite covers snapshot and ref fill, three parallel ephemeral workers, persistent profile collision, dashboard and authentication pause, MCP handshake, global configuration handshake, lock registry integrity, and artifact pruning.

## Design

The system design and trust boundaries are in `docs/PLAYWRIGHT_ORCHESTRATOR_DESIGN.md`. The source provenance and upstream references are in `docs/SOURCE_NOTES.md`.

## License

MIT
