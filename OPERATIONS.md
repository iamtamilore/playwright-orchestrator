# Operations

## Install or repair

```bash
bash /home/newtazer/repos/playwright-orchestrator/scripts/install.sh
```

The installer is idempotent. It replaces the local virtual environment and refreshes the global client templates.

## Status

```bash
playwright-cli --version
playwright-profile locks
opencode mcp list
```

The MCP entry name is `playwright-orchestrator`.

## Locks

A persistent profile has one atomic `flock` file under:

```text
~/.local/share/playwright-orchestrator/locks/
```

The live registry is:

```text
~/.local/share/playwright-orchestrator/live_browsers.json
```

The registry is observability. The kernel-held `flock` is the collision control.

A stale daemon exits when its owning server dies. A manual status check must not be used to decide that a lock is free. Try the workflow. The lock service returns `profile_busy` with the owner when the lock is held.

## Displays

- `:0` is the physical desktop.
- `:99` is the virtual display.
- A missing display returns `display_unavailable`.
- Headless work does not need an X server.

## Authentication

The marker file is:

```text
/dev/shm/.auth_pw
```

When it exists, the runner reports `auth_waiting` before the next action. `pw_interactive_handoff` is allowed while the marker exists. It opens a headed profile, retains the profile lock, and returns the session to resume after the human clears the marker. The marker content is never copied into artifacts or logs.

## Dashboard

`pw_dashboard_status` reports CLI availability, current sessions, display availability, and authentication state. It can start the Playwright Dashboard with `start: true` when the selected display is available.

## Artifacts

Default root:

```text
/mnt/2tb/browser-artifacts/playwright-orchestrator
```

The store removes files older than 48 hours. It then removes the oldest files until the total is no more than 500 MB. It never removes profile data.

## Failure checks

1. `profile_busy`: inspect the owner in the response or `playwright-profile locks`.
2. `display_unavailable`: check `/tmp/.X11-unix/X0` or `/tmp/.X11-unix/X99`.
3. `auth_waiting`: check `/dev/shm/.auth_pw` and use interactive handoff if a human is present.
4. MCP disconnected: check `opencode mcp list`, then run the server module by hand with `initialize` and `tools/list` requests.
5. CLI says Node 18: use `~/.local/bin/playwright-cli`, which forces Node 22.

## Compatibility hooks

- `scripts/outreach/b_seq.mjs` owns the lock for one broker sequence.
- `scripts/posting/headless_upload.py` reaches the lock through `b_seq.mjs`.
- `scripts/posting/ig_hygiene_atom.py` acquires the lock directly.
- `~/.local/share/playwright-mcp/browser_broker.mjs` acquires the lock when it is used directly.
