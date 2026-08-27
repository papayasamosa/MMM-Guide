# Media Mix Lab UI/UX Coding Handoff

## Repository state

Repository: `papayasamosa/Media-Mix-Lab`

Remote `main` at the start of this review: `7b671af43caf13e1159fbec203baa1892f362f93` (merged PR #327, governed FX authority reconciliation).

The corresponding post-merge `main` Tests workflow completed successfully. No pull requests were open when this review started.

Always resolve current remote `main` again before starting the next package. Do not treat this SHA as a permanent live pointer.

## Authority

Read, in order, before editing:

1. root `AGENTS.md`;
2. the most specific nested `AGENTS.md` for changed files, especially `ancestry_mmm/pages/AGENTS.md` for Streamlit pages;
3. `docs/specification_authority.md`;
4. `docs/approved_requirements/README.md` and `docs/approved_requirements/index.json`;
5. relevant approved `REQ-*` records;
6. relevant decision packages and `docs/decision_log.md`;
7. versioned schemas, migrations and tests;
8. existing implementation where it does not conflict with the above.

The local checkout contains the current PRD suite for traceability. PRD prose is not direct implementation authority. Do not implement a PRD statement unless a corresponding approved repository `REQ-*` or approved decision record authorises it.

If an unreconciled PRD provision is unambiguous and already approved, reconcile it into repository authority before implementation. If it requires a statistical, causal, modelling, data-treatment, business, finance, governance, approval-policy or material product decision, create a decision package and stop that workstream. Do not guess.

UI-only changes to wording, hierarchy, layout, discoverability, interaction, navigation, accessibility and progressive disclosure are allowed when they preserve governed semantics.

## Current UI direction

The application is a Streamlit analytical workbench, not a greenfield UI.

The current design direction is analyst-first:

- plain analytical/business language first;
- technical identity and provenance available through progressive disclosure;
- one obvious primary action where possible;
- canonical lifecycle state reused across Home, sidebar and page headers;
- status is never colour-only;
- warnings and blockers are visually and semantically distinct;
- no UI control may invent a model, causal, financial or governance rule;
- pages remain thin orchestration/presentation layers;
- shared UI primitives are preferred to one-off page styling.

Preserve the existing light analytical workbench rather than introducing a visual redesign for novelty.

## Existing shared UI architecture

### Workflow metadata

`ancestry_mmm/utils/workflow.py` is the single source of truth for:

- page keys;
- sidebar labels;
- page titles;
- page purposes;
- workflow order;
- navigation groups;
- page-level guidance;
- current footer next-step text.

Do not duplicate page labels or routes in new UI code.

### Canonical workflow state

`ancestry_mmm/utils/workflow_state.py` separates:

- access status;
- lifecycle status;
- whether a required stage is satisfied;
- whether a workspace is optional.

Home and the shared shell already use this state to derive next recommended work. Presentation state does not grant analytical or governance authority.

### Shared components

Prefer the existing primitives in:

- `ancestry_mmm/components/ui.py`;
- `ancestry_mmm/components/tokens.py`;
- `ancestry_mmm/components/status.py`;
- `ancestry_mmm/components/diagnostics_rail.py`;
- `ancestry_mmm/components/charts.py`.

Important reusable surfaces include:

- `render_sidebar`;
- `render_context_bar`;
- `render_page_header`;
- `render_next_step`;
- `render_empty_state`;
- `render_workspace_note`;
- `render_definition_help`;
- `render_decision_help`;
- `render_technical_details`;
- `SectionCard`;
- `InfoPanel`;
- `WarningPanel`;
- `BlockingPanel`;
- shared semantic status badges.

Do not add a second status vocabulary or a second workflow registry.

## What is already working well

The current app already has a strong analyst-workbench foundation:

- grouped sidebar navigation;
- canonical readiness/lifecycle state;
- a Home dashboard with one next recommended action, project state, attention items and workflow-area progress;
- project context bar;
- consistent page headers;
- status badges with text plus restrained semantic cues;
- shared semantic panels;
- progressive disclosure for definitions, decision help and technical details;
- analyst-facing labels layered over persisted technical IDs;
- humanised model setup controls for carryover, saturation and pooling;
- a Diagnostics summary rail above detailed evidence tabs;
- humanised Scenario Planner output tables;
- actionable empty-state routing;
- AppTest/component/workflow tests for much of the shared shell.

Preserve these patterns.

## Current UX findings

### Critical: none found in the shared shell review

No UI-only defect reviewed here justified bypassing current governance or changing statistical behaviour.

### High: Data Sources mixes ingestion with advanced evidence registries

`ancestry_mmm/pages/01_Data_Upload.py` begins as a coherent source-ingestion workspace, but after source readiness and source details it continues into full Experiment Evidence and Named Events registry administration.

Analyst problem: the first workflow page becomes extremely long and changes task from "load and verify data" to specialist governance administration. This obscures completion and makes the ingestion journey feel much more complex than it needs to be.

Recommended direction:

- keep source loading, source readiness, imported-definition review and source previews as the primary Data Sources journey;
- move advanced registry administration behind clearly labelled progressive disclosure or, if repository authority permits a separate workspace, a dedicated evidence/governance workspace;
- do not change experiment or named-event semantics while reorganising presentation;
- preserve immutable registry behaviour and existing adoption gates.

Relevant authority includes `REQ-DATAIN-001`, `REQ-EXPMODE-001`, `REQ-EVENT-001` and page `AGENTS.md`.

### High: page-footer routing conflicts with Home's required-workflow recommendation

Home's `next_recommended_step_key()` uses canonical lifecycle state and skips optional workspaces. `render_next_step()` instead follows literal `WORKFLOW_STEPS` order.

Examples:

- Model Structure footer recommends optional Causal Graph even though Home may recommend Model Setup;
- Fit Model footer recommends optional Model Comparison even when there is only one fit;
- Prepare Data footer can recommend optional Coverage & Gaps as though it were mandatory for every exploratory continuation.

Analyst problem: two authoritative-looking navigation surfaces can tell the analyst different things.

Recommended direction: distinguish `Next required step` from `Optional workspace`. The primary footer action should use canonical required-workflow progression; optional adjacent workspaces should remain discoverable as secondary links when relevant.

This is presentation routing only. Do not change lifecycle satisfaction or governance gates.

### High: Scenario Planner opening message is stale and potentially misleading

The top of `ancestry_mmm/pages/08_Scenario_Planner.py` currently announces a `Steady-state monthly approximation` and says media carryover is not simulated. Later on the same page the analyst can explicitly choose `Sequential weekly`, which does simulate week-by-week carry-in and terminal carryover for manual evaluation.

Analyst problem: the page appears to state a global limitation that is only true for one method and the optimiser tabs.

Recommended direction:

- replace the global warning with neutral method-selection guidance;
- state method-specific limitations beside the method selector/result;
- make it explicit that manual evaluation can be steady-state monthly or sequential weekly;
- keep constrained/unconstrained optimisation labelled steady-state-only;
- do not imply sequential optimisation exists.

Relevant approved sequential-planning requirements and decision records must be checked before editing.

### High: Scenario Planner exposes too many decisions before the analyst has a clear task sequence

The page contains plan setup, spend editor, counterfactual policy, planning use, manual evaluation method, objective, value/currency resolution, constraints, optimiser modes, uncertainty and saved scenarios in one large workspace.

Analyst problem: technically correct controls compete for attention, and some configuration that applies to optimisation appears alongside manual-plan decisions.

Recommended direction: organise the page around a visible sequence such as `1 Plan scope`, `2 Edit plan`, `3 Choose how to evaluate`, `4 Review result`, `5 Optimise if needed`, `6 Save`. Keep governance controls visible where they materially change semantics, but use progressive disclosure for technical provenance.

Do not move calculation logic into the page while reorganising it.

### High: Diagnostics remains cognitively dense after the strong summary layer

The top-line readiness summary and domain rail are good. The full page still contains many specialised evidence sections, experiment workflows, residual exploration and backtesting controls in one file.

Analyst problem: after answering the main trust question, the page can still feel like a statistical framework rather than a review workflow.

Recommended direction:

- preserve the top-line answer and domain rail;
- make the default path `summary -> primary concern -> readiness blockers -> approval`;
- keep specialist evidence behind domain tabs/expanders;
- avoid adding more page-local analytical orchestration;
- extract rendering/orchestration components where safe rather than expanding `pages/06_Diagnostics.py` further.

### Medium: Model Setup repeats strategy information and mixes read-only and editable language

The page has a read-only `Model strategy · market pooling` section saying markets/pooling are changed on Structure, followed by an editable `Model strategy` radio controlling shared versus market-specific response.

Analyst problem: two adjacent sections named Model strategy imply conflicting ownership.

Recommended direction: rename the read-only section around market scope/pooling exceptions and keep `Response strategy` for the shared-versus-market-specific choice. Do not change hierarchy semantics.

### Medium: technical IDs still leak into some tables and captions

The repository has already added `readable_label`, outcome display labels and scenario table humanisation, but raw channel/input IDs remain visible in several analyst-facing lists and diagnostic tables.

Recommended direction: centralise display-label resolution for activities/channels while retaining raw IDs in technical details and exports. Do not change persisted identifiers.

### Medium: `docs/user_guide.md` is materially behind the current UI

The guide still describes an older step count/order and older labels such as Data Upload, Transform Pipeline, Channel & Media Units, Model Configuration and Project Export & Recovery. It also describes some pages as optional using old numbering.

Recommended direction: regenerate the guide from current analyst-facing workflow language and explicitly separate the required path from optional specialist workspaces. Do not make the guide a second workflow registry.

### Medium: README quick-start language is also stale

README's quick-start still uses older labels/order and does not match the current 15-stage registry.

Recommended direction: derive or manually reconcile docs against `utils/workflow.py`, with tests guarding key analyst-facing names where practical.

### Low: long captions are doing work that should sometimes be structured guidance

Several pages use long captions for consequences, caveats and provenance. Where a sentence answers `what should I do?`, prefer a small shared guidance/status surface. Keep purely technical provenance in technical details.

## Ordered UI/UX work packages

### UI-WP1: Navigation coherence

Goal: one coherent answer to `what should I do next?` across Home and page footers.

Acceptance criteria:

- primary footer navigation follows canonical required-workflow progression;
- optional pages are never presented as mandatory merely because of file order;
- optional workspaces remain discoverable;
- Home, sidebar and footer do not disagree about the next required stage;
- routes and persisted workflow keys remain unchanged;
- workflow/component tests cover required-versus-optional routing;
- no model or governance semantics change.

Likely files:

- `ancestry_mmm/utils/workflow.py`;
- `ancestry_mmm/utils/workflow_state.py` only if a pure presentation helper is needed;
- `ancestry_mmm/components/ui.py`;
- `ancestry_mmm/tests/test_workflow.py`;
- `ancestry_mmm/tests/test_shell_components.py`.

Prefer a dedicated presentation helper rather than changing `next_step_key()` if existing tests or non-footer callers rely on literal registry order.

### UI-WP2: Scenario Planner method and task hierarchy

Goal: make planning read as an analyst decision workflow rather than one large configuration surface.

Acceptance criteria:

- opening copy no longer states steady-state-only behaviour globally;
- manual method choice is explained before method-specific limitations;
- sequential weekly is clearly available only for manual evaluation;
- optimiser tabs remain explicitly steady-state monthly;
- plan setup, editable plan, evaluation, optimisation and save states are visually distinct;
- current governance controls remain explicit and fail closed;
- no scenario mathematics change;
- AppTest/browser regression coverage is added or updated.

### UI-WP3: Data Sources progressive disclosure

Goal: keep ingestion simple while preserving specialist evidence governance.

Acceptance criteria:

- source readiness and upload are the obvious primary task;
- advanced Experiment Evidence and Named Events administration no longer dominate the default page flow;
- all existing registry actions, immutable versioning and governance gates remain available;
- no source-domain semantics change;
- Data Sources tests continue to prove required/optional domains and upload behaviour.

If moving registries to a new page would change workflow contracts materially, stop and reconcile authority first. A presentation-only collapsed `Advanced evidence registries` area is the safer first increment.

### UI-WP4: Model Setup ownership and progressive disclosure

Goal: reduce duplicated strategy language and keep routine setup separate from advanced modelling controls.

Acceptance criteria:

- market scope/pooling-exception summary is clearly read-only;
- shared versus market-specific response choice has one unambiguous label;
- advanced priors remain collapsed by default;
- technical parameter names remain available in help/technical detail;
- model fingerprint inputs and invalidation behaviour are unchanged.

### UI-WP5: Diagnostics review path

Goal: preserve evidence depth while making the approval journey dominant.

Acceptance criteria:

- top-line status, primary concern and blocking readiness issues remain first;
- approval action and reason are easy to find;
- specialist residual/backtest/experiment evidence remains available but secondary;
- no evidence is recomputed in rendering components;
- no approval policy or thresholds change;
- diagnostics artefact and identity fingerprints remain unchanged.

### UI-WP6: Documentation and terminology reconciliation

Goal: make README/user guide match the actual application.

Acceptance criteria:

- current page names and order match `utils/workflow.py`;
- optional workspaces are clearly identified;
- current sequential-manual planning capability is described accurately;
- old page names are removed from current-use instructions;
- docs do not become a second source of runtime workflow truth.

### UI-WP7: Activity/channel display-label consistency

Goal: reduce technical-ID leakage without changing stored identity.

Acceptance criteria:

- reusable activity/channel display-label helper is used on high-traffic analyst tables/selectors;
- raw IDs remain available in technical details;
- persisted IDs, fingerprints and exports are unchanged;
- tests prove display labels do not mutate identifiers.

## Next package to implement

Start with `UI-WP1: Navigation coherence`.

Before editing:

1. refresh `main` and verify CI;
2. confirm no overlapping PR exists;
3. read root `AGENTS.md` and relevant nested instructions;
4. inspect every caller of `next_step_key`, `next_recommended_step_key` and `render_next_step`;
5. confirm this remains presentation-only.

Implementation preference:

- keep literal registry order available for sidebar/order tests;
- introduce a separate required-workflow footer target derived from canonical workflow state or optional-page metadata;
- render optional adjacent workspace links as secondary, never primary, when useful;
- do not silently remove optional workspaces from the sidebar.

Validation minimum:

```powershell
uv run pytest ancestry_mmm/tests/test_workflow.py ancestry_mmm/tests/test_shell_components.py -q
uv run ruff check ancestry_mmm/utils ancestry_mmm/components ancestry_mmm/tests/test_workflow.py ancestry_mmm/tests/test_shell_components.py
uv run ruff format --check ancestry_mmm/utils ancestry_mmm/components ancestry_mmm/tests/test_workflow.py ancestry_mmm/tests/test_shell_components.py
```

Run broader repository-required checks before merge if changed surfaces require them.

For rendered navigation changes, run the app locally and verify Home plus at least Data Sources, Model Structure, Fit Model and Model Diagnostics at a normal desktop width. Use Playwright/AppTest where available and keep synthetic data only.

## PR, CI and merge protocol

For every package:

1. start from updated `main`;
2. create a focused branch;
3. implement one coherent package;
4. run relevant local tests;
5. commit and push;
6. open a PR automatically;
7. include analyst problem, authority, implementation, tests, visual evidence where useful and known limitations;
8. monitor CI;
9. if CI fails, inspect the actual failing job, fix the root cause on the same branch, rerun local validation, push and wait again;
10. do not weaken tests, coverage, type ceilings, governance or security to get green;
11. merge only when CI and the repository merge gate pass;
12. prefer the repository safe merge gate:

```powershell
pwsh scripts/wait_for_pr_green_then_merge.ps1 -PRNumber <PR_NUMBER>
```

13. verify the PR merged;
14. return local checkout to `main` and pull;
15. verify the merge is present and post-merge `main` CI is green;
16. update this handoff to actual merged state;
17. only then begin the next dependent package.

Do not use `-DangerouslySkipMainVerification` in the autonomous path.

If post-merge `main` fails, repair it through a new focused PR before starting the next package.

## GitHub tooling reliability

GitHub MCP has been unreliable in the normal local workflow. Do not let it block work.

Prefer for write operations, in order where appropriate:

1. local `git`;
2. GitHub CLI `gh`;
3. repository PowerShell scripts;
4. authenticated GitHub REST API;
5. GitHub MCP only when healthy and useful.

Do not repeatedly retry a broken MCP when `git`/`gh` can complete the operation.

## D-drive rule

Local repository:

```text
D:\App Projects\Media-Mix-Lab
```

Any new local environment, dependency installation, package-manager cache, browser binary, temporary build artefact, model artefact or substantial generated file must stay on `D:`.

Follow the repository's existing D-drive tooling conventions. Preferred operational root remains:

```text
D:\Ancestry-MMM
```

Examples:

```text
D:\Ancestry-MMM\envs
D:\Ancestry-MMM\tools
D:\Ancestry-MMM\cache
D:\Ancestry-MMM\temp
D:\Ancestry-MMM\logs
D:\Ancestry-MMM\test-artifacts
```

Do not make unnecessary global/system installations. If a required tool cannot be redirected away from `C:`, stop before installing it and report the issue.

## Real-data rule

Never commit real Ancestry source data, model traces, posterior files, secrets or confidential data-derived artefacts.

Use synthetic data for CI and browser tests.

Keep local real-data analysis artefacts under governed D-drive locations and untracked.

## Deferred decision-bound work

Do not implement unresolved statistical/causal/product work as part of UI cleanup. In particular, do not use UX work to silently decide:

- production hierarchy replacement;
- sequential-weekly optimisation;
- Search planning eligibility or cap optimisation;
- SEO causal estimands or intervention semantics;
- Finance-owned FX provider/rate-set/future-assumption choices;
- time-varying baseline mathematics;
- future-assumption bundle semantics;
- Chronos-2 integration;
- unresolved ragged market-specific predictor mathematics.

Improve how blockers are explained, not how they are bypassed.
