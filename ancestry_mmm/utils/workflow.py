"""Single source of truth for the app's workflow: page order, sidebar labels,
on-page guidance copy and next-step routing. Used by the sidebar, the page
header, the step indicator and the next-step panel so all four stay in sync
instead of being hand-maintained separately on every page.
"""

from typing import Any, Dict, List, Optional

HOME_KEY = "home"

# Ordered workflow (see TOTAL_STEPS below - derived from this list's length,
# never hand-counted). Each entry:
#   key       - stable identifier used across the app
#   label     - exact sidebar / navigation label
#   path      - st.page_link / st.switch_page target
#   title     - page H1
#   purpose   - one short sentence shown under the title
#   steps     - short numbered list of what the user needs to do on this page
#   next      - the "Next:" message shown in the bottom next-step panel
WORKFLOW_STEPS: List[Dict[str, Any]] = [
    {
        "key": "data_upload",
        "label": "Data Sources",
        "path": "pages/01_Data_Upload.py",
        "title": "Data Sources",
        "purpose": "Upload the media, outcome, and control files used by the model, or start from the built-in demo data.",
        "steps": [
            "Load the demo data, or upload one file for each source type.",
            "Check that the date and market columns are present.",
            "Review the preview and row counts.",
            "Continue to Prepare Data.",
        ],
        "next": "Join and prepare the sources in Prepare Data.",
    },
    {
        "key": "transform_pipeline",
        "label": "Prepare Data",
        "path": "pages/02_Transform_Pipeline.py",
        "title": "Prepare Data",
        "purpose": "Join your sources into one dataset, then record any clean-up steps as a reusable pipeline.",
        "steps": [
            "Join the uploaded sources on a shared date (and market) column.",
            "Add any transformations needed - renaming, type casts, calculated columns, lags, filling gaps.",
            "Review the transformed preview.",
            "Continue to Coverage & Gaps.",
        ],
        "next": "Review variable coverage and missingness in Coverage & Gaps.",
    },
    {
        "key": "data_coverage",
        "label": "Coverage & Gaps",
        "path": "pages/15_Data_Coverage.py",
        "title": "Coverage & Gaps",
        "purpose": "Review each variable's coverage and missingness by market before defining model structure.",
        "steps": [
            "Choose which joined columns to treat as governed variables, and declare each one's frequency, variable class and source.",
            "Build the coverage matrix and review the states it finds - missing, unavailable, not applicable, estimated, unknown, and so on.",
            "Propose and approve a treatment for any variable you want eligible for official use.",
            "Save the reviewed matrix as a new version.",
        ],
        "next": "Define segments, markets, channels, and outcomes in Model Structure.",
    },
    {
        "key": "structure",
        "label": "Model Structure",
        "path": "pages/03_Structure_Segments_Markets.py",
        "title": "Model Structure",
        "purpose": "Tell the model which columns are markets, segments, channels, promotions, controls and value.",
        "steps": [
            "Choose which markets to include.",
            "Map each acquisition segment to its outcome column.",
            "Select media channels, promo flags, controls and LTV per segment.",
            "Save the structure to validate it.",
        ],
        "next": "Build the variable-level causal graph in Causal Graph.",
    },
    {
        "key": "causal_graph",
        "label": "Causal Graph",
        "path": "pages/14_Causal_Graph.py",
        "title": "Causal Graph",
        "purpose": "Build a variable-level causal structure. Once approved, it is the authoritative structural input to model compilation.",
        "steps": [
            "Add variable nodes (intervention, mediator, outcome, control, ...) and draw edges between them.",
            "Set each edge's role and lag in the property panel.",
            "Fix any validation errors, then review the model-plan preview.",
            "Save a draft, or approve the graph once it passes validation.",
            "Prepare a compiled model configuration from the approved graph.",
        ],
        "next": "Map each channel's media inputs in Media Mapping.",
    },
    {
        "key": "channel_media_units",
        "label": "Media Mapping",
        "path": "pages/10_Channel_Media_Units.py",
        "title": "Media Mapping",
        "purpose": "Map each channel's spend column to a physical delivery metric (impressions, GRPs, clicks, ...) for CPA and media-unit reporting.",
        "steps": [
            "For each channel, optionally map a response-unit column (impressions, GRPs, clicks, TVRs, reach, ...).",
            "Record the unit type, currency and cost basis.",
            "Save the mapping - it's optional and can be skipped or added later.",
        ],
        "next": "Add market context in Market Context.",
    },
    {
        "key": "market_descriptors",
        "label": "Market Context",
        "path": "pages/11_Market_Descriptors.py",
        "title": "Market Context",
        "purpose": "Record market currency and optional descriptive context for reporting and future interpretation.",
        "steps": [
            "Review each market's data coverage card.",
            "Record currency and, optionally, market descriptors.",
            "Save - every field is optional and can be filled in later.",
        ],
        "next": "Configure media response and hierarchy in Model Setup.",
    },
    {
        "key": "model_config",
        "label": "Model Setup",
        "path": "pages/04_Model_Config.py",
        "title": "Model Setup",
        "purpose": "Choose the model structure, and set the adstock, saturation, pooling and MCMC settings the model will fit with.",
        "steps": [
            "Choose a shared response across markets, or market-specific responses with partial pooling.",
            "Review the geo hierarchy detected from your structure.",
            "Adjust curve and pooling priors if needed - the defaults are reasonable starting points.",
            "Set sampling controls under Advanced settings if needed.",
            "Prepare the modelling frame.",
        ],
        "next": "Fit the chosen model structure in Fit Model.",
    },
    {
        "key": "model_training",
        "label": "Fit Model",
        "path": "pages/05_Model_Training.py",
        "title": "Fit Model",
        "purpose": "Fit the chosen model structure to the prepared data.",
        "steps": [
            "Review the observation, market, segment and channel counts.",
            "Start the fit and watch sampling progress.",
            "Wait for training to complete - this can take several minutes.",
            "Optionally save this fit as a candidate for model comparison.",
        ],
        "next": "Compare this fit with other candidates, if you have more than one.",
    },
    {
        "key": "compare_models",
        "label": "Model Comparison",
        "path": "pages/12_Compare_Models.py",
        "title": "Model Comparison",
        "purpose": "Compare fitted candidate models side by side before deciding which to review and approve.",
        "steps": [
            "Fit more candidates on Fit Model if you want to compare model structures - a shared curve, market-specific curves, or a single-market fit.",
            "Review convergence, in-sample fit and posterior predictive coverage side by side.",
            "Decide which fitted model to take forward to Diagnostics.",
        ],
        "next": "Review model diagnostics before approval in Model Diagnostics.",
    },
    {
        "key": "diagnostics",
        "label": "Model Diagnostics",
        "path": "pages/06_Diagnostics.py",
        "title": "Model Diagnostics",
        "purpose": "Check convergence, fit and plausibility before approving the model for planning.",
        "steps": [
            "Compute the scorecard.",
            "Review convergence, in-sample fit, posterior predictive coverage and plausibility flags.",
            "Approve the model once you're satisfied it's trustworthy.",
        ],
        "next": "Review results and save response curves.",
    },
    {
        "key": "curve_bank",
        "label": "Results & Response Curves",
        "path": "pages/07_Results_Curve_Bank.py",
        "title": "Results & Response Curves",
        "purpose": "Review channel and segment contributions, then save an approved model's curves to the versioned curve bank.",
        "steps": [
            "Review contribution and DNA halo results.",
            "Approve the model on Diagnostics if you haven't already.",
            "Save the current curves to the curve bank.",
        ],
        "next": "Generate a governed planning curve artifact in Planning Curves.",
    },
    {
        "key": "official_curve_generation",
        "label": "Planning Curves",
        "path": "pages/13_Official_Curve_Generation.py",
        "title": "Planning Curves",
        "purpose": "Generate and persist a governed planning curve artifact, distinct from exploratory fitted-parameter snapshots.",
        "steps": [
            "Pick an approved outcome authorised for curve_publication.",
            "Build a complete reference context per market - no field defaults silently.",
            "Record model-input support for each channel to include.",
            "Choose the posterior draw count and generate the artifact.",
            "Review its authorization and planning-support status.",
        ],
        "next": "Plan and compare allocations in Scenario Planner.",
    },
    {
        "key": "scenario_planner",
        "label": "Scenario Planner",
        "path": "pages/08_Scenario_Planner.py",
        "title": "Scenario Planner",
        "purpose": "Plan spend manually, or let constrained/unconstrained optimisation suggest an allocation.",
        "steps": [
            "Choose a market and planning window.",
            "Edit the spend plan directly, or add constraints and run optimisation.",
            "Save the scenarios you want to keep.",
        ],
        "next": "Export the project bundle for recovery or archival.",
    },
    {
        "key": "export",
        "label": "Export & Recovery",
        "path": "pages/09_Project_Export.py",
        "title": "Export & Recovery",
        "purpose": "Export a portable project bundle, or an Excel summary, for portability, recovery and later re-import.",
        "steps": [
            "Build and download the project bundle.",
            "Or build an Excel summary of curves and contributions.",
            "Keep the bundle as the system of record - session state is not saved automatically.",
        ],
        "next": "",
    },
]

