# MCP live-verification report — 29 July 2026

## Context

| Field | Value |
|---|---|
| Repository commit | `b8af933ffe850ea39bad689c6e0daccadae79dc6` (PR 69A) |
| Date | 29 July 2026 |
| Coding client | Claude Code (VS Code native extension) |
| MCP package versions | `@upstash/context7-mcp@3.2.5`, `@playwright/mcp@0.0.78` |
| App host | `http://127.0.0.1:8501` |

## GitHub MCP (read-only)

| Action | Result |
|---|---|
| List branches | 10 branches returned |
| Read PR #67 | Merged, 289 additions, 7 files, 1 commit |
| Read PR #68 | Merged, 501 additions, 8 files, 1 commit |
| Read PR #67 comments | 0 inline comments |
| Read PR #68 review comments | 3 threads (all unresolved before merge) |
| Read PR #68 reviews | 1 automated review (Codex) |
| Read current head (`main`) | `41e8a8fe90940b5886189db391936078f4cb853b` (pre-69A) |
| **Write calls made** | **None** |

## Context7 MCP (read-only doc queries)

| Query | Library ID | Result |
|---|---|---|
| Resolve Playwright MCP configuration + browser matching | `/microsoft/playwright-mcp` | Confirmed `--allowed-origins` advisory, install-browser command, version pinning guidance |
| Resolve Context7 MCP package + version | `/upstash/context7` | Confirmed v3.2.4 package was latest; active config pins v3.2.5. Exact v3.2.5 compatibility not independently verified. |
| Playwright MCP browser installation details | `/microsoft/playwright-mcp` | Confirmed `install-browser chrome-for-testing` command and chromium-1232 |
| **Write calls made** | | **None** |

## Playwright MCP (local app testing)

| Step | Result |
|---|---|
| Launch app | HTTP 200, `http://127.0.0.1:8501` |
| Page title | "Marketing Mix Modelling & Scenario Planner" |
| Navigate: Data Upload | Title "Data Upload - Ancestry FH MMM" — accessible |
| Navigate: Diagnostics | Page loaded successfully |
| Navigate: Scenario Planner | Title "Scenario Planner - Ancestry FH MMM" — accessible |
| Console errors (total) | 2 — benign Streamlit `_stcore/host-config` 404s (sub-page health endpoints) |
| Failed network requests | None beyond the benign 404s above |
| Screenshot captured | `D:\Ancestry-MMM\test-artifacts\playwright-mcp\pr69a-verification.png` |
| Browser state | Isolated (`--isolated`), no persistent profile written to `C:` |
| App process stopped | Port 8501 freed after `taskkill` |
| **Write calls made** | **None** (synthetic demo data only) |

## Hugging Face MCP

| Status | Detail |
|---|---|
| Configured | No — documented in `.mcp.json` as placeholder only |
| Connected | No — requires user authentication at huggingface.co/settings/mcp |
| Live verified | No — pending user completion of the HF settings flow |
| Write calls made | N/A |

## Summary

| MCP | Configured | Authenticated | Live verified | Access mode |
|---|---|---|---|---|
| GitHub | ✓ | ✓ (OAuth via Copilot) | ✓ | Read-only, no write tool calls |
| Context7 | ✓ (v3.2.5 pinned) | — (unauthenticated) | ✓ (connectivity); exact 3.2.5 not independently verified | Read-only doc lookups; version lookup showed v3.2.4 as latest, configured version is 3.2.5 |
| Playwright | ✓ (v0.0.78 pinned) | N/A | ✓ | Local-app testing only, origin allowlist (not a security boundary) |
| Hugging Face | Documented, not connected | Pending user authentication | Not verified | Read-only search/documentation only when connected |

## Known limitations

- Hugging Face MCP cannot be connected without interactive user login.
- GitHub MCP OAuth requires interactive consent on first tool call.
- Playwright `--allowed-origins` is an advisory allowlist, not a network security boundary.
- Verification uses synthetic demo data only — no real Ancestry data was sent to any MCP.
- No credentials, browser storage, or login state were committed to the repository.
