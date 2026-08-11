"""Shared design tokens for the app shell (Phase 1 of the Streamlit UI/UX
overhaul - see docs/decision_log.md).

Centralises spacing, radius, surface/background and text-hierarchy tokens
as a thin extension of the existing dark graphite-green identity
(.streamlit/config.toml, ancestry_mmm.utils.config.THEME_COLORS) - it does
not replace that palette, only gives every shell primitive (sidebar, context
bar, page header, panels, status badges) a single, consistent set of values
to build from instead of each hand-rolling its own spacing/border/radius
numbers.

Presentation-only: no analytical, model, or governance behaviour lives
here, and nothing here is imported by ancestry_mmm/core.
"""

from ancestry_mmm.utils.config import THEME_COLORS

# Spacing scale (CSS length strings) - use these instead of ad-hoc px/rem
# values in any new component CSS.
SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "20px",
    "xl": "32px",
}

# Corner radius scale.
RADIUS = {
    "sm": "6px",
    "md": "10px",
    "lg": "14px",
}

# Surface/background tokens, layered on top of THEME_COLORS rather than
# duplicating its values.
SURFACE = {
    "base": THEME_COLORS["background"],
    "raised": THEME_COLORS["background_secondary"],
    "card": THEME_COLORS["card"],
    "border": THEME_COLORS["border"],
    "border_strong": "#3D5245",
}

# Text hierarchy tokens.
TEXT = {
    "primary": THEME_COLORS["foreground"],
    "muted": THEME_COLORS["foreground_muted"],
    "accent": THEME_COLORS["accent"],
}

# Semantic status colours - the single colour vocabulary reused by
# components/status.py's badge mapping and by the sidebar's readiness
# indicators, so status meaning is never reinvented per call site.
# Deliberately no purple/blue AI-gradient accent - "info" reuses the
# existing muted slate-green rather than introducing a new hue family.
STATUS_COLOR = {
    "neutral": TEXT["muted"],
    "positive": "#34A871",
    "caution": "#D9A441",
    "negative": "#E2555B",
    "info": "#6B8B7A",
}


def shell_css() -> str:
    """CSS for shared shell chrome: nav group headers, the project context
    bar, page-header description text, status badges and panel primitives.
    Injected once by ``apply_theme()``; every primitive in ``ui.py`` only
    ever applies one of these class names, never an inline style block of
    its own, so the shell's visual language stays in exactly one place.
    """
    return f"""
    <style>
    .mmm-nav-group {{
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: {TEXT["muted"]};
        margin: {SPACING["md"]} 0 {SPACING["xs"]} 0;
        font-weight: 600;
    }}
    .mmm-context-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: {SPACING["lg"]};
        padding: {SPACING["sm"]} {SPACING["md"]};
        margin-bottom: {SPACING["md"]};
        background: {SURFACE["raised"]};
        border: 1px solid {SURFACE["border"]};
        border-radius: {RADIUS["md"]};
        font-size: 0.85rem;
        align-items: center;
    }}
    .mmm-context-item {{
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }}
    .mmm-context-label {{
        font-size: 0.66rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: {TEXT["muted"]};
    }}
    .mmm-context-value {{
        color: {TEXT["primary"]};
        font-weight: 500;
        overflow-wrap: anywhere;
    }}
    .mmm-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 9px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        border: 1px solid transparent;
        white-space: nowrap;
        margin-right: 6px;
    }}
    .mmm-header-desc {{
        color: {TEXT["muted"]};
        margin-top: -4px;
        margin-bottom: {SPACING["sm"]};
    }}
    .mmm-panel-title {{
        font-weight: 600;
        margin-bottom: 4px;
    }}
    /* Panel primitives (SectionCard/InfoPanel/WarningPanel/BlockingPanel in
       ui.py) render a hidden marker span as the first child of a bordered
       st.container(); :has() tints the container itself by kind, the same
       technique already used above to retint st.info. Falls back cleanly
       to a plain bordered container if a future Streamlit release renames
       this testid - the marker/title text still render either way. */
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-info) {{
        background: rgba(107, 139, 122, 0.12);
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-caution) {{
        background: rgba(217, 164, 65, 0.10);
        border-color: #4a3f26 !important;
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-negative) {{
        background: rgba(226, 85, 91, 0.10);
        border-color: #4a2a2c !important;
    }}
    </style>
    """
