"""Page 1: upload media / outcomes / controls sources, or load the synthetic demo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    clear_model_state,
    dataframe_column_config,
    set_state,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_status_badges,
    render_workspace_note,
    SectionCard,
    WarningPanel,
)
from ancestry_mmm.data import (
    TEMPLATE_MIME_TYPE,
    build_standard_template,
    load_file_with_source_version,
    load_standard_workbook_with_source_version,
    load_all_sample_sources,
    load_realistic_sample_sources,
    get_data_summary,
    summarise_source_inventory,
    source_lineage_id,
    source_table_name,
    standard_template_filename,
)
from ancestry_mmm.data.templates import (
    OUTCOMES_TEMPLATE_SCHEMA_VERSION,
    canonicalize_standard_workbook,
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
from ancestry_mmm.core.outcomes import OutcomeDefinition, OutcomeGroupDefinition
from ancestry_mmm.core.outcome_import import (
    OUTCOME_SOURCE_STATUS_BLOCKED,
    OUTCOME_SOURCE_STATUS_V1_INCOMPLETE,
    OUTCOME_SOURCE_STATUS_V2_DRAFT,
    OutcomeCatalogueAdoption,
    adopt_outcome_source_draft,
    interpret_outcome_source,
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


def _workbook_table_source_id(source_name: str, sheet_name: str) -> str:
    """Stable session-state identity for one physical workbook table."""
    # Keep the identity safe for persistence's Windows parquet filenames;
    # Excel sheet names cannot contain these separator characters.
    return f"{source_name}__sheet__{sheet_name}"


def _is_excel_filename(filename: str) -> bool:
    return filename.lower().endswith((".xlsx", ".xls", ".xlsm"))


def _remove_source_lineage(source_name: str) -> None:
    """Remove the currently displayed tables for one workbook lineage."""
    prefix = f"{source_name}__sheet__"
    sources = dict(st.session_state.get("raw_sources") or {})
    for source_id in list(sources):
        if source_id == source_name or source_id.startswith(prefix):
            sources.pop(source_id, None)
    st.session_state["raw_sources"] = sources

    active = dict(st.session_state.get("active_source_upload_version") or {})
    for source_id in list(active):
        if source_id == source_name or source_id.startswith(prefix):
            active.pop(source_id, None)
    st.session_state["active_source_upload_version"] = active

    definitions = [
        definition
        for definition in (st.session_state.get("source_definitions") or [])
        if not (
            definition.get("source_id") == source_name
            or definition.get("source_id", "").startswith(prefix)
        )
    ]
    st.session_state["source_definitions"] = definitions


def _store_standard_workbook(
    source_name: str, workbook, source_version, logical_domain: str
) -> list[str]:
    """Store standard tables separately while retaining one workbook version."""
    _remove_source_lineage(source_name)
    recognised_sheets = {item.sheet_name for item in workbook.table_metadata}
    sources = dict(st.session_state.get("raw_sources") or {})
    definitions = list(st.session_state.get("source_definitions") or [])
    active = dict(st.session_state.get("active_source_upload_version") or {})
    stored: list[str] = []
    for sheet_name, table in workbook.tables.items():
        source_id = _workbook_table_source_id(source_name, sheet_name)
        sources[source_id] = table
        active[source_id] = source_version.version
        stored.append(source_id)
        if sheet_name in recognised_sheets:
            definitions.append(
                SourceDefinition(
                    source_id=source_id,
                    name=f"{source_name}/{sheet_name}",
                    logical_domain=logical_domain,
                ).to_dict()
            )
    st.session_state["raw_sources"] = sources
    st.session_state["source_definitions"] = definitions
    st.session_state["active_source_upload_version"] = active
    return stored


def _record_outcome_source_import(workbook, canonical_bundle) -> None:
    """Store source semantics separately, adopting only when no catalogue exists."""
    current_definitions = [
        OutcomeDefinition.from_dict(value)
        for value in (st.session_state.get("outcome_definitions") or [])
    ]
    current_groups = [
        OutcomeGroupDefinition.from_dict(value)
        for value in (st.session_state.get("outcome_groups") or [])
    ]
    source_import = interpret_outcome_source(
        schema_version=workbook.manifest.template_schema_version,
        outcome_definitions=canonical_bundle.outcome_definitions,
        outcome_groups=canonical_bundle.outcome_groups,
        outcome_reconciliation_groups=canonical_bundle.outcome_reconciliation_groups,
        outcome_completeness_metadata=canonical_bundle.outcome_completeness_metadata,
        source_warnings=workbook.manifest.warnings,
        current_outcomes=current_definitions,
        current_groups=current_groups,
    )
    set_state("outcome_source_import_status", source_import.to_dict())
    set_state(
        "outcome_source_draft",
        [item.to_dict() for item in source_import.outcome_definitions]
        if source_import.is_seedable_draft
        else None,
    )
    set_state(
        "outcome_source_draft_groups",
        [item.to_dict() for item in source_import.outcome_groups]
        if source_import.is_seedable_draft
        else [],
    )
    set_state(
        "outcome_source_draft_reconciliation_groups",
        [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in source_import.outcome_reconciliation_groups
        ]
        if source_import.is_seedable_draft
        else [],
    )

    # A v2 source is allowed to seed an empty catalogue as an unapproved
    # draft.  Existing catalogue records are never replaced by upload.
    if source_import.is_seedable_draft and not current_definitions:
        adoption = adopt_outcome_source_draft(source_import)
        adopted = adoption.to_state()
        for key, value in adopted.items():
            if key != "outcome_approvals":
                set_state(key, value)
        status = dict(source_import.to_dict())
        status["draft_seeded"] = True
        set_state("outcome_source_import_status", status)


def _render_outcome_source_review() -> None:
    """Render source-dictionary status and an explicit adoption action."""
    status = st.session_state.get("outcome_source_import_status")
    if not status:
        return
    with SectionCard(
        "Outcome dictionary review",
        description="Imported meaning is a draft until an analyst reviews and approves it.",
    ):
        source_version = status.get("schema_version") or "unknown"
        source_status = status.get("status")
        st.caption(f"Source contract: `{source_version}`")
        if source_status == OUTCOME_SOURCE_STATUS_V1_INCOMPLETE:
            st.warning(
                "This is a legacy/incomplete v1 mapping. Product, Metric, Breakdown, "
                "Segment, and Outcome group were not inferred, so no source draft was "
                "seeded. Add a v2 dictionary or review the catalogue manually."
            )
            for warning in status.get("warnings") or ():
                st.caption(warning)
            return
        if source_status == OUTCOME_SOURCE_STATUS_BLOCKED:
            st.error("The v2 dictionary could not be used to seed a draft catalogue.")
            for error in status.get("errors") or ():
                st.caption(error)
            return
        if source_status != OUTCOME_SOURCE_STATUS_V2_DRAFT:
            st.error("The Outcomes source contract is unsupported and was not adopted.")
            return

        draft_count = len(st.session_state.get("outcome_source_draft") or [])
        draft_group_count = len(
            st.session_state.get("outcome_source_draft_groups") or []
        )
        if status.get("draft_seeded"):
            st.success(
                f"Seeded {draft_count} v2 outcome definition(s) and "
                f"{draft_group_count} outcome group(s) as an unapproved draft."
            )

        comparison = status.get("comparison") or {}
        current_exists = bool(st.session_state.get("outcome_definitions") or [])
        if current_exists and not status.get("draft_seeded"):
            st.info(
                "An existing outcome catalogue was kept unchanged. Review the source "
                "comparison below before explicitly adopting it as a new draft."
            )
            rows = []
            for outcome_id in comparison.get("source_only_outcome_ids") or ():
                rows.append(
                    {"kind": "Outcome", "change": "source only", "id": outcome_id}
                )
            for outcome_id in comparison.get("current_only_outcome_ids") or ():
                rows.append(
                    {"kind": "Outcome", "change": "current only", "id": outcome_id}
                )
            for outcome_id in comparison.get("changed_outcome_ids") or ():
                rows.append({"kind": "Outcome", "change": "changed", "id": outcome_id})
            for group_id in comparison.get("source_only_group_ids") or ():
                rows.append({"kind": "Group", "change": "source only", "id": group_id})
            for group_id in comparison.get("current_only_group_ids") or ():
                rows.append({"kind": "Group", "change": "current only", "id": group_id})
            for group_id in comparison.get("changed_group_ids") or ():
                rows.append({"kind": "Group", "change": "changed", "id": group_id})
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")
            else:
                st.success("The imported v2 source matches the current catalogue.")
            if st.button(
                "Adopt imported catalogue as draft",
                key="adopt_outcome_source_draft",
                disabled=not bool(st.session_state.get("outcome_source_draft")),
            ):
                adoption = OutcomeCatalogueAdoption(
                    outcome_definitions=tuple(
                        OutcomeDefinition.from_dict(value)
                        for value in (
                            st.session_state.get("outcome_source_draft") or []
                        )
                    ),
                    outcome_groups=tuple(
                        OutcomeGroupDefinition.from_dict(value)
                        for value in (
                            st.session_state.get("outcome_source_draft_groups") or []
                        )
                    ),
                    outcome_reconciliation_groups=tuple(
                        st.session_state.get(
                            "outcome_source_draft_reconciliation_groups"
                        )
                        or []
                    ),
                )
                for key, value in adoption.to_state().items():
                    if key != "outcome_approvals":
                        set_state(key, value)
                updated_status = dict(status)
                updated_status["draft_seeded"] = True
                set_state("outcome_source_import_status", updated_status)
                clear_model_state()
                st.success(
                    "Imported outcome definitions and groups adopted as a draft. "
                    "No outcome approval was created."
                )
                st.rerun()


st.set_page_config(
    page_title="Data Sources | Ancestry Family History & DNA MMM",
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
        "Factors. Start with demo data or add your source files."
    ),
    badges=_header_badges,
)

render_workspace_note(
    "Editable setup",
    "Name the project and load governed source files here; everything below is derived from those sources.",
    kind="editable",
)

sources = st.session_state.get("raw_sources") or {}
definitions = st.session_state.get("source_definitions") or []
sources_by_domain: "dict[str | None, list]" = {}
for name, df in sources.items():
    domain = resolve_source_logical_domain(name, definitions)
    sources_by_domain.setdefault(domain, []).append((name, df))

source_inventory = summarise_source_inventory(
    sources,
    definitions,
    st.session_state.get("source_versions") or [],
    st.session_state.get("active_source_upload_version") or {},
    st.session_state.get("demo_source_pack"),
)

if sources:
    with st.container(border=True):
        st.markdown("### Source inventory")
        st.caption(
            "A workbook can contain several recognised tables. The counts below "
            "keep uploaded files, data categories, and tables separate."
        )
        inventory_cols = st.columns(5)
        inventory_cols[0].metric(
            "Uploaded files/workbooks", source_inventory.uploaded_file_count
        )
        inventory_cols[1].metric(
            "Data categories", source_inventory.data_category_count
        )
        inventory_cols[2].metric("Tables/sheets", source_inventory.table_count)
        inventory_cols[3].metric(
            "Recognised standard tables",
            source_inventory.recognised_standard_table_count,
        )
        inventory_cols[4].metric(
            "Active source versions", source_inventory.active_source_version_count
        )

with st.container(border=True):
    st.markdown("### Source readiness")
    st.caption(
        "Required source areas are shown here before file detail. Add or replace a source below."
    )
    readiness_cols = st.columns(4)
    for col, domain in zip(
        readiness_cols,
        [*REQUIRED_LOGICAL_SOURCE_DOMAINS, DOMAIN_EXPERIMENT_EVIDENCE],
    ):
        supplied = sources_by_domain.get(domain) or []
        with col:
            st.caption(_DOMAIN_LABELS[domain])
            render_status_badges(
                [
                    "ready"
                    if supplied
                    else (
                        "optional"
                        if domain == DOMAIN_EXPERIMENT_EVIDENCE
                        else "blocked"
                    )
                ]
            )
            st.caption(
                f"{len(supplied)} source(s)"
                if supplied
                else (
                    "Optional"
                    if domain == DOMAIN_EXPERIMENT_EVIDENCE
                    else "Add a source"
                )
            )

with st.container(border=True):
    st.markdown("### Download standard templates")
    st.caption(
        "Use one workbook for one data category. These files contain synthetic "
        "example rows to show the shape of the source contract; replace them with "
        "your approved source data before upload."
    )
    st.info(
        f"The Outcomes template uses `{OUTCOMES_TEMPLATE_SCHEMA_VERSION}` and "
        "keeps Product, Metric, Breakdown, Segment, Outcome group, and Source "
        "column explicit. Optional `outcome_completeness` is not included; if "
        "you add it, provide real completeness rows or remove the sheet rather "
        "than leaving it empty."
    )
    _template_downloads = (
        (DOMAIN_OUTCOMES, "Outcomes (v2)"),
        (DOMAIN_ACTIVITY_AND_MEDIA, "Activity and Media"),
        (DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS, "Context and External Factors"),
        (DOMAIN_EXPERIMENT_EVIDENCE, "Experiment Evidence"),
    )
    _template_columns = st.columns(len(_template_downloads))
    for _template_column, (_domain, _label) in zip(
        _template_columns, _template_downloads
    ):
        with _template_column:
            st.download_button(
                f"Download {_label} template",
                data=build_standard_template(_domain),
                file_name=standard_template_filename(_domain),
                mime=TEMPLATE_MIME_TYPE,
                key=f"download_standard_template_{_domain}",
                help=(
                    "Synthetic example workbook. Keep the logical domain separate "
                    "when you upload it."
                ),
            )

st.markdown("### Add or update sources")
st.session_state.setdefault("project_name", "ancestry-fh-uk")
st.session_state["project_name"] = st.text_input(
    "Project name",
    value=st.session_state["project_name"],
    help="Used to namespace the curve bank and exported project bundles for this project.",
)

tab_demo, tab_upload = st.tabs(["Demo data", "Add source"])

with tab_demo:
    st.markdown(
        "**Quick demo:** use the small rectangular weekly UK / Australia / Canada "
        "fixture for fast end-to-end exploration. It is ready for the supported "
        "Prepare Data workflow. **This is not real Ancestry data.**"
    )
    if st.button("Load demo data", type="primary"):
        frames, err = load_all_sample_sources()
        if err:
            st.error(err)
        else:
            ltv_df = frames.pop("ltv")
            st.session_state["raw_sources"] = frames
            st.session_state["demo_source_pack"] = "quick-rectangular-demo-v1"
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

    st.divider()
    st.markdown("#### Realistic source-pack demo")
    st.caption(
        "Exercises the source-input contract: tidy activity identities, dictionaries, "
        "market availability, ragged coverage, mixed weekly/monthly context, and "
        "irregular events. It remains synthetic and is intentionally not pre-joined "
        "into a model matrix; use it to review ingestion, not to run a full model."
    )
    if st.button("Load realistic source pack"):
        frames, err = load_realistic_sample_sources()
        if err:
            st.error(err)
        else:
            ltv_df = frames.pop("segment_ltv")
            st.session_state["raw_sources"] = frames
            st.session_state["sample_ltv"] = {
                row.segment: row.ltv for row in ltv_df.itertuples()
            }
            st.session_state["active_source_upload_version"] = {}
            realistic_domains = {
                "activity_data": DOMAIN_ACTIVITY_AND_MEDIA,
                "activity_dictionary": DOMAIN_ACTIVITY_AND_MEDIA,
                "outcomes": DOMAIN_OUTCOMES,
                "outcome_dictionary": DOMAIN_OUTCOMES,
                "context_data": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
                "variable_dictionary": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
                "events": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
            }
            st.session_state["source_definitions"] = [
                SourceDefinition(
                    source_id=name,
                    name=name,
                    logical_domain=domain,
                ).to_dict()
                for name, domain in realistic_domains.items()
            ]
            st.session_state["data_loaded"] = True
            st.session_state["demo_source_pack"] = "realistic-source-pack-v2"
            clear_model_state()
            st.success(
                "Loaded realistic synthetic source pack: "
                + ", ".join(
                    f"{name} ({frame.shape[0]} rows x {frame.shape[1]} cols)"
                    for name, frame in frames.items()
                )
            )

with tab_upload:
    st.caption(
        "Preferred route: add a standard workbook pack. You can add more than one "
        "workbook under a data category; each recognised table remains separate."
    )
    with st.expander("Preferred standard workbook pack", expanded=True):
        st.caption(
            f"Schema version: `{OUTCOMES_TEMPLATE_SCHEMA_VERSION}` for Outcomes; "
            "other domains keep their own standard contract. Standard "
            "Excel packs are read sheet-by-sheet; physical tables remain separate "
            "under one logical domain."
        )
        st.markdown(
            "- Outcomes: `outcomes` plus optional `outcome_dictionary`\n"
            "- Activity and Media: `activity_data` plus `activity_dictionary`\n"
            "- Context and External Factors: `context_data`, `variable_dictionary`, "
            "and optional `events`\n"
            "- Experiment Evidence: `experiment_evidence`"
        )
        st.info(
            "Use this route when the workbook matches the standard schema. Generic "
            "Excel import is a fallback for a workbook that needs separate review."
        )
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
        "Data category *",
        [_DOMAIN_PLACEHOLDER, *LOGICAL_SOURCE_DOMAINS],
        format_func=lambda d: _DOMAIN_LABELS.get(d, d),
        help=(
            "Choose the logical domain for this source. Outcomes, Activity and "
            "Media, and Context and "
            "External Factors are required for a complete project; "
            "Experiment Evidence is optional."
        ),
    )
    uploaded = st.file_uploader(
        "Choose a CSV, Excel, or Parquet file *",
        type=["csv", "xlsx", "xls", "xlsm", "parquet"],
        key="uploader",
    )

    add_standard_source = st.button("Add source", type="primary")
    add_generic_excel = st.button(
        "Add as generic Excel fallback",
        disabled=uploaded is None or not _is_excel_filename(uploaded.name),
        help=(
            "Use only when the workbook is not a standard source pack. The first "
            "sheet is loaded as the generic source and every workbook sheet is "
            "recorded in provenance."
        ),
    )

    if uploaded is not None and (add_standard_source or add_generic_excel):
        if not source_name.strip():
            st.error("Source name is required.")
        elif logical_domain_choice == _DOMAIN_PLACEHOLDER:
            st.error("Choose a logical source domain before adding this source.")
        else:
            existing_versions = [
                SourceVersion.from_dict(v)
                for v in st.session_state.get("source_versions") or []
            ]
            if _is_excel_filename(uploaded.name):
                workbook, source_version, err = (
                    load_standard_workbook_with_source_version(
                        uploaded,
                        source_name,
                        logical_domain_choice,
                        existing_versions,
                    )
                )
                if err:
                    st.error(err)
                elif workbook is None or source_version is None:
                    st.error("The workbook could not be loaded.")
                elif (
                    add_standard_source
                    and not workbook.manifest.valid_standard_template
                ):
                    st.error(
                        "Standard workbook validation failed; source not accepted."
                    )
                    for message in workbook.manifest.errors:
                        st.error(message)
                    for message in workbook.manifest.warnings:
                        st.warning(message)
                    st.info(
                        "Correct the standard workbook, or choose 'Add as generic "
                        "Excel fallback' to import only its first sheet."
                    )
                elif add_standard_source and logical_domain_choice == DOMAIN_OUTCOMES:
                    try:
                        canonical_outcome_bundle = canonicalize_standard_workbook(
                            workbook
                        )
                    except ValueError as exc:
                        set_state("outcome_source_draft", None)
                        set_state("outcome_source_draft_groups", [])
                        set_state("outcome_source_draft_reconciliation_groups", [])
                        set_state(
                            "outcome_source_import_status",
                            {
                                "schema_version": workbook.manifest.template_schema_version,
                                "status": OUTCOME_SOURCE_STATUS_BLOCKED,
                                "errors": [str(exc)],
                                "warnings": list(workbook.manifest.warnings),
                            },
                        )
                        st.error(
                            "The Outcomes workbook passed sheet checks but its "
                            f"dictionary could not be interpreted: {exc}"
                        )
                    else:
                        stored = _store_standard_workbook(
                            source_name,
                            workbook,
                            source_version,
                            logical_domain_choice,
                        )
                        st.session_state["source_versions"] = [
                            v.to_dict() for v in existing_versions
                        ] + [source_version.to_dict()]
                        st.session_state["data_loaded"] = True
                        st.session_state["demo_source_pack"] = None
                        _record_outcome_source_import(
                            workbook, canonical_outcome_bundle
                        )
                        clear_model_state()
                        for message in workbook.manifest.warnings:
                            st.warning(message)
                        st.success(
                            f"Loaded standard workbook {uploaded.name} as {len(stored)} "
                            f"separate table(s) under '{_DOMAIN_LABELS[logical_domain_choice]}' "
                            f"(v{source_version.version})."
                        )
                else:
                    if (
                        add_generic_excel
                        or not workbook.manifest.valid_standard_template
                    ):
                        if not workbook.tables:
                            st.error("The workbook contains no readable sheets.")
                        else:
                            first_sheet = next(iter(workbook.tables))
                            _remove_source_lineage(source_name)
                            sources = dict(st.session_state.get("raw_sources") or {})
                            sources[source_name] = workbook.tables[first_sheet]
                            st.session_state["raw_sources"] = sources
                            definitions = list(
                                st.session_state.get("source_definitions") or []
                            )
                            definitions.append(
                                SourceDefinition(
                                    source_id=source_name,
                                    name=source_name,
                                    logical_domain=logical_domain_choice,
                                ).to_dict()
                            )
                            st.session_state["source_definitions"] = definitions
                            active = dict(
                                st.session_state.get("active_source_upload_version")
                                or {}
                            )
                            active[source_name] = source_version.version
                            st.session_state["active_source_upload_version"] = active
                            st.session_state["source_versions"] = [
                                v.to_dict() for v in existing_versions
                            ] + [source_version.to_dict()]
                            st.session_state["data_loaded"] = True
                            st.session_state["demo_source_pack"] = None
                            clear_model_state()
                            st.warning(
                                "Generic Excel import loaded only the first sheet "
                                f"({first_sheet!r}); workbook sheets were not combined. "
                                + " ".join(
                                    [
                                        *workbook.manifest.warnings,
                                        *workbook.manifest.errors,
                                    ]
                                )
                            )
                            st.success(
                                f"Loaded {sources[source_name].shape[0]} rows from "
                                f"{uploaded.name} as generic source '{source_name}' "
                                f"(v{source_version.version})."
                            )
                    else:
                        stored = _store_standard_workbook(
                            source_name,
                            workbook,
                            source_version,
                            logical_domain_choice,
                        )
                        st.session_state["source_versions"] = [
                            v.to_dict() for v in existing_versions
                        ] + [source_version.to_dict()]
                        st.session_state["data_loaded"] = True
                        st.session_state["demo_source_pack"] = None
                        clear_model_state()
                        for message in workbook.manifest.warnings:
                            st.warning(message)
                        st.success(
                            f"Loaded standard workbook {uploaded.name} as {len(stored)} "
                            f"separate table(s) under '{_DOMAIN_LABELS[logical_domain_choice]}' "
                            f"(v{source_version.version})."
                        )
            else:
                df, source_version, err = load_file_with_source_version(
                    uploaded, source_name, existing_versions
                )
                if err:
                    st.error(err)
                else:
                    _remove_source_lineage(source_name)
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
                    st.session_state["source_definitions"] = [
                        *(st.session_state.get("source_definitions") or []),
                        SourceDefinition(
                            source_id=source_name,
                            name=source_name,
                            logical_domain=logical_domain_choice,
                        ).to_dict(),
                    ]
                    st.session_state["data_loaded"] = True
                    st.session_state["demo_source_pack"] = None
                    clear_model_state()
                    st.success(
                        f"Loaded {df.shape[0]} rows from {uploaded.name} as source "
                        f"'{source_name}' (version {source_version.version})."
                    )


_render_outcome_source_review()


def _render_source_detail(name: str, df) -> None:
    """One physical source's expander: version/provenance, logical domain,
    row/column summary and preview - identical content regardless of which
    domain group it's rendered under, so several physical files can share
    one logical domain's card without duplicating this logic per domain."""
    table_name = source_table_name(name)
    title = (
        f"**{table_name}** - {df.shape[0]} rows x {df.shape[1]} columns"
        if table_name != name
        else f"**{name}** - {df.shape[0]} rows x {df.shape[1]} columns"
    )
    with st.expander(title, expanded=False):
        # Look up the *specific* version that actually produced this name's
        # current frame (never "the latest history entry for this name" - a
        # prior real upload's provenance must not be displayed against a
        # frame that isn't actually that upload, e.g. after loading demo
        # data under a reused name).
        active_version = (
            st.session_state.get("active_source_upload_version") or {}
        ).get(name)
        workbook_source_id = source_lineage_id(name)
        active_record = next(
            (
                v
                for v in st.session_state.get("source_versions") or []
                if v.get("source_id") == workbook_source_id
                and v.get("version") == active_version
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
            if active_record.get("standard_template"):
                st.caption(
                    "Standard workbook schema "
                    f"`{active_record.get('template_schema_version')}`; "
                    f"tables: {', '.join(active_record.get('parsed_table_ids') or ())}"
                )
            for message in active_record.get("template_warnings") or ():
                st.warning(message)
        # REQ-DATAIN-001: a source with no recorded SourceDefinition (e.g. a
        # bundle imported from before this capability existed) reads as
        # "Unclassified", never a guessed domain.
        domain = resolve_source_logical_domain(
            name, st.session_state.get("source_definitions") or []
        )
        st.caption(
            f"Data category: **"
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
            st.session_state["source_definitions"] = [
                definition
                for definition in (st.session_state.get("source_definitions") or [])
                if definition.get("source_id") != name
            ]
            st.rerun()


if sources:
    st.markdown("## Data by category")
    st.caption(
        "A data category is not a physical file. Any number of uploaded files or "
        "workbooks can belong to one category, and a workbook can contain several "
        "tables. Each stored table remains separate and belongs to one governed "
        "category."
    )

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
                    f"{len(supplied)} table(s) supplied under this category. "
                    "See Source inventory above for uploaded file/workbook count."
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
                f"{len(optional_supplied)} table(s) supplied under this category."
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
            "plus the optional Experiment Evidence domain."
        ),
        next_action="Load the demo data, or upload a file and choose its logical domain above.",
    )
