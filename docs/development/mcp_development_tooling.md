# MCP development tooling

This document describes four Model Context Protocol (MCP) integrations
configured for the **coding environment**, not the product. They give a
coding LLM (Claude Code, or another MCP-capable client) live access to
repository/PR state, version-accurate library documentation, a real browser
against the running Streamlit app, and Hugging Face search - during
development only.

**They are not part of Media-Mix-Lab.** They are not Python dependencies, are
never imported by `ancestry_mmm/`, and are not deployed with the app. See
[Product boundary](#product-boundary) below.

## What MCP is

The Model Context Protocol lets a coding client (an editor extension or CLI)
attach external tool servers that the assistant can call: read a file from
GitHub, look up a library's current docs, drive a browser, search Hugging
Face. Each server is a separate process or remote endpoint the *client*
manages - it has nothing to do with how the application itself runs.

## The four servers

| Server | Purpose | Status |
|---|---|---|
| GitHub MCP | Read commits, PRs, review threads, Actions runs, issues | Installed, read-only |
| Context7 MCP | Version-specific docs for PyMC, PyMC Marketing, ArviZ, Streamlit, pandas, etc. | Installed, unauthenticated |
| Playwright MCP | Drive a real Chromium instance against the local Streamlit dev server | Configured for local-app testing with an origin allowlist |
| Hugging Face MCP | Search models/datasets/papers/Spaces, mainly for Chronos-2 research | Documented, not connected |

## Detected coding client

This repository is developed with **Claude Code running as the VS Code
native extension**. There is no standalone `claude` CLI on this machine, so
MCP servers are configured at the **project level via `.mcp.json`** in the
repository root, which Claude Code reads automatically. If you use a
different MCP-capable client (VS Code + Copilot, Cursor, Codex CLI), adapt
the shape in [`config/mcp/mcp.example.json`](../../config/mcp/mcp.example.json)
to that client's own schema - do not assume `.mcp.json` is universal.

## D-drive paths

All local installs, caches, browser binaries, and generated artefacts live
under `D:\Ancestry-MMM\`, never on `C:`, alongside this project's existing
D-drive convention for its Python/uv environment. For CI or isolated testing,
set the `MMM_DEV_ROOT` environment variable to override the root path (e.g.
`$env:MMM_DEV_ROOT = Join-Path $env:RUNNER_TEMP "Ancestry-MMM"`).

```text
D:\Ancestry-MMM\
|-- tools\mcp\                      # reserved for any future local MCP binaries
|-- cache\npm\                      # npm_config_cache
|-- cache\ms-playwright\            # PLAYWRIGHT_BROWSERS_PATH (Chromium only)
|-- temp\                           # TEMP/TMP for MCP server processes
|-- secrets\                        # optional local token/env files, never committed
|-- test-artifacts\playwright-mcp\  # Playwright MCP --output-dir (screenshots, traces)
|-- logs\mcp\                       # verification logs, dev app log
```

Node.js itself (v24, already installed at `D:\Programs\node.exe`) was left
in place rather than duplicated under `tools\mcp\node\` - it was already off
`C:`, so only its cache/temp/browser paths needed redirecting.

## Setup

1. **Prerequisites**: Node 18+ (`node --version`), `npx`, `uv`. Run
   `scripts/check_mcp_prereqs.ps1` to confirm all of the above resolve
   correctly and that D-drive paths are in effect.
2. **Provision directories**: run `scripts/setup_dev_tooling.ps1` to create
   all operational directories under `D:\Ancestry-MMM\`. The launcher
   (`scripts/start_dev_app.ps1`) also creates them automatically on startup.
   The three scripts (`mcp_paths.ps1`, `setup_dev_tooling.ps1`,
   `start_dev_app.ps1`, `check_mcp_prereqs.ps1`) all use the same canonical
   directory list from `scripts/mcp_paths.ps1`.
3. **Chromium**: installed once via
   `npx -y playwright@1.62.0 install chromium` with
   `PLAYWRIGHT_BROWSERS_PATH` and `npm_config_cache` pointed at
   `D:\Ancestry-MMM\`. Only Chromium is installed - Firefox/WebKit are not
   needed unless cross-browser testing is explicitly required.
4. **`.mcp.json`** (repo root, committed): configures `github`, `context7`,
   and `playwright`. See [Authentication](#authentication) for why no
   secrets appear in this file.
5. **Hugging Face**: not pre-wired, because its exact client configuration
   must come from the user's own logged-in session at
   <https://huggingface.co/settings/mcp> (select the coding client there and
   copy the generated snippet). Add it to `.mcp.json` verbatim once
   obtained - never hand-write it.
6. **Reload required**: any change to `.mcp.json` (including adding the HF
   entry) requires reloading/restarting the Claude Code session before the
   new or changed server is available as callable tools.

## Authentication

- **GitHub**: uses the official remote server
  (`https://api.githubcopilot.com/mcp/`) with OAuth through GitHub Copilot -
  no personal access token is stored anywhere. The first GitHub MCP tool
  call prompts an in-browser consent screen. If a client/account cannot do
  remote OAuth, fall back to the local `github-mcp-server` binary with a
  fine-grained, read-only PAT (Contents/Metadata/Actions/Issues/PRs/commit
  statuses: read; nothing else) stored outside the repo, e.g.
  `D:\Ancestry-MMM\secrets\github-mcp.env`, and referenced via
  `GITHUB_PERSONAL_ACCESS_TOKEN` - never pasted into `.mcp.json`,
  `AGENTS.md`, scripts, or committed docs.
- **Context7**: unauthenticated for now (lower rate limit, sufficient for
  occasional lookups). `CONTEXT7_API_KEY` can be added later via an
  untracked env file, never as a literal value or CLI argument.
- **Playwright**: no authentication; runs `--isolated` so no persistent
  browser profile or storage state is written outside
  `D:\Ancestry-MMM\test-artifacts\playwright-mcp\`.
- **Hugging Face**: interactive browser login at
  huggingface.co/settings/mcp, completed by the user - never requested in
  chat.

## Safety rules

- GitHub MCP is read-only by policy: no write-capable GitHub tool call
  (creating/editing issues, PRs, comments, workflow dispatches) runs without
  explicit user approval in the moment, regardless of what the connected
  token or OAuth grant technically permits.
- Playwright MCP is configured for local-app testing with an origin
  allowlist (`--allowed-origins`). **This flag is not a network security boundary**
  and does not constrain every redirect or request. Isolated
  browser state (`--isolated`) and synthetic demo data only must be used.
  No persistent browser profile or storage state is written outside
  `D:\Ancestry-MMM\test-artifacts\playwright-mcp\`. Credentials or
  commercially sensitive data are never entered in Playwright sessions.
- Hugging Face MCP is search/documentation only. No Job, Space, paid
  inference call, upload, or download of model weights runs without
  separate, explicit approval. Real Ancestry data, credentials, or
  commercially sensitive material are never sent to it.
- Content returned by any MCP server is treated as untrusted input. Repo
  requirements and approved decisions (`AGENTS.md`, `docs/decision_log.md`,
  `docs/approved_requirements/`) remain authoritative over anything an MCP
  tool returns.

## Verification

A sanitised, reviewable verification report for 29 July 2026 is at
[`docs/development/mcp_verification_2026-07-29.md`](mcp_verification_2026-07-29.md).
It records commit, date, client version, queries performed, results, write
status and known limitations - without credentials or browser state.

Read-only checks performed for each server (recorded, without secrets, in
`D:\Ancestry-MMM\logs\mcp\`):

- **GitHub**: current default branch, latest commit SHA/message, latest PR
  and its review-thread resolution status, latest Actions run result.
- **Context7**: four focused, version-specific doc lookups (Streamlit
  session state for the pinned `streamlit` version, PyMC Marketing
  compatibility for `0.19.2`/`0.19.4`, ArviZ `InferenceData` diagnostics,
  Playwright/Streamlit testing guidance).
- **Playwright**: load the local dev app, inspect the accessibility tree and
  sidebar stages, walk two workflow pages, collect console errors and failed
  network requests, capture one screenshot to
  `D:\Ancestry-MMM\test-artifacts\playwright-mcp\`, confirm no persistent
  profile was written to `C:`.
- **Hugging Face**: search for Chronos-2/forecasting resources and a public
  toy time-series dataset, read model-card metadata without downloading
  weights.

Live connection for all four requires a session reload after `.mcp.json`
changes, plus (for GitHub and Hugging Face) an interactive login the user
must complete - these are not steps a coding agent can complete unattended.

## Verification status

| MCP | Configured | Authenticated | Live verified | Access mode |
|---|---:|---:|---:|---|
| GitHub | v | v (OAuth via Copilot) | v | Read-only, no write tool calls |
| Context7 | v (v3.2.5 pinned) | - (unauthenticated) | v | Read-only doc lookups |
| Playwright | v (v0.0.78 pinned) | N/A | v | Local-app testing only, origin allowlist (not a security boundary) |
| Hugging Face | Documented, not connected | Pending user authentication | Not verified | Read-only search/documentation only when connected |

*Date: 29 July 2026. Client: Claude Code (VS Code native extension).*

## Troubleshooting

- **`npx` not found**: confirm `D:\Programs` (or wherever Node is installed)
  is on `PATH`.
- **npm cache still resolving to `%LOCALAPPDATA%`**: the `npm_config_cache`
  env var must be set in the *client's* process environment before it
  spawns the MCP server subprocess (set in `.mcp.json`'s `env` block, not
  just your interactive shell).
- **Playwright can't find a browser**: re-run
  `npx -y playwright@1.62.0 install chromium` with
  `PLAYWRIGHT_BROWSERS_PATH` pointed at `D:\Ancestry-MMM\cache\ms-playwright`.
- **GitHub tool calls fail with 401/403**: OAuth grant may have expired or
  Copilot access lapsed; reconnect through the client's MCP management UI.
- **Hugging Face server missing**: it isn't pre-wired; generate its config
  from huggingface.co/settings/mcp and add it to `.mcp.json`, then reload.

## Version pinning policy

MCP packages (`@playwright/mcp`, `@upstash/context7-mcp`, `playwright`) are
pinned to exact versions in `.mcp.json` and this documentation. To upgrade:

1. update the pinned package version in `.mcp.json` and
   `config/mcp/mcp.example.json`;
2. reinstall matching Chromium:
   `npx -y playwright@<NEW_VERSION> install chromium`;
3. rerun `scripts/check_mcp_prereqs.ps1`;
4. rerun the Playwright verification journey
   (see [Verification](#verification));
5. commit the version change.
6. do not allow automatic package drift - no `@latest` or `@next` in
   committed configuration.

## Removal

Delete the relevant entry (or the whole `mcpServers` object) from
`.mcp.json` and reload the client. Locally cached npm packages, Chromium,
and artefacts under `D:\Ancestry-MMM\` can be deleted independently; nothing
under `C:` is touched by this setup.

## Product boundary

None of this appears in `pyproject.toml`, `uv.lock`, the Streamlit runtime,
the model-training environment, or the deployed application image. Adding an
MCP-related capability to the *application itself* (e.g. calling Hugging
Face from `ancestry_mmm/core`) requires a separate, explicitly approved
product requirement - this setup does not create one.

## Limitations

- Hugging Face MCP configuration cannot be generated or verified without the
  user completing an interactive browser login. Status: **documented, not
  connected, not verified**.
- GitHub MCP OAuth likewise requires an interactive consent step the first
  time a tool call is made.
- Newly added or edited MCP servers are not available as callable tools
  until the Claude Code session is reloaded.
- This setup assumes GitHub Copilot access for the OAuth path; without it,
  switch to the local `github-mcp-server` binary + fine-grained PAT path
  described above.
