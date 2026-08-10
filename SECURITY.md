# Security Policy

## Scope

Claude Token Monitor is a local-first desktop application (Python) with an
optional companion browser extension. It is designed to run entirely on the
user's own machine and includes several components that are security- and
privacy-sensitive:

- **Local usage/token data**: the app reads and stores Claude Code CLI usage
  logs (`~/.claude/projects/*.jsonl`) and Claude.ai usage statistics in a
  local file (`app/usage_data.json`).
- **Session/credential material**: in "Standalone Mode" the app can read or
  store a Claude.ai `sessionKey` cookie value (`app/config.json`) in order to
  query usage directly from the Claude.ai API.
- **Local network service**: the desktop app runs a local HTTP server bound
  to `127.0.0.1:9988` to receive pushes from the browser extension.
- **Browser extension**: the Chrome/Chromium extension (`extension/`) runs
  content scripts against `claude.ai` and communicates with the local HTTP
  server.

Any vulnerability affecting the handling, storage, transmission, or exposure
of this local data — including but not limited to session key handling,
the local HTTP server binding, the browser extension's permissions or
messaging, or any code path that could leak this data off the local machine
— is in scope for this policy.

Out of scope: issues that require the attacker to already have local code
execution or full filesystem access on the user's machine (at that point the
local data is already exposed by design, since this is a local-first tool),
and vulnerabilities in third-party dependencies that should instead be
reported upstream (though we still want to know about them — see below).

## Reporting a Vulnerability

Please report security vulnerabilities using **GitHub Security Advisories**:

1. Go to the repository's **Security** tab.
2. Select **Report a vulnerability** to open a new private security advisory.
3. Include as much detail as possible: affected component/file, reproduction
   steps, potential impact, and any relevant logs or proof-of-concept.

Do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests, since these are visible to everyone.

## Response Targets

- **Acknowledgment**: we aim to acknowledge new reports within **72 hours**.
- **Resolution/disclosure**: we aim to resolve and, if applicable, coordinate
  public disclosure within **90 days** of the initial report, depending on
  complexity and severity.

You will be kept informed of progress via the private security advisory
thread throughout the process.

## Supported Versions

This project does not currently maintain multiple long-term release
branches. Security fixes are applied to the latest version on the default
branch. Users are encouraged to keep their local copy up to date.