TOTAL_STEPS = len(WORKFLOW_STEPS)

_BY_KEY = {step["key"]: step for step in WORKFLOW_STEPS}
_HOME = {
    "key": HOME_KEY,
    "label": "Home",
    "path": "app.py",
    "title": "Family History & DNA MMM",
}


def get_step(key: str) -> Optional[Dict[str, Any]]:
    """Look up a workflow page's metadata by key (None for an unknown key)."""
    if key == HOME_KEY:
        return _HOME
    return _BY_KEY.get(key)


def workflow_label(key: str, fallback: Optional[str] = None) -> str:
    """Return the current analyst-facing destination label for ``key``.

    Workflow keys and routes are stable persistence/navigation contracts;
    labels are presentation metadata. Centralising this lookup prevents
    empty states, warnings, and next actions from drifting away from the
    sidebar when a page is renamed.
    """
    step = get_step(key)
    if step is not None:
        return str(step["label"])
    return fallback if fallback is not None else key


def step_number(key: str) -> Optional[int]:
    """1-based position in the workflow (None for Home / unknown keys)."""
    for i, step in enumerate(WORKFLOW_STEPS, start=1):
        if step["key"] == key:
            return i
    return None


def next_step_key(key: str) -> Optional[str]:
    """The key of the workflow page that follows `key` (None if last or unknown)."""
    idx = None
    for i, step in enumerate(WORKFLOW_STEPS):
        if step["key"] == key:
            idx = i
            break
    if idx is None or idx + 1 >= len(WORKFLOW_STEPS):
        return None
    return WORKFLOW_STEPS[idx + 1]["key"]


