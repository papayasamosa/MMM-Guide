"""Page 1: upload media / outcomes / controls sources, or load the synthetic demo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    clear_model_state,
    dataframe_column_config,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_status_badges,
    SectionCard,
    WarningPanel,
)
from ancestry_mmm.data import (
    load_file_with_source_version,
    load_all_sample_sources,
    get_data_summary,
)
from ancestry_mmm.core.coverage import (
    SourceVersion,
    SourceDefinition,
    LOGICAL_SOURCE_DOMAINS,
    REQUIRED_LOGICAL_SOURCE_DOMAINS,
    DOMAIN_OUTCOMES,
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    resolve_source_logical_domain,
)

# REQ-DATAIN-001: human-readable labels for the four governed logical
# source domains - Outcomes/Activity and Media/Context and External
# Factors are required for a complete project; Experiment Evidence is
# optional.
_DOMAIN_LABELS = {
    DOMAIN_OUTCOMES: "Outcomes",
    DOMAIN_ACTIVITY_AND_MEDIA: "Activity and Media",
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS: "Context and External Factors",
    DOMAIN_EXPERIMENT_EVIDENCE: "Experiment Evidence (optional)",
}

st.set_page_config(
    page_title="Data Upload | Ancestry Family History & DNA MMM",
    page_icon="🧬",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("data_upload")

# REQ-DATAIN-001: header badge reflects whether every required logical
# domain (Outcomes, Activity and Media, Context and External Factors) has
# at least one supplied source yet - never a guess, computed the same way
# the "Sources by logical domain" section below computes it.
_sources_at_load = st.session_state.get("raw_sources") or {}
_definitions_at_load = st.session_state.get("source_definitions") or []
_domains_supplied_at_load = {
    resolve_source_logical_domain(name, _definitions_at_load)
    for name in _sources_at_load
}
_required_missing_at_load = [
    d for d in REQUIRED_LOGICAL_SOURCE_DOMAINS if d not in _domains_supplied_at_load
]
if not _sources_at_load:
    _header_badges = ["awaiting_data"]
elif not _required_missing_at_load:
    _header_badges = ["ready"]
else:
    _header_badges = ["current"]

render_page_header(
    "data_upload",
    description=(
        "Bring together Outcomes, Activity and Media, and Context and External "
        "Factors. Start with the synthetic fixture or add governed source files."
    ),
    badges=_header_badges,
)

st.markdown("### Project setup")
st.session_state.setdefault("project_name", "ancestry-fh-uk")
st.session_state["project_name"] = st.text_input(
    "Project name",
    value=st.session_state["project_name"],
    help="Used to namespace the curve bank and exported project bundles for this project.",
)

tab_demo, tab_upload = st.tabs(["Synthetic fixture", "Upload sources"])

with tab_demo:
    st.markdown(
        "Use the deterministic weekly UK / Australia / Canada fixture to explore the "
        "workflow end-to-end. **This is not real Ancestry data.**"
    )
    if st.button("Load synthetic demo sources", type="primary"):
        frames, err = load_all_sample_sources()
        if err:
            st.error(err)
        else:
            ltv_df = frames.pop("ltv")
            st.session_state["raw_sources"] = frames
            st.session_state["sample_ltv"] = {
                row.segment: row.ltv for row in ltv_df.itertuples()
            }
            # Demo sources are not real uploads and have no genuine
            # checksum/provenance - wholesale-replacing raw_sources this
            # way must not leave a prior real upload's provenance appearing
            # to describe the now-demo frame for a reused name (e.g. a
            # previous "media" upload).
            st.session_state["active_source_upload_version"] = {}
            # REQ-DATAIN-001: the demo fixture's own source names map
            # unambiguously onto the governed logical domains - this is a
            # naming-obvious classification of this repository's own
            # synthetic sample data, not an invented business rule for
            # real Ancestry sources.
            _demo_domains = {
                "media": DOMAIN_ACTIVITY_AND_MEDIA,
                "outcomes": DOMAIN_OUTCOMES,
                "controls": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
            }
            st.session_state["source_definitions"] = [
                SourceDefinition(
                    source_id=name, name=name, logical_domain=domain
                ).to_dict()
                for name, domain in _demo_domains.items()
                if name in frames
            ]
            st.session_state["data_loaded"] = True
            clear_model_state()
            st.success(
                f"Loaded demo sources: {', '.join(f'{k} ({v.shape[0]} rows x {v.shape[1]} cols)' for k, v in frames.items())}"
            )

with tab_upload:
    st.caption("Add one or more governed source files. You can add more later.")
    source_name = st.text_input(
        "Source name *", value="media", help="e.g. media, outcomes, controls"
    )
    # REQ-DATAIN-001 (review finding): a Streamlit selectbox pre-selects
    # its first option, so listing LOGICAL_SOURCE_DOMAINS directly would
    # let "Add source" be clicked without the analyst ever making this
    # required business classification - silently persisting an
    # unauthorized default domain (worse still, paired with the adjacent
    # "media" source-name default, defaulting to "Outcomes" would be
    # actively wrong). An explicit, non-domain placeholder is the default
    # instead, and "Add source" blocks until a real domain is chosen.
    _DOMAIN_PLACEHOLDER = "— Select a logical domain —"
    logical_domain_choice = st.selectbox(
        "Logical source domain *",
        [_DOMAIN_PLACEHOLDER, *LOGICAL_SOURCE_DOMAINS],
        format_func=lambda d: _DOMAIN_LABELS.get(d, d),
        help=(
            "REQ-DATAIN-001: every source belongs to one governed logical "
            "domain. Outcomes, Activity and Media, and Context and "
            "External Factors are required for a complete project; "
            "Experiment Evidence is optional."
        ),
    )
    uploaded = st.file_uploader(
        "Choose a CSV, Excel, or Parquet file *",
        type=["csv", "xlsx", "xls", "xlsm", "parquet"],
        key="uploader",
    )

    if uploaded is not None and st.button("Add source"):
        if not source_name.strip():
            st.error("Source name is required.")
        elif logical_domain_choice == _DOMAIN_PLACEHOLDER:
            st.error("Choose a logical source domain before adding this source.")
        else:
            existing_versions = [
                SourceVersion.from_dict(v)
                for v in st.session_state.get("source_versions") or []
            ]
            df, source_version, err = load_file_with_source_version(
                uploaded, source_name, existing_versions
            )
            if err:
                st.error(err)
            else:
                sources = dict(st.session_state.get("raw_sources") or {})
                sources[source_name] = df
                st.session_state["raw_sources"] = sources
                st.session_state["source_versions"] = [
                    v.to_dict() for v in existing_versions
                ] + [source_version.to_dict()]
                active = dict(
                    st.session_state.get("active_source_upload_version") or {}
                )
                active[source_name] = source_version.version
                st.session_state["active_source_upload_version"] = active
                # REQ-DATAIN-001: record/update this source_id's governed
                # SourceDefinition - one record per source_id, replaced
                # (not appended) if the analyst re-adds the same name with
                # a different domain, since a source has exactly one
                # current logical domain.
                definitions = [
                    d
                    for d in (st.session_state.get("source_definitions") or [])
                    if d.get("source_id") != source_name
                ]
                definitions.append(
                    SourceDefinition(
                        source_id=source_name,
                        name=source_name,
                        logical_domain=logical_domain_choice,
                    ).to_dict()
                )
                st.session_state["source_definitions"] = definitions
                st.session_state["data_loaded"] = True
                clear_model_state()
                st.success(
                    f"Loaded {df.shape[0]} rows from {uploaded.name} as source "
                    f"'{source_name}' (v{source_version.version}, checksum "
                    f"{source_version.checksum[:12]}...)."
                )

sources = st.session_state.get("raw_sources") or {}


def _render_source_detail(name: str, df) -> None:
    """One physical source's expander: version/provenance, logical domain,
    row/column summary and preview - identical content regardless of which
    domain group it's rendered under, so several physical files can share
    one logical domain's card without duplicating this logic per domain."""
    with st.expander(
        f"**{name}** - {df.shape[0]} rows x {df.shape[1]} columns", expanded=False
    ):
        # Look up the *specific* version that actually produced this name's
        # current frame (never "the latest history entry for this name" - a
        # prior real upload's provenance must not be displayed against a
        # frame that isn't actually that upload, e.g. after loading demo
        # data under a reused name).
        active_version = (
            st.session_state.get("active_source_upload_version") or {}
        ).get(name)
        active_record = next(
            (
                v
                for v in st.session_state.get("source_versions") or []
                if v.get("source_id") == name and v.get("version") == active_version
            ),
            None,
        )
        st.caption(
            "Uploaded data" if active_record is not None else "Synthetic demo data"
        )
        if active_record is not None:
            st.caption(
                f"Source version v{active_record['version']} - "
                f"`{active_record['original_filename']}` - "
                f"checksum `{active_record['checksum'][:12]}...` - "
                f"uploaded {active_record['uploaded_at']}"
            )
        # REQ-DATAIN-001: a source with no recorded SourceDefinition (e.g. a
        # bundle imported from before this capability existed) reads as
        # "Unclassified", never a guessed domain.
        domain = resolve_source_logical_domain(
            name, st.session_state.get("source_definitions") or []
        )
        st.caption(
            f"Logical domain: **"
            f"{_DOMAIN_LABELS.get(domain, 'Unclassified (no domain recorded)')}"
            "**"
        )
        summary = get_data_summary(df)
        c1, c2, c3 = st.columns(3)
        c1.metric("Rows", f"{summary['rows']:,}")
        c2.metric("Columns", summary["columns"])
        c3.metric("Missing values", f"{int(summary['missing_values']):,}")
        preview = df.head(20)
        st.dataframe(
            preview, width="stretch", column_config=dataframe_column_config(preview)
        )
        if st.button(f"Remove '{name}'", key=f"remove_{name}"):
            remaining = dict(st.session_state.get("raw_sources") or {})
            remaining.pop(name, None)
            st.session_state["raw_sources"] = remaining
            active = dict(st.session_state.get("active_source_upload_version") or {})
            active.pop(name, None)
            st.session_state["active_source_upload_version"] = active
            st.rerun()


