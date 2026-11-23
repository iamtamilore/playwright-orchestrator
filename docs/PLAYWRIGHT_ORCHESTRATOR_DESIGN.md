# Playwright Orchestrator Design

Status: implemented design for the system-wide Playwright upgrade.

Date: 2026-11-23

## 1. Goal

Install one browser control path that works from OpenCode and Claude Code without placing a large browser tool schema in every request. The path must preserve signed-in profiles, prevent two processes from using the same persistent profile, support parallel isolated work, and leave the existing browser broker and posting flows operational.

The system has four layers:

1. New worker and coordinator browser work runs through Playwright CLI. The existing Zenpai broker remains as a documented compatibility exception under the same canonical lock.
2. A restricted worker agent can call the CLI but cannot edit files, search the web, or launch other agents.
3. A lean MCP server exposes six orchestration tools to coordinators.
4. A canonical profile lock service protects persistent profiles across agents, scripts, and browsers.

## 2. Source baseline

The design uses Microsoft Playwright CLI package `@playwright/cli` version `0.1.25` and its published `playwright-cli` skill as the canonical command reference. The source video by Brandon Melville was transcribed in full and checked against the upstream package. The upstream repository does not contain the video author's OpenCode agent, command, or memory files, so the local implementation is an adaptation rather than a copy.

Relevant upstream behavior:

- CLI state is held by named sessions using `-s=name`.
- Persistent state uses `open --persistent` or a custom profile directory.
- Snapshots use element references such as `e15`.
- `show` starts the Playwright Dashboard.
- Snapshots and command output can be written to files instead of the session transcript.

## 3. Components

### 3.1 Playwright CLI

The CLI runs browser commands. It is installed globally as `playwright-cli`. It is not wrapped by a second browser framework. The orchestrator requires version `0.1.25`, rejects destructive global commands, and rejects direct persistent-profile or config overrides.

### 3.2 Orchestrator source repository

The implementation lives in `/home/newtazer/repos/playwright-orchestrator`. It contains:

- `src/playwright_orchestrator/server.py`: newline-delimited JSON-RPC MCP server.
- `src/playwright_orchestrator/locks.py`: canonical per-profile lock and live registry service.
- `src/playwright_orchestrator/cli.py`: profile-aware CLI wrapper and lock control commands.
- `src/playwright_orchestrator/artifacts.py`: bounded artifact storage and TTL pruning.
- `templates/opencode/`: OpenCode agent, skill, and command templates.
- `templates/claude/`: Claude Code agent, skill, and command templates.
- `tests/`: unit, integration, configuration, and handshake tests.

A symlink from `/home/newtazer/.local/share/mcp-servers/playwright-orchestrator` points to the source repository. This keeps one installed copy and one versioned source.

### 3.3 OpenCode worker agent

The worker uses `nvidia/minimaxai/minimax-m3.1-flash`. Its permissions allow only:

- the `playwright-orchestrator` skill;
- shell commands for the narrow `playwright-profile run` and `playwright-profile snapshot` wrapper;
- no edit, write, webfetch, websearch, task, subagent, or general shell access.

Raw browser broker tools are denied globally and in the worker. The worker uses Playwright CLI and the narrow profile lock wrapper. Coordinators use the lean MCP server.

### 3.4 Claude Code worker agent

Claude Code receives a separate native agent definition with the same least-privilege boundary. It receives only the six `playwright-orchestrator` MCP tools. It has no shell, file-editing, web, task, or subagent tool. It does not share OpenCode-specific permission keys.

### 3.5 `/playwright` command

Both clients receive a global command that explains the workflow, selects a profile, and dispatches browser work to the worker. The command does not contain credentials and does not copy page data into chat.

## 4. Trust boundaries

Page content is untrusted. A snapshot, title, form value, downloaded file, or dashboard annotation can contain instructions. The worker treats all of it as data.

The worker cannot write repository files or use network research tools. It can call only browser actions and the lock wrapper. It cannot start another agent.

The coordinator can call six MCP tools. It cannot call the raw broker unless it is running as the worker. The MCP server rejects arbitrary command strings that do not map to supported Playwright CLI operations.

The profile directory contains authenticated browser state. It is never copied into an artifact, a prompt, or a public repository.

## 5. Profile model

A profile name maps to one persistent Chromium user-data directory under `/home/newtazer/.local/share/playwright-mcp/profiles`. The live metadata remains in `/home/newtazer/.local/share/playwright-mcp/profiles.json`.

Two profile modes exist:

- Persistent: a named profile with an on-disk user-data directory. It requires the profile lock.
- Ephemeral: a temporary isolated session. It may run in parallel and uses a temporary user-data directory that is deleted after the run.

The Chromium executable is selected from the existing health cache. Chromium `1234` remains the preferred signed-in-profile build because cookie encryption is build-sensitive. Every launch uses these Chromium arguments:

- `--no-sandbox`
- `--disable-dev-shm-usage`

A launch fails with a clear error if the preferred executable is missing. The installer does not silently switch builds for a signed-in profile.

## 6. Lock lifecycle

Each persistent profile has one lock file under `/home/newtazer/.local/share/playwright-orchestrator/locks`. The lock daemon acquires the file with non-blocking `flock(LOCK_EX | LOCK_NB)`.

