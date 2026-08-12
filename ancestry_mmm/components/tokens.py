"""Shared design tokens for the Family History & DNA MMM workbench.

The palette is an original analytical system: warm enough to feel considered,
neutral enough for dense tables and charts, and explicit about the difference
between interaction, context, and semantic status colours.

Presentation-only: no analytical, model, or governance behaviour lives here,
and nothing here is imported by ``ancestry_mmm.core``.
"""

from ancestry_mmm.utils.config import THEME_COLORS


SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "20px",
    "xl": "32px",
}

RADIUS = {
    "sm": "6px",
    "md": "10px",
    "lg": "12px",
}

SURFACE = {
    "base": THEME_COLORS["canvas"],
    "raised": THEME_COLORS["surface_subtle"],
    "card": THEME_COLORS["surface"],
    "border": THEME_COLORS["border_subtle"],
    "border_strong": THEME_COLORS["border_strong"],
}

TEXT = {
    "primary": THEME_COLORS["text_primary"],
    "muted": THEME_COLORS["text_secondary"],
    "accent": THEME_COLORS["action_primary"],
    "context": THEME_COLORS["context_accent"],
}

# Semantic status colours are deliberately separate from interaction/context.
STATUS_COLOR = {
    "neutral": TEXT["muted"],
    "positive": THEME_COLORS["success"],
    "caution": THEME_COLORS["warning"],
    "negative": THEME_COLORS["error"],
    "info": THEME_COLORS["info"],
}


