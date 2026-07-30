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
production dependency set (`pyproject.toml` / `uv.lock` are untouched):

```powershell
uv tool install "graphifyy[mcp]"
uv tool update-shell   # persists ~/.local/bin (graphify, graphify-mcp) on PATH
```

| Field | Value |
|---|---|
| Package (PyPI) | `graphifyy` (double-y - not `graphify`) |
| Installed version | `0.9.30` |
| CLI command | `graphify` |
| MCP server command | `graphify-mcp` (equivalent to `python -m graphify.serve`) |
| Install method | `uv tool install` (isolated; not in `pyproject.toml`/`uv.lock`) |
| Executable location | `%USERPROFILE%\.local\bin\graphify(.exe)` / `graphify-mcp(.exe)` |
| Supported Python | >=3.10 (repo pins 3.11-3.12; no conflict, since it's an isolated tool env, not the project venv) |

A new terminal or VS Code window is required after `uv tool update-shell`
for `graphify`/`graphify-mcp` to resolve without a full path.

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
call, no API key, no LLM):

```bash
graphify extract . --code-only
graphify cluster-only . --no-label
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

```bash
graphify update .
graphify cluster-only . --no-label
```

`update` re-extracts only changed/added/deleted files (no LLM, no API key)
and merges into the existing graph; `cluster-only` regenerates the report
and visualisation. Both are cheap - run after any meaningful restructuring
(new modules, moved files, changed call graph), not after every edit.

## MCP server

```bash
graphify-mcp graphify-out/graph.json          # stdio (default) - what .mcp.json uses
graphify-mcp graphify-out/graph.json --transport http --port 8765   # only if a client needs HTTP
```

- **Transport**: stdio is used here. It needs no persistently running
  process - the client (Claude Code) spawns `graphify-mcp` itself per
  session and tears it down when the session ends, matching how the
  existing `context7`/`playwright` entries in `.mcp.json` work. There is no
  standing background service to start, stop, or forget about.
- If a client that only supports Streamable HTTP is added later, start it
  manually with `--transport http`; it binds to `127.0.0.1` by default
  (`--host` to change - do not bind `0.0.0.0` without a specific reason) and
  needs an explicit stop (`Ctrl+C` or killing the process) since nothing
  manages it automatically.

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
  "command": "graphify-mcp",
  "args": ["graphify-out/graph.json"]
}
```

No absolute path: `graphify-mcp` resolves via `PATH` (see
[Installation](#installation)) and the graph path is repo-relative, so this
entry is portable across machines that have Graphify installed the same
way - unlike a hard-coded `C:\Users\<name>\...` path, which would break for
any other developer and violates the "no machine-specific paths" rule this
repo already follows for its other MCP entries.

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
command = "graphify-mcp"
args = ["graphify-out/graph.json"]
cwd = "D:\\App Projects\\MMM-Guide"
```

`cwd` is required here (unlike `.mcp.json`) because Codex's config isn't
scoped to one project - without it, `graphify-out/graph.json` wouldn't
resolve relative to this repo. Restart the Codex extension/session after
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
   session; the model is just who gets to call the tools it exposes.

If `graphify-mcp` isn't found after a reload, PATH wasn't picked up yet -
close and reopen VS Code fully (not just reload window), or run `uv tool
update-shell` again and start a fresh terminal to confirm it resolves there
first.

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

- **`graphify`/`graphify-mcp` not found**: PATH wasn't updated in the
  current shell/VS Code session - run `uv tool update-shell`, then open a
  new terminal or fully restart VS Code.
- **MCP server not listed after adding to `.mcp.json`**: Claude Code only
  picks up `.mcp.json` changes on reload/restart, same as the other three
  servers (see `mcp_development_tooling.md`).
- **`graphify cluster-only` says "no graph found"**: run `graphify extract .
  --code-only` first - `cluster-only` operates on an existing `graph.json`,
  it doesn't build one.
- **Graph looks stale after a refactor**: run the refresh commands in
  [Refreshing after structural changes](#refreshing-after-structural-changes).
  `GRAPH_REPORT.md`'s own "Graph Freshness" section records the commit it
  was built from - compare against `git rev-parse HEAD`.
- **Report/graph.json unexpectedly missing a file**: check `.graphifyignore`
  and `.gitignore` first; both are respected by default.

## Uninstall / rollback

```powershell
graphify uninstall --purge   # removes any registered client integrations and graphify-out/
uv tool uninstall graphifyy  # removes the isolated tool install
```

To fully remove the repo-side integration: delete the `graphify-project`
entry from `.mcp.json`, delete `.graphifyignore`, remove the "Graphify
repository map" section and the Graphify bullet/sentence from `AGENTS.md`,
delete this file, and remove the `graphify-out/` line from `.gitignore`.
Nothing under `graphify-out/` is committed, so there is nothing else to
clean up in git history.

## Product boundary

None of this appears in `pyproject.toml`, `uv.lock`, the Streamlit runtime,
the model-training environment, or the deployed application image. Graphify
is never imported by `ancestry_mmm/`. Adding graph-based capability to the
*application itself* would require a separate, explicitly approved product
requirement - this setup does not create one.
