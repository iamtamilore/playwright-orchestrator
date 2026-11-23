---
description: Run a browser task with the restricted Playwright worker.
allowed-tools: Bash(playwright-cli:*), Bash(playwright-profile:*), Skill(playwright-cli), Skill(playwright-orchestrator)
argument-hint: [profile and task]
---

Run the requested browser task as the Playwright worker.

Choose the named profile supplied by the user. If no profile is supplied, list the available profiles with `playwright-profile locks` and ask for the correct profile before touching a persistent account.

Keep one profile lock for the whole task. Use snapshots to obtain element refs. Save large output as an artifact and return its path. Stop and report `profile_busy` if another owner holds the profile.

Do not use web research, edit files, or start another agent.