def shell_css() -> str:
    """Return the shared CSS for shell chrome and analytical surfaces."""

    return f"""
    <style>
    :root {{
        --mmm-canvas: {SURFACE["base"]};
        --mmm-surface: {SURFACE["card"]};
        --mmm-border: {SURFACE["border"]};
        --mmm-text: {TEXT["primary"]};
        --mmm-muted: {TEXT["muted"]};
        --mmm-action: {TEXT["accent"]};
        --mmm-context-accent: {TEXT["context"]};
    }}
    [data-testid="stAppViewContainer"] {{
        background: {SURFACE["base"]};
    }}
    [data-testid="stMainBlockContainer"] {{
        max-width: 1440px;
        padding-top: 2.25rem;
        padding-bottom: 3rem;
    }}
    section[data-testid="stSidebar"] {{
        background: {SURFACE["card"]};
        border-right: 1px solid {SURFACE["border"]};
    }}
    section[data-testid="stSidebar"] > div {{
        padding-top: 1.35rem;
    }}
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
        margin-bottom: 0;
    }}
    .mmm-brand-lockup {{
        padding: 0.1rem 0.35rem 1.25rem;
        border-bottom: 1px solid {SURFACE["border"]};
        margin-bottom: 0.85rem;
    }}
    .mmm-brand-product {{
        color: {TEXT["primary"]};
        font-size: 1.08rem;
        font-weight: 700;
        line-height: 1.3;
    }}
    .mmm-brand-function {{
        color: {TEXT["muted"]};
        font-size: 0.76rem;
        line-height: 1.35;
        margin-top: 0.22rem;
    }}
    .mmm-brand-context {{
        color: {TEXT["muted"]};
        font-size: 0.68rem;
        letter-spacing: 0.03em;
        line-height: 1.35;
        margin-top: 0.5rem;
    }}
    .mmm-nav-group {{
        font-size: 0.67rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: {TEXT["muted"]};
        margin: 1.2rem 0 0.35rem 0.35rem;
        font-weight: 750;
    }}
    section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
        border-left: 3px solid transparent;
        border-radius: 0 {RADIUS["sm"]} {RADIUS["sm"]} 0;
        color: {TEXT["primary"]};
        margin: 0.12rem 0;
        min-height: 2.1rem;
        padding: 0.38rem 0.55rem;
        transition: background 120ms ease, border-color 120ms ease;
    }}
    section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{
        background: {THEME_COLORS["surface_selected"]};
    }}
    section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"] {{
        background: {THEME_COLORS["surface_selected"]};
        border-left-color: {TEXT["accent"]};
        font-weight: 700;
    }}
    .mmm-sidebar-footnote {{
        border-top: 1px solid {SURFACE["border"]};
        color: {TEXT["muted"]};
        font-size: 0.72rem;
        line-height: 1.45;
        margin-top: 1.2rem;
        padding: 0.75rem 0.35rem 0;
    }}
    .mmm-context-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 1.25rem;
        padding: 0.55rem 0 0.85rem;
        margin-bottom: 1.35rem;
        border-bottom: 1px solid {SURFACE["border"]};
        font-size: 0.8rem;
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
        font-weight: 600;
        overflow-wrap: anywhere;
    }}
    .mmm-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: {RADIUS["sm"]};
        font-size: 0.72rem;
        font-weight: 650;
        border: 1px solid transparent;
        white-space: nowrap;
        margin-right: 6px;
    }}
    .mmm-panel-title {{
        color: {TEXT["primary"]};
        font-weight: 700;
        margin-bottom: 4px;
    }}
    .mmm-header-desc {{
        color: {TEXT["muted"]};
        font-size: 1rem;
        line-height: 1.55;
        max-width: 72ch;
        margin-top: -4px;
        margin-bottom: {SPACING["md"]};
    }}
    .mmm-task-prompt {{
        color: {TEXT["primary"]};
        font-size: 0.86rem;
        line-height: 1.45;
        margin: -0.35rem 0 {SPACING["md"]};
        max-width: 72ch;
    }}
    .mmm-task-prompt span {{
        color: {TEXT["accent"]};
        font-size: 0.68rem;
        font-weight: 750;
        letter-spacing: 0.06em;
        margin-right: 0.45rem;
        text-transform: uppercase;
    }}
    .mmm-next-step {{
        border-top: 1px solid {SURFACE["border"]};
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem 0.75rem;
        margin-top: 2rem;
        padding-top: 0.8rem;
        align-items: baseline;
    }}
    .mmm-next-step-label {{
        color: {TEXT["accent"]};
        font-size: 0.68rem;
        font-weight: 750;
        letter-spacing: 0.06em;
    }}
    .mmm-next-step-copy {{
        color: {TEXT["muted"]};
        font-size: 0.86rem;
        line-height: 1.45;
    }}
    .mmm-workbench-note {{
        align-items: baseline;
        border-left: 3px solid {THEME_COLORS["border_subtle"]};
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem 0.6rem;
        margin: 0.15rem 0 1rem;
        padding: 0.15rem 0 0.15rem 0.7rem;
    }}
    .mmm-workbench-note.editable {{ border-left-color: {TEXT["accent"]}; }}
    .mmm-workbench-note.derived {{ border-left-color: {TEXT["context"]}; }}
    .mmm-workbench-note.governed {{ border-left-color: {STATUS_COLOR["caution"]}; }}
    .mmm-workbench-note-label {{
        color: {TEXT["primary"]};
        font-size: 0.68rem;
        font-weight: 750;
        letter-spacing: 0.055em;
        text-transform: uppercase;
    }}
    .mmm-workbench-note-copy {{
        color: {TEXT["muted"]};
        font-size: 0.82rem;
        line-height: 1.45;
    }}
    /* Native dividers are retained as structural spacing, not card borders. */
    hr {{
        border: 0;
        border-top: 1px solid transparent;
        margin: 0.65rem 0;
    }}
    .mmm-home-identity {{
        border-left: 3px solid {TEXT["context"]};
        margin: 0.15rem 0 1.7rem;
        padding-left: 1rem;
        position: relative;
    }}
    .mmm-home-product {{
        color: {TEXT["primary"]};
        font-size: clamp(1.7rem, 2.6vw, 2.35rem);
        font-weight: 760;
        letter-spacing: -0.025em;
        line-height: 1.12;
        margin-top: 0.22rem;
    }}
    .mmm-home-description {{
        color: {TEXT["muted"]};
        font-size: 1rem;
        line-height: 1.5;
        margin-top: 0.6rem;
        max-width: 66ch;
    }}
    div[data-testid="stVerticalBlock"] > div:has(> div .mmm-panel-marker-neutral) {{
        padding-bottom: 0.25rem;
    }}
    /* Only semantic warning/blocking panels receive a bordered surface. */
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-info) {{
        background: {THEME_COLORS["surface_info"]};
        border-color: {THEME_COLORS["focus_ring"]} !important;
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-caution) {{
        background: {THEME_COLORS["surface_warning"]};
        border-color: {THEME_COLORS["warning"]} !important;
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:has(> div .mmm-panel-marker-negative) {{
        background: {THEME_COLORS["surface_error"]};
        border-color: {THEME_COLORS["error"]} !important;
    }}
    </style>
    """