def sidebar_entries() -> List[Dict[str, Any]]:
    """All pages in sidebar order, Home first."""
    return [_HOME] + WORKFLOW_STEPS


# Phase 1 UI overhaul (see docs/decision_log.md): a purely visual grouping
# of the same WORKFLOW_STEPS keys into workflow areas for the sidebar nav.
# This is presentation grouping only - it changes no route, key, or label,
# and every key here must already exist in WORKFLOW_STEPS/HOME_KEY (enforced
# by TestNavGroups in tests/test_workflow.py). Do not hand-maintain a
# second copy of page order/labels here; only the grouping itself lives in
# this list.
NAV_GROUPS: List[Dict[str, Any]] = [
    {"label": "OVERVIEW", "keys": [HOME_KEY]},
    {
        "label": "DATA",
        "keys": ["data_upload", "transform_pipeline", "data_coverage"],
    },
    {
        "label": "MODEL DESIGN",
        "keys": [
            "structure",
            "causal_graph",
            "channel_media_units",
            "market_descriptors",
            "model_config",
        ],
    },
    {
        "label": "FIT & VALIDATE",
        "keys": ["model_training", "compare_models", "diagnostics"],
    },
    {
        "label": "DECISION SUPPORT",
        "keys": ["curve_bank", "official_curve_generation", "scenario_planner"],
    },
    {"label": "OPERATIONS", "keys": ["export"]},
]


def nav_groups() -> List[Dict[str, Any]]:
    """NAV_GROUPS with each key resolved to its full step-metadata dict
    (via get_step), in group order. Unknown keys are skipped defensively
    rather than raising, since this is presentation-only grouping."""
    resolved = []
    for group in NAV_GROUPS:
        entries = [get_step(k) for k in group["keys"]]
        entries = [e for e in entries if e is not None]
        resolved.append({"label": group["label"], "entries": entries})
    return resolved


def home_workflow_lines() -> List[str]:
    """Numbered '**Label** - purpose.' lines for the Home page's workflow
    summary, derived directly from WORKFLOW_STEPS so it can never drift out
    of sync with the actual page count, order, or labels (see
    docs/decision_log.md - this replaced a hand-maintained, stale copy)."""
    return [
        f"{i}. **{step['label']}** - {step['purpose']}"
        for i, step in enumerate(WORKFLOW_STEPS, start=1)
    ]