The daemon writes a live record containing profile, PID, session name, display, start time, and last activity. Registry writes use a temporary file and atomic rename.

The lock order is fixed:

1. Acquire the profile lock.
2. Register the live browser.
3. Launch or attach the browser.
4. Run the requested actions.
5. Close the browser.
6. Remove the live registry record.
7. Release the profile lock.

If steps 3 through 6 fail, the daemon still closes only its own named session and releases its own lock. It never calls `close-all` or `kill-all`.

A second process cannot acquire the same profile lock. It receives the current owner and session name. Ephemeral profiles do not use named locks and can run in parallel.

The live registry is observability, not the lock. Correctness comes from the kernel-held `flock`. Stale registry rows are removed when their owner PID is gone.

## 7. Display and authentication

Headless work uses the current display environment. It does not require an X server.

Headed work supports:

- `DISPLAY=:0`, the physical desktop.
- `DISPLAY=:99`, the virtual display used for browser takeover.
- A missing or unreachable display, which returns `display_unavailable` rather than falling back to headless without permission.

Authentication pauses in two forms:

1. `/dev/shm/.auth_pw` exists. The service reports `auth_waiting` and does not advance the action queue.
2. Interactive handoff is allowed while the marker exists. It opens a headed browser on the requested display, retains the profile lock, and returns a resumable session handle. The human completes authentication, clears the marker, and resumes the same named session.

The handoff never stores the password in logs, registry data, artifacts, or the MCP response. Authentication state remains in the persistent Chromium profile.

## 8. MCP tools

The MCP server exposes exactly these tools:

- `pw_run_session`: run an ordered list of Playwright CLI actions against one profile.
- `pw_parallel_batch`: run independent ephemeral or persistent jobs with per-profile collision handling.
- `pw_snapshot`: save a snapshot artifact, return its path, and list the element references it contains.
- `pw_profile_locks`: list lock owners and live sessions.
- `pw_dashboard_status`: report whether the Playwright Dashboard can start, whether it is running, and whether authentication is waiting.
- `pw_interactive_handoff`: open or attach a headed session for human action and return a resumable handle.

The server uses stdio JSON-RPC. It supports `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`, and a clean EOF shutdown.

## 9. Artifact storage

Artifacts live under `/mnt/2tb/browser-artifacts/playwright-orchestrator` when the drive is mounted. They fall back to `/home/newtazer/.local/share/playwright-orchestrator/artifacts` only when needed.

The store has two bounds:

- Files older than 48 hours are removed.
- If the total remains above 500 MB, the oldest files are removed until the store is below the bound.

Pruning runs before and after each job and after a completed batch. A store lock serializes pruning. It never removes active session logs or profile data. Snapshots are returned by path with a short preview. The full snapshot stays on disk.

## 10. Compatibility hooks

The existing browser broker remains available for its current callers. Its lease registry remains a second collision check. New orchestration does not use `close-all` or `kill-all`.

The Zenpai posting paths use the canonical lock wrapper:

- `scripts/outreach/b_seq.mjs`
- `scripts/posting/headless_upload.py`
- `scripts/posting/ig_hygiene_atom.py`

`b_seq.mjs` acquires the named profile lock before launching its broker and releases it after that broker closes. `headless_upload.py` inherits the same lock through `b_seq.mjs`. `ig_hygiene_atom.py` acquires the canonical lock directly before its existing Python Playwright work. These two legacy paths are formal compatibility exceptions. New worker and coordinator work uses Playwright CLI only. The existing posting ledgers and pipeline claims remain authoritative for job ownership.

## 11. Failure handling

- Profile lock held: return the owner and do not launch a browser.
- Missing Chromium: return an actionable error and do not switch signed-in builds.
- Missing display: return `display_unavailable`.
- Authentication marker present: pause before the next action and report `auth_waiting`.
- CLI timeout: close only the owned session, release only the owned lock, and preserve the error.
- MCP client disconnect: leave no lock daemon or browser session running for an ephemeral job.
- Artifact limit exceeded: prune before reporting a path.

## 12. Verification matrix

| Area | Test | Pass condition |
| --- | --- | --- |
| Snapshot | CLI snapshot and reference extraction | Snapshot file exists and contains usable element refs |
| Ref fill | Fill a referenced element | The fake CLI receives the exact ref and value |
| Parallel workers | Three ephemeral workers | All three run at the same time and return distinct results |
| Profile collision | Two workers use one persistent profile | Exactly one starts and the other reports the owner |
| Dashboard | Dashboard status and auth pause | Status is explicit and an auth marker pauses work |
| MCP | Initialization and tool listing | Handshake succeeds and exactly six tools are exposed |
| Configuration | OpenCode and Claude templates | Required agent, skill, command, and MCP entries exist |
| Lock | Atomic registry update and stale cleanup | Registry stays valid JSON and stale owners are removed |
| Artifacts | TTL and size pruning | Old files and excess bytes are removed |
| Compatibility | Posting hooks | Each hook references the canonical lock wrapper |

## 13. Release rules

The dedicated repository and the Zenpai repository use conventional commits. The Zenpai commit excludes mutable Batch 4 progress, manifests, ledgers, and schedule files. Public repository text contains no em dash or en dash. The release tag follows the package version.
