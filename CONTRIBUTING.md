# Contributing to Claude Token Monitor

Thanks for your interest in contributing. This document covers how to
propose changes, the expected coding style, and — importantly — the manual
testing that's required for changes to the desktop UI, since this project's
GUI cannot be exercised by CI.

## Before You Start

- Check open issues and pull requests to avoid duplicate work.
- For anything non-trivial (new features, architectural changes, new
  dependencies), consider opening an issue first to discuss the approach.

## Development Setup

1. Fork the repository and clone your fork.
2. Install Python 3.10+.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the app locally to confirm your environment works:
   ```bash
   python -m app.main
   ```
5. If you are working on the browser extension, load the `extension/`
   folder as an unpacked extension via `chrome://extensions` with Developer
   Mode enabled.

## Making Changes

1. Create a feature branch off `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make focused, logically-scoped commits with clear messages describing
   *why* the change was made, not just what changed.
3. Keep pull requests reasonably small and focused on a single concern —
   this makes review (and manual testing) practical.

## Coding Style

- Follow standard Python style (PEP 8). We use [`ruff`](https://docs.astral.sh/ruff/)
  for linting; run it locally before opening a PR:
  ```bash
  pip install ruff
  ruff check .
  ```
- Prefer clear, descriptive names over abbreviations, especially for
  anything touching token/cost calculations or local data handling.
- Keep functions focused; avoid mixing UI code (widget/tray rendering) with
  data/parsing logic (watcher, storage, fetcher) where practical, to keep
  the non-UI parts testable.
- For JavaScript in `extension/`, match the existing style in
  `background.js` / `content.js` / `popup/popup.js` (plain JS, no build
  step is currently used).
- Any code path touching the `sessionKey` cookie, `app/config.json`, or the
  local HTTP server on port `9988` should be reviewed with extra care for
  privacy/security implications — see `SECURITY.md`.

## CI Expectations

Every pull request runs automated CI which:

- Installs dependencies from `requirements.txt`.
- Lints the codebase with `ruff check .`.
- Runs a Python syntax/compile smoke check (`compileall`) over `app/`.
- Validates that `extension/manifest.json` is well-formed JSON.

CI does **not**, and cannot, launch or interact with the actual desktop HUD,
system tray icon, or browser extension UI — this is a Windows desktop
GUI application built on `customtkinter` and `pystray`, plus a Chrome
extension, neither of which can be meaningfully exercised in a headless CI
runner. A passing CI run only confirms the code lints cleanly and compiles;
it says nothing about whether the widget renders correctly, the tray menu
works, drag/collapse behavior functions, or the extension syncs data
correctly.

## Manual Testing (Required for UI/Behavioral Changes)

If your change touches any of the following, you must manually verify it
on a real machine (Windows, since that's the supported platform) and
describe what you tested in the pull request description:

- The floating HUD widget (`app/widget.py`) — layout, colors/states
  (green/amber/red), drag-and-drop position persistence, collapse/expand.
- The system tray integration (`app/tray.py`) — menu items, "Setup Session
  Key", "Sync Now", show/hide.
- The log watcher (`app/watcher.py`) — verify it picks up new
  `~/.claude/projects/*.jsonl` entries and updates token/cost figures
  correctly.
- The local HTTP server (`app/server.py`) — verify it still binds only to
  `127.0.0.1:9988` and correctly handles pushes from the extension.
- The direct API fetcher (`app/claude_fetcher.py`) — verify standalone mode
  still authenticates and syncs quota using a `sessionKey`.
- The browser extension (`extension/`) — reload it unpacked in Chrome/Edge/
  Brave, confirm the popup, background service worker, and content script
  still function against `claude.ai`, and that `manifest.json` permissions
  weren't broadened beyond what's needed.

Please include in your PR description:
- What you changed and why.
- What you manually tested, and on what OS/browser.
- Screenshots or a short screen recording for any visual/UI change.

## Pull Request Checklist

- [ ] Code lints cleanly (`ruff check .`).
- [ ] Changes are focused and the commit history is reasonably clean.
- [ ] Manual testing performed and described for any UI/behavioral change.
- [ ] No secrets, session keys, or personal usage data included in the diff
      or in any added test fixtures.
- [ ] Documentation (`README.md`, `README.id.md`, or this file) updated if
      behavior, setup steps, or permissions changed.

## Reporting Bugs vs. Security Issues

- Regular bugs: open a GitHub issue with reproduction steps.
- Security or privacy issues (e.g., anything involving session key
  handling, the local HTTP server, or the extension's data handling):
  do **not** open a public issue — follow `SECURITY.md` instead.
