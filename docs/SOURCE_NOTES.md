# Source Notes

## Primary source

- Video ID: `c2Jj2XIPduk`
- Title: `Playwright CLI + OpenCode Just Changed Browser Automation Forever`
- Channel: `Brandon Melville`
- Duration: 481 seconds
- Source URL: `https://www.youtube.com/watch?v=c2Jj2XIPduk`

The full video was downloaded. The local copy and its metadata were kept outside the public repository. A full CPU `int8` `faster-whisper` `large-v3` transcription produced 102 segments from `0:00` to `478.64` seconds. The YouTube subtitle endpoint returned HTTP 429, so the local transcription supplied the required text.

## Upstream implementation

- Repository: `https://github.com/microsoft/playwright-cli`
- Package: `@playwright/cli`
- Version used: `0.1.25`
- Upstream skill: `skills/playwright-cli/SKILL.md`

The upstream README and skill were checked directly. They establish the supported session, persistent profile, snapshot, ref, dashboard, and configuration behavior.

## Adaptation boundary

The upstream repository does not contain the video author's `opencode.json`, `agents.md`, `MEMORY.md`, `.opencode/agents/playwright-worker.md`, `.opencode/commands/playwright.md`, or `.opencode/skills/playwright-orchestrator/SKILL.md`. This project does not claim that those files came from upstream. The worker, command, MCP server, lock service, and tests are a local adaptation of the workflow shown in the video.

## Browser build

The installed machine has signed-in profiles tied to Chromium `1234` for cookie encryption. The orchestrator uses the existing browser health cache and does not download or silently substitute another Chromium build for a persistent profile.
