# Memory

## Current release

- Version: `0.1.0`
- Date: 2026-11-23
- Playwright CLI: `@playwright/cli` `0.1.25`
- Source repository: `/home/newtazer/repos/playwright-orchestrator`
- Installed MCP link: `~/.local/share/mcp-servers/playwright-orchestrator`

## Decisions

- The worker uses `nvidia/minimaxai/minimax-m3.1-flash` in OpenCode.
- The Claude Code worker is a separate native agent with Bash and Skill access only.
- Coordinators use the six-tool lean MCP server.
- The raw browser broker remains available for compatibility but is denied globally in OpenCode.
- The existing browser broker acquires the canonical lock when it is used directly.
- `b_seq.mjs` owns the lock for Zenpai outreach and headless upload sequences.
- Instagram hygiene acquires the canonical lock directly.
- Persistent profiles keep Chromium `1234`.
- Artifacts use `/mnt/2tb/browser-artifacts/playwright-orchestrator` when available.
- The artifact limits are 48 hours and 500 MB.

## Verification state

The test suite covers the six-tool MCP handshake, live global configuration handshake, snapshot and ref fill, three parallel ephemeral workers, persistent profile collision, dashboard and authentication pause, lock registry integrity, and artifact pruning.