if sources:
    st.markdown("## Sources by logical domain")
    st.caption(
        "REQ-DATAIN-001: a logical domain is not a physical file - any "
        "number of physical source files/versions may exist under one "
        "domain. A source belongs to exactly one of the three required "
        "domains (Outcomes, Activity and Media, Context and External "
        "Factors) or the optional Experiment Evidence domain."
    )

    definitions = st.session_state.get("source_definitions") or []
    sources_by_domain: "dict[str | None, list]" = {}
    for name, df in sources.items():
        domain = resolve_source_logical_domain(name, definitions)
        sources_by_domain.setdefault(domain, []).append((name, df))

    missing_required_labels = []
    for domain in REQUIRED_LOGICAL_SOURCE_DOMAINS:
        supplied = sources_by_domain.get(domain) or []
        with SectionCard(
            _DOMAIN_LABELS[domain],
            description="Required for a complete project.",
        ):
            render_status_badges(["ready" if supplied else "blocked"])
            if not supplied:
                missing_required_labels.append(_DOMAIN_LABELS[domain])
                st.caption("No source supplied yet for this required domain.")
            else:
                st.caption(
                    f"{len(supplied)} physical source file(s) supplied under "
                    "this domain."
                )
                for name, df in supplied:
                    _render_source_detail(name, df)

    optional_supplied = sources_by_domain.get(DOMAIN_EXPERIMENT_EVIDENCE) or []
    with SectionCard(
        _DOMAIN_LABELS[DOMAIN_EXPERIMENT_EVIDENCE],
        description="Optional - not required for a complete project.",
    ):
        render_status_badges(["ready" if optional_supplied else "optional"])
        if optional_supplied:
            st.caption(
                f"{len(optional_supplied)} physical source file(s) supplied "
                "under this domain."
            )
            for name, df in optional_supplied:
                _render_source_detail(name, df)
        else:
            st.caption("No experiment-evidence source supplied.")

    unclassified = sources_by_domain.get(None) or []
    if unclassified:
        with WarningPanel(
            "Unclassified sources",
            description="No SourceDefinition recorded - never guessed into "
            "one of the four governed domains.",
        ):
            for name, df in unclassified:
                _render_source_detail(name, df)

    if missing_required_labels:
        st.warning(
            "Missing required logical domain(s): "
            + ", ".join(missing_required_labels)
            + ". **Next action:** upload at least one source under each "
            "missing domain above before continuing."
        )

    render_next_step("data_upload")
else:
    render_empty_state(
        "No sources loaded yet. Load the demo data or upload a file above to get started.",
        what_for=(
            "Loading source data under the three required logical domains "
            "(Outcomes; Activity and Media; Context and External Factors) "
            "plus the optional Experiment Evidence domain, per REQ-DATAIN-001."
        ),
        next_action="Load the synthetic demo data, or upload a file and choose its logical domain above.",
    )
