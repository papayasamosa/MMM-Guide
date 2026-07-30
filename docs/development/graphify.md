# Graphify: repository knowledge graph

Graphify builds a local, AST-based knowledge graph of this repository and
exposes it to MCP-capable coding clients, so any supported model switched to
inside the same VS Code client can navigate architecture, dependencies, and
call paths without re-scanning the whole tree on every request.

**It is not part of MMM-Guide.** Like the other MCP tooling documented in
[`mcp_development_tooling.md`](mcp_development_tooling.md), it is a
development-time tool only: not a Python dependency, never imported by
`ancestry_mmm/`, not deployed with the app. See
[Product boundary](#product-boundary) below.

## Purpose

- Give a coding agent a structural map of the repo (files, functions,
  classes, call/import edges, docstrings) that is much cheaper to query than
  re-reading or re-grepping the whole tree.
- Let a developer switch between coding models/extensions inside the same
  VS Code client (e.g. Claude Code) without losing that context - the MCP
  server is owned by the *client*, not the model; whichever model is active
  gets the same tool access.
- Provide a static fallback (`graphify-out/GRAPH_REPORT.md`) readable even
  when no MCP client is connected.

## Installation

Installed as an isolated developer tool via `uv tool install`, matching the
convention this repo already uses for keeping dev tooling out of the
production dependency set (`pyproject.toml` / `uv.lock` are untouched) -
and, per this repo's mandatory D-drive storage rule, entirely under
`D:\Ancestry-MMM\` rather than `%USERPROFILE%\.local\bin` or any other
`C:`-drive or default user-profile location:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_graphify.ps1
```

This script (not a bare `uv tool install`) is the supported install path. It:

1. sets `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_CACHE_DIR`, `TEMP`, and `TMP`
   to `D:\Ancestry-MMM\...` paths before invoking `uv`;
2. runs the pinned, forced install:
   ```powershell
   uv tool install --force "graphifyy[mcp]==0.9.30"
   ```
3. does **not** run `uv tool update-shell` - Graphify is never added to the
   ambient user `PATH`. `scripts\run_graphify_mcp.ps1` (see
   [MCP server](#mcp-server)) resolves the exact D-drive executable
   directly instead, so nothing depends on shell PATH state;
4. verifies the resolved executables exist and are on `D:` before reporting
   success.

Run `scripts\check_graphify_prereqs.ps1` at any time afterwards to
re-verify the install (read-only, makes no changes) - it fails clearly if
`MMM_DEV_ROOT` resolves off `D:`, matching the same drive check enforced by
the launcher.

| Field | Value |
|---|---|
| Package (PyPI) | `graphifyy` (double-y - not `graphify`) |
| Installed version | `0.9.30` (pinned in `scripts\graphify_paths.ps1`) |
| CLI command | `graphify` |
| MCP server command | `graphify-mcp` (equivalent to `python -m graphify.serve`) |
| Install method | `scripts\setup_graphify.ps1` -> `uv tool install --force` (isolated; not in `pyproject.toml`/`uv.lock`) |
| Executable location | `D:\Ancestry-MMM\tools\uv\bin\graphify(.exe)` / `graphify-mcp(.exe)` (override the root via `MMM_DEV_ROOT`) |
| Supported Python | >=3.10 (repo pins 3.11-3.12; no conflict, since it's an isolated tool env, not the project venv) |

No shell restart or PATH change is required or used: `graphify`/`graphify-mcp`
are invoked by their full `D:\Ancestry-MMM\...` path, by the launcher script
or manually, never resolved via PATH.

### Discrepancy from the public docs

The Graphify website (`graphify.com/docs`) and README show usage examples as
`/graphify .`, `/graphify ./raw --update`, `/graphify ./raw --mcp`. Those are
**chat-slash-command syntax** for clients where `graphify install` has
registered a skill (Claude Code, Cursor, etc.), not literal shell commands.
The installed CLI's own `--help` is the source of truth used throughout this
document: there is no bare `graphify build` command; the real build path is
`graphify extract` (initial/full) and `graphify update` (incremental), and
the graph must be clustered separately with `graphify cluster-only` to get
`GRAPH_REPORT.md` and `graph.html`. Where the docs and the installed CLI
disagreed, this document follows the installed CLI.

## Building the graph

Two-step build, run from the repo root, both steps local-only (no network
call, no API key, no LLM). Both go through
[`scripts\run_graphify_cli.ps1`](#the-cli-wrapper) - never a bare `graphify`
command - so the build always resolves the exact D-drive executable this
repo installed, never an ambient `graphify` on `PATH` (which could be an
unrelated install, a different pinned version, or belong to another
project entirely):

```powershell
scripts\run_graphify_cli.ps1 extract . --code-only
scripts\run_graphify_cli.ps1 cluster-only . --no-label
```

- `--code-only`: indexes source code via local tree-sitter AST parsing only;
  explicitly skips doc/PDF/image/office extraction and never calls an LLM
  backend. This is what makes the build satisfy "nothing leaves the
  machine" - it is not merely the default.
- `--no-label`: runs structural (Louvain-style) clustering, which is a pure
  graph algorithm, but skips the LLM call that would otherwise generate
  human-readable community names. Communities are left as `Community N`
  placeholders. See [Community labelling](#community-labelling-opt-in) to
  opt into named communities later, and what that trades away.
- `.graphifyignore` (committed, gitignore-style syntax) excludes confidential
  and low-value paths on top of whatever `.gitignore` already excludes (see
  [Exclusions](#exclusions)).

Produces `graphify-out/`:

| File | Purpose |
|---|---|
| `graph.json` | Machine-readable graph, read by the MCP server and CLI queries |
| `GRAPH_REPORT.md` | Human-readable architecture/community summary |
| `graph.html` | Interactive browser visualisation |
| `manifest.json`, `.graphify_analysis.json`, `cache/` | Internal build state (incremental cache, analysis) |

### Refreshing after structural changes

```powershell
scripts\run_graphify_cli.ps1 update .
scripts\run_graphify_cli.ps1 cluster-only . --no-label
```

`update` re-extracts only changed/added/deleted files (no LLM, no API key)
and merges into the existing graph; `cluster-only` regenerates the report
and visualisation. Both are cheap - run after any meaningful restructuring
(new modules, moved files, changed call graph), not after every edit.

### The CLI wrapper

`scripts\run_graphify_cli.ps1` (PR 88C) is the required entry point for
every `graphify` build/refresh subcommand - `extract`, `update`,
`cluster-only`, or any other CLI subcommand. It never invokes a bare
`graphify` command (that would depend on an ambient `PATH` entry, which
this repo's D-drive rule forbids relying on, and could silently pick up an
unrelated install or a different pinned version). It:

1. resolves the exact D-drive tool-bin directory the same way
   [`scripts\run_graphify_mcp.ps1`](#mcp-server) does (`UV_TOOL_BIN_DIR` if
   set, else the default under `MMM_DEV_ROOT`);
2. rejects the resolved directory if it does not resolve **inside** the
   configured root - exact containment (equal to the root, or nested under
   it), not a string-prefix match, so a similarly-named sibling directory
   (e.g. `D:\Ancestry-MMM-Evil` against a configured root of
   `D:\Ancestry-MMM`) cannot be selected;
3. fails clearly (non-zero exit, nothing launched) if the resolved
   `graphify.exe` is missing;
4. passes every argument through unchanged to the resolved executable and
   propagates its exit code unchanged.

```powershell
scripts\run_graphify_cli.ps1 extract . --code-only
scripts\run_graphify_cli.ps1 cluster-only . --no-label
scripts\run_graphify_cli.ps1 update .
```

## MCP server

`.mcp.json` never invokes `graphify-mcp` directly (that would depend on an
ambient `PATH` entry, which this repo's D-drive rule forbids relying on).
It calls the repository launcher instead, which resolves the exact
`D:\Ancestry-MMM\tools\uv\bin\graphify-mcp.exe` and fails clearly rather
than falling back to PATH or partially starting:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_graphify_mcp.ps1
```

Equivalent manual invocation (same executable, resolved the same way the
launcher does):

```bash
D:\Ancestry-MMM\tools\uv\bin\graphify-mcp.exe graphify-out/graph.json   # stdio (default) - what the launcher/.mcp.json use
D:\Ancestry-MMM\tools\uv\bin\graphify-mcp.exe graphify-out/graph.json --transport http --port 8765   # only if a client needs HTTP
```

The launcher (`scripts\run_graphify_mcp.ps1`) fails with a clear, non-zero
exit before starting anything when:

- `MMM_DEV_ROOT` (or the `D:\Ancestry-MMM` default) does not resolve to a
  `D:`-drive path;
- the resolved tool-bin directory (`UV_TOOL_BIN_DIR`, or the default) falls
  outside that root - e.g. a stray ambient override pointing at
  `%USERPROFILE%\.local\bin` or an unrelated machine-wide tool directory;
- `graphify-mcp.exe` is not present at the resolved location (install not
  yet run, or run against a different root);
- `graphify-out/graph.json` is absent (nothing to serve - run
  [Building the graph](#building-the-graph) first).

- **Transport**: stdio is used here. It needs no persistently running
  process - the client (Claude Code) spawns the launcher (which spawns
  `graphify-mcp`) itself per session and tears it down when the session
  ends, matching how the existing `context7`/`playwright` entries in
  `.mcp.json` work. There is no standing background service to start,
  stop, or forget about.
- If a client that only supports Streamable HTTP is added later, start it
  manually with `--transport http` against the resolved executable path
  above; it binds to `127.0.0.1` by default (`--host` to change - do not
  bind `0.0.0.0` without a specific reason) and needs an explicit stop
  (`Ctrl+C` or killing the process) since nothing manages it automatically.

## Configured VS Code clients

Detected coding-agent-relevant extensions on this machine:
`anthropic.claude-code`, `openai.chatgpt` (Codex), `vizards.deepseek-v4-for-copilot`.
No Continue, Cline, Roo Code, Kilo Code, Cursor, or Gemini CLI extension is
installed, and GitHub Copilot Chat itself (`github.copilot-chat`) is **not**
installed (only `github.vscode-github-actions`, which is unrelated CI
tooling).

| Client | MCP support here | Configuration |
|---|---|---|
| **Claude Code** (VS Code extension) | Yes, project-scoped | `graphify-project` entry added to `.mcp.json` (committed, repo-root, portable - see below) |
| **Codex** (`openai.chatgpt` extension) | Yes, but user-global only | Not auto-configured (by your choice - see [Codex setup](#codex-manual-setup)); config lives in `~/.codex/config.toml`, outside the repo and shared across all your Codex projects |
| **DeepSeek** (`vizards.deepseek-v4-for-copilot`) | No functioning chat surface currently | This extension only registers DeepSeek as a model in **GitHub Copilot Chat's** model picker (BYOK) - it has no chat UI or MCP layer of its own. Since Copilot Chat itself isn't installed, DeepSeek currently has no working entry point in this VS Code install. If you install GitHub Copilot Chat later, DeepSeek becomes selectable as a model inside it, and it would then use Copilot Chat's own MCP configuration (`graphify install --platform vscode`, or hand-edit `.vscode/mcp.json`) - the MCP connection belongs to Copilot Chat as the client, not to DeepSeek as the model |

### `.mcp.json` entry (Claude Code)

```json
"graphify-project": {
  "command": "powershell",
  "args": [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "scripts/run_graphify_mcp.ps1"
  ]
}
```

No absolute path and no ambient `PATH` dependency: the launcher script is
repo-relative (portable across machines - unlike a hard-coded
`C:\Users\<name>\...` path, which would break for any other developer and
violates the "no machine-specific paths" rule this repo already follows for
its other MCP entries) and resolves the exact D-drive executable itself
(see [MCP server](#mcp-server)), rather than depending on `graphify-mcp`
being on `PATH`.

**Reload required**: like the other three servers, a change to `.mcp.json`
only takes effect after reloading/restarting the Claude Code session.

### Codex manual setup

Codex's MCP config is global (`~/.codex/config.toml`), not project-scoped,
so it cannot be committed to this repo and was **not** edited automatically
(you chose to review it yourself). To wire it up, add this under your
existing `[mcp_servers.*]` entries (keep `node_repl` and anything else
already there):

```toml
[mcp_servers.graphify-project]
command = "powershell"
args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/run_graphify_mcp.ps1"]
cwd = "D:\\Ancestry-MMM\\repos\\MMM-Guide"
```

`cwd` is required here (unlike `.mcp.json`) because Codex's config isn't
scoped to one project - without it, `scripts/run_graphify_mcp.ps1` and
`graphify-out/graph.json` wouldn't resolve relative to this repo. Use the
repository's canonical D-drive checkout path
(`D:\Ancestry-MMM\repos\MMM-Guide`), not a machine-specific location such
as the original `D:\App Projects\MMM-Guide` this repo was previously
checked out to - adjust to your actual checkout path if it differs.
Restart the Codex extension/session after
editing.

## Verifying MCP tool availability

1. Reload the Claude Code VS Code window (or restart the session) after any
   `.mcp.json` change.
2. Ask the assistant to list available MCP tools, or check whatever
   tool/server picker the client exposes - a `graphify-project` (or
   `graphify-mcp`) entry alongside `github`, `context7`, `playwright` (and
   `huggingface` once connected) confirms discovery.
3. Run a real query through the tools, e.g. "using Graphify, find the
   Streamlit entry point and its immediate dependencies" or "trace how
   `ancestry_mmm/pages/08_Scenario_Planner.py` reaches
   `ancestry_mmm/core/optimization.py`".
4. Switching models inside the same MCP-capable client (e.g. changing which
   model Claude Code or Copilot Chat is using) does **not** require
   reconnecting MCP or rebuilding the graph - the extension owns the MCP
   session; the model is just who gets to call the tools it exposes. A
   model can only call `graphify-project` tools when its *coding client*
   both supports MCP and has this server configured and connected - MCP
   access is a property of the client, not of any specific model.

If the `graphify-project` tools aren't listed after a reload, run
`scripts\check_graphify_prereqs.ps1` first to confirm the D-drive install
resolves correctly, then close and reopen VS Code fully (not just reload
window). This is unrelated to `PATH`: the launcher never depends on
`graphify-mcp` being on `PATH`, so a PATH change alone will not fix it.

## Exclusions

`.graphifyignore` (committed, gitignore-style patterns), layered on top of
`.gitignore` (which Graphify already respects by default unless
`--no-gitignore` is passed - not used here):

| Excluded | Why |
|---|---|
| `archive/` | Deprecated code, not part of the current implementation |
| `MMM_Complete_Guide_v7.docx`, `conjura_mmm_data.csv`, `conjura_mmm_data_dictionary.xlsx` | Confidential vendor/Ancestry material and raw client data - tracked in git for other reasons, but never fed into the graph |
| `mmm_complete_example.ipynb`, `mmm_multiplicative_example.ipynb` | Notebook cell outputs derived from the confidential data above |
| `docs/screenshots/`, `docs/*.png` | Large binaries, no architectural value |
| `.env*`, `secrets/`, `credentials/`, `data/raw\|private\|confidential/`, `model_artifacts/`, `checkpoints/` | Standard defensive exclusions - none currently exist in this repo, kept for when they do |
| `graphify-out/` | The graph must never graph itself |

`--code-only` (used for every build) is a second, independent layer: even
without the entries above, it skips all non-code files (docs, PDFs, images,
office formats) and never invokes an LLM backend, so nothing is chunked and
sent anywhere regardless of `.graphifyignore` content.

Verified after the initial build: `graphify-out/graph.json` and
`GRAPH_REPORT.md` contain zero references to `conjura_mmm_data.csv`,
`MMM_Complete_Guide_v7.docx`, or any `archive/` path.

## What's committed vs rebuilt locally

| Committed | Rebuilt locally (gitignored) |
|---|---|
| `.graphifyignore` | `graphify-out/` (`graph.json`, `graph.html`, `GRAPH_REPORT.md`, `manifest.json`, `cache/`, `.graphify_analysis.json`) |
| `.mcp.json` (`graphify-project` entry) | |
| `AGENTS.md` (Graphify repository map section) | |
| `docs/development/graphify.md` (this file) | |

**Nothing under `graphify-out/` is committed.** Reasoning:

- `graph.json` (~7 MB) and `graph.html` (~5 MB) are large generated
  artefacts with no diff-review value.
- `GRAPH_REPORT.md` is small enough to consider, but community numbering
  (`Community 0`, `Community 1`, ...) is not stable across rebuilds, so
  every refresh would produce a noisy, low-signal diff.
- Rebuilding is two cheap, local, no-API-key commands (see
  [Building the graph](#building-the-graph)) - there is no availability
  benefit to committing it that outweighs the diff noise.
- The MCP server reads `graph.json` directly, so any MCP-connected client
  never needs the committed copy anyway; only a developer without MCP
  connected loses the static `GRAPH_REPORT.md` fallback until they run the
  build locally.

Graphify itself is not added to `pyproject.toml` or `uv.lock` - it is a
developer utility, not a runtime or even a versioned-dev dependency of the
project, matching the `uv tool install` isolation the
[Installation](#installation) section describes.

## Community labelling (opt-in)

By default, community names in `GRAPH_REPORT.md` are `Community N`
placeholders (`--no-label`). Running `graphify label .` instead would send
node summaries to a configured LLM backend (`--backend
gemini|kimi|claude|openai|deepseek|ollama`) to generate readable names -
this is the one Graphify operation that leaves the machine unless the
backend is `ollama` (local). It was **not** enabled here by default, per
this repo's "never send source code or confidential material to an external
service without a separate approved requirement" rule. If you want it,
review which backend/model you're sending code summaries to first.

## Troubleshooting

- **`graphify`/`graphify-mcp` not found**: run
  `scripts\check_graphify_prereqs.ps1` to see exactly which D-drive path
  and executable are missing, then (re)run `scripts\setup_graphify.ps1`.
  There is no PATH step to retry - neither script relies on `PATH`, so
  restarting a terminal alone will not fix a missing install.
- **Launcher fails with "resolves outside the configured D-drive root"**:
  an ambient environment variable (`UV_TOOL_BIN_DIR`, or `MMM_DEV_ROOT`
  itself) is pointing somewhere other than `D:\Ancestry-MMM\...` - often a
  machine-wide convention from another project. Unset it or correct it
  before launching; the launcher deliberately refuses to guess.
- **MCP server not listed after adding to `.mcp.json`**: Claude Code only
  picks up `.mcp.json` changes on reload/restart, same as the other three
  servers (see `mcp_development_tooling.md`).
- **`cluster-only` says "no graph found"**: run
  `scripts\run_graphify_cli.ps1 extract . --code-only` first - `cluster-only`
  operates on an existing `graph.json`, it doesn't build one.
- **Graph looks stale after a refactor**: run the refresh commands in
  [Refreshing after structural changes](#refreshing-after-structural-changes).
  `GRAPH_REPORT.md`'s own "Graph Freshness" section records the commit it
  was built from - compare against `git rev-parse HEAD`.
- **Report/graph.json unexpectedly missing a file**: check `.graphifyignore`
  and `.gitignore` first; both are respected by default.

## Uninstall / rollback

```powershell
# Same D-drive env vars setup_graphify.ps1 uses, so uv targets the
# isolated D-drive install rather than any default location:
$env:MMM_DEV_ROOT = "D:\Ancestry-MMM"          # or your configured root
$env:UV_TOOL_DIR = "$env:MMM_DEV_ROOT\tools\uv\tools"
$env:UV_TOOL_BIN_DIR = "$env:MMM_DEV_ROOT\tools\uv\bin"
D:\Ancestry-MMM\tools\uv\bin\graphify.exe uninstall --purge   # removes any registered client integrations and graphify-out/
uv tool uninstall graphifyy                                   # removes the isolated tool install
```

To fully remove the repo-side integration: delete the `graphify-project`
entry from `.mcp.json`, delete `scripts\graphify_paths.ps1`,
`scripts\setup_graphify.ps1`, `scripts\check_graphify_prereqs.ps1`, and
`scripts\run_graphify_mcp.ps1`, delete `.graphifyignore`, remove the
"Graphify repository map" section and the Graphify bullet/sentence from
`AGENTS.md`, delete this file, and remove the `graphify-out/` line from
`.gitignore`. Nothing under `graphify-out/` is committed, so there is
nothing else to clean up in git history.

## Product boundary

None of this appears in `pyproject.toml`, `uv.lock`, the Streamlit runtime,
the model-training environment, or the deployed application image. Graphify
is never imported by `ancestry_mmm/`. Adding graph-based capability to the
*application itself* would require a separate, explicitly approved product
requirement - this setup does not create one.
