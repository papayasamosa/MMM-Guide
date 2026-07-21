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
        "label": "Data Upload",
        "path": "pages/01_Data_Upload.py",
        "title": "Data Upload",
        "purpose": "Upload the media, outcome, and control files used by the model, or start from the built-in demo data.",
        "steps": [
            "Load the synthetic demo data, or upload one file for each source type.",
            "Check that the date and market columns are present.",
            "Review the preview and row counts.",
            "Continue to Transform Pipeline.",
        ],
        "next": "Join and prepare the uploaded sources in Transform Pipeline.",
    },
    {
        "key": "transform_pipeline",
        "label": "Transform Pipeline",
        "path": "pages/02_Transform_Pipeline.py",
        "title": "Transform Pipeline",
        "purpose": "Join your sources into one dataset, then record any clean-up steps as a reusable pipeline.",
        "steps": [
            "Join the uploaded sources on a shared date (and market) column.",
            "Add any transformations needed - renaming, type casts, calculated columns, lags, filling gaps.",
            "Review the transformed preview.",
            "Continue to Structure: Segments & Markets.",
        ],
        "next": "Define segments, markets, channels, and outcome columns in Structure: Segments & Markets.",
    },
    {
        "key": "structure",
        "label": "Structure: Segments & Markets",
        "path": "pages/03_Structure_Segments_Markets.py",
        "title": "Structure: Segments & Markets",
        "purpose": "Tell the model which columns are markets, segments, channels, promotions, controls and value.",
        "steps": [
            "Choose which markets to include.",
            "Map each acquisition segment to its outcome column.",
            "Select media channels, promo flags, controls and LTV per segment.",
            "Save the structure to validate it.",
        ],
        "next": "Map each channel's spend and physical media units in Channel & Media Units.",
    },
    {
        "key": "channel_media_units",
        "label": "Channel & Media Units",
        "path": "pages/10_Channel_Media_Units.py",
        "title": "Channel & Media Units",
        "purpose": "Map each channel's spend column to a physical delivery metric (impressions, GRPs, clicks, ...) for CPA and media-unit reporting.",
        "steps": [
            "For each channel, optionally map a response-unit column (impressions, GRPs, clicks, TVRs, reach, ...).",
            "Record the unit type, currency and cost basis.",
            "Save the mapping - it's optional and can be skipped or added later.",
        ],
        "next": "Add market context in Market Descriptors.",
    },
    {
        "key": "market_descriptors",
        "label": "Market Descriptors",
        "path": "pages/11_Market_Descriptors.py",
        "title": "Market Descriptors",
        "purpose": "Record market context (currency, audience, penetration, maturity) used to explain market-level differences.",
        "steps": [
            "Review each market's data coverage card.",
            "Record currency and, optionally, market descriptors.",
            "Save - every field is optional and can be filled in later.",
        ],
        "next": "Configure adstock, saturation and hierarchy priors in Model Configuration.",
    },
    {
        "key": "model_config",
        "label": "Model Configuration",
        "path": "pages/04_Model_Config.py",
        "title": "Model Configuration",
        "purpose": "Choose the model structure, and set the adstock, saturation, pooling and MCMC settings the model will fit with.",
        "steps": [
            "Choose a shared curve (Model A) or market-specific, partially pooled curves (Model C).",
            "Review the geo hierarchy detected from your structure.",
            "Adjust curve and pooling priors if needed - the defaults are reasonable starting points.",
            "Set MCMC sampling settings under Advanced settings if needed.",
            "Prepare the modelling frame.",
        ],
        "next": "Fit the chosen model structure in Model Training.",
    },
    {
        "key": "model_training",
        "label": "Model Training",
        "path": "pages/05_Model_Training.py",
        "title": "Model Training",
        "purpose": "Fit the chosen model structure to the prepared data.",
        "steps": [
            "Review the observation, market, segment and channel counts.",
            "Start the fit and watch sampling progress.",
            "Wait for training to complete - this can take several minutes.",
            "Optionally save this fit as a candidate for model comparison.",
        ],
        "next": "Compare this fit against other candidate models, if you've fit more than one.",
    },
    {
        "key": "compare_models",
        "label": "Compare Models",
        "path": "pages/12_Compare_Models.py",
        "title": "Compare Models",
        "purpose": "Compare fitted candidate models side by side before deciding which to review and approve.",
        "steps": [
            "Fit more candidates on Model Training if you want to compare model structures - a shared curve, market-specific curves, or a single-market fit.",
            "Review convergence, in-sample fit and posterior predictive coverage side by side.",
            "Decide which fitted model to take forward to Diagnostics.",
        ],
        "next": "Review diagnostics before approving a model.",
    },
    {
        "key": "diagnostics",
        "label": "Diagnostics",
        "path": "pages/06_Diagnostics.py",
        "title": "Diagnostics",
        "purpose": "Check convergence, fit and plausibility before approving the model for planning.",
        "steps": [
            "Compute the scorecard.",
            "Review convergence, in-sample fit, posterior predictive coverage and plausibility flags.",
            "Approve the model once you're satisfied it's trustworthy.",
        ],
        "next": "Review results and save curves to the Curve Bank.",
    },
    {
        "key": "curve_bank",
        "label": "Results & Curve Bank",
        "path": "pages/07_Results_Curve_Bank.py",
        "title": "Results & Curve Bank",
        "purpose": "Review channel and segment contributions, then save an approved model's curves to the versioned curve bank.",
        "steps": [
            "Review contribution and DNA halo results.",
            "Approve the model on Diagnostics if you haven't already.",
            "Save the current curves to the curve bank.",
        ],
        "next": "Plan and compare spend scenarios in the Scenario Planner.",
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
        "next": "Export the project bundle for handover.",
    },
    {
        "key": "export",
        "label": "Project Export & Handover",
        "path": "pages/09_Project_Export.py",
        "title": "Project Export & Handover",
        "purpose": "Export a portable project bundle, or an Excel summary, for handover and later re-import.",
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
    "title": "Marketing Mix Modelling & Scenario Planner",
}


def get_step(key: str) -> Optional[Dict[str, Any]]:
    """Look up a workflow page's metadata by key (None for an unknown key)."""
    if key == HOME_KEY:
        return _HOME
    return _BY_KEY.get(key)


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


def home_workflow_lines() -> List[str]:
    """Numbered '**Label** - purpose.' lines for the Home page's workflow
    summary, derived directly from WORKFLOW_STEPS so it can never drift out
    of sync with the actual page count, order, or labels (see
    docs/decision_log.md - this replaced a hand-maintained, stale copy)."""
    return [f"{i}. **{step['label']}** - {step['purpose']}" for i, step in enumerate(WORKFLOW_STEPS, start=1)]
