"""Page 9: project export/import bundle (Parquet + JSON + NetCDF) and Excel export for handover."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    PROJECT_EXPORT_ROOT,
    curve_bank_dir,
    get_state,
    get_workflow_progress,
    init_session_state,
    set_state,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_drift_status,
)
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    export_excel_summary,
    reconstruct_model_state,
    verify_imported_approval,
    UnsafeZipEntryError,
    audit_project_resumability,
)
from ancestry_mmm.core.curve_bank import load_all_entries, entries_to_dataframe
from ancestry_mmm.core.attribution import (
    compute_shapley_contributions,
    total_fh_contribution,
    outcome_channel_summary,
)
from ancestry_mmm.core.market_specific_attribution import (
    compute_shapley_contributions_market_specific,
    total_contribution_market_specific,
    outcome_channel_market_summary,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.evidence_tiers import evidence_tiers_dataframe
from ancestry_mmm.core.media_units import market_specific_cpa_table
from ancestry_mmm.core.outcomes import fh_gsa_outcome_ids, resolve_outcome_definitions
from ancestry_mmm.core.pathways import MediaOutcomePathway, pathways_drift_dataframe
from ancestry_mmm.core.optimization import compare_scenarios
from ancestry_mmm.core.report import build_report_sections, render_markdown, render_html
from ancestry_mmm.core.promotions import PROMOTION_EVENT_OP
from ancestry_mmm.data import apply_pipeline, pipeline_from_json

st.set_page_config(
    page_title="Project Export - Ancestry FH MMM", page_icon="🧬", layout="wide"
)
init_session_state()
apply_theme()
render_sidebar("export")
render_page_header("export")
st.caption(
    "Streamlit session state is never the system of record - it only drives in-session "
    "interactivity. This bundle (Parquet + JSON + NetCDF, all open formats) is what an analyst "
    "actually keeps: pause here, resume later, hand it off, or replay the same pipeline on "
    "refreshed weekly data."
)

st.markdown("---")
st.markdown("### Export project bundle")
project_name = get_state("project_name", "ancestry-fh-uk")
project_notes = st.text_area(
    "Analyst project notes",
    value=get_state("project_notes", ""),
    help="Saved in the resumable bundle as notes.md.",
)
set_state("project_notes", project_notes)
if st.button("Build export bundle", type="primary"):
    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = PROJECT_EXPORT_ROOT / f"{project_name}.zip"
    with st.spinner("Building bundle..."):
        export_project(
            output_path,
            raw_sources=get_state("raw_sources") or {},
            transformed_data=get_state("transformed_data"),
            pipeline_steps=get_state("pipeline_steps") or [],
            model_spec=get_state("model_spec"),
            prior_config=get_state("prior_config"),
            dna_lag_weeks=get_state("dna_lag_weeks", 4),
            trace=get_state("trace"),
            scenarios=get_state("scenarios") or [],
            curve_bank_source_dir=curve_bank_dir(),
            model_approval=get_state("model_approval"),
            model_run_id=get_state("model_run_id"),
            model_meta=get_state("model_meta"),
            market_spec_config=get_state("market_spec_config"),
            model_type=get_state("model_type", "shared"),
            outcome_definitions=get_state("outcome_definitions"),
            funnel_links=get_state("funnel_links"),
            media_outcome_pathways=get_state("media_outcome_pathways"),
            net_billthrough_metadata=get_state("net_billthrough_metadata"),
            workflow_state={
                "checkpoint": (
                    "scenarios"
                    if get_state("scenarios")
                    else "curves"
                    if get_state("curve_bank_entry_id")
                    else "approved"
                    if get_state("model_approval")
                    else "fitted"
                    if get_state("trace") is not None
                    else "pre_fit"
                    if get_state("model_spec")
                    else "uploaded"
                ),
                "current_page": get_state("current_page", 0),
                "workflow_progress": get_workflow_progress(),
                "active_scenario": get_state("active_scenario"),
            },
            diagnostics={
                "scorecard": get_state("scorecard"),
                "backtest_results": get_state("backtest_results"),
            },
            notes=get_state("project_notes"),
            calibration_records=get_state("calibration_records") or [],
            model_comparison_candidates=get_state("model_comparison_candidates") or [],
            migration_review=get_state("migration_review"),
            media_input_specs=get_state("media_input_specs") or [],
            media_cost_mappings=get_state("media_cost_mappings"),
            media_input_support=get_state("media_input_support") or [],
            monetary_spend_support=get_state("monetary_spend_support") or [],
        )
    st.success(f"Project bundle built: {output_path}")
    with open(output_path, "rb") as f:
        st.download_button(
            "Download project bundle (.zip)",
            f,
            file_name=f"{project_name}.zip",
            mime="application/zip",
        )

st.markdown("---")
st.markdown("### Import project bundle")
uploaded_zip = st.file_uploader("Upload a previously exported .zip", type=["zip"])
if uploaded_zip is not None and st.button("Import bundle"):
    tmp_path = PROJECT_EXPORT_ROOT / f"_import_{uploaded_zip.name}"
    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(uploaded_zip.getbuffer())
    try:
        with st.spinner("Importing..."):
            imported = import_project(tmp_path)
    except UnsafeZipEntryError as e:
        st.error(f"Refusing to import this bundle: {e}")
    else:
        set_state("raw_sources", imported["raw_sources"])

        # Replay promotion-event pipeline steps fresh against the imported
        # data rather than trusting the derived promo columns already
        # sitting in the imported parquet (PR E.2 #11 - "re-importing a
        # project must reproduce the same derived columns from raw data").
        # Any pre-existing derived column for a segment with a
        # promotion_event step is dropped first, so the regenerated value
        # is computed purely from the versioned event list, not layered on
        # top of a stale one.
        transformed = imported["transformed_data"]
        promo_steps = [
            s
            for s in pipeline_from_json(imported["pipeline_steps"] or [])
            if s.op == PROMOTION_EVENT_OP
        ]
        if transformed is not None and promo_steps:
            promo_columns = {
                f"{s.params.get('column_prefix', '_promo_event_')}{s.params['event']['segment']}"
                for s in promo_steps
            }
            transformed = transformed.drop(
                columns=[c for c in promo_columns if c in transformed.columns]
            )
            transformed = apply_pipeline(transformed, promo_steps)
        set_state("transformed_data", transformed)
        set_state("pipeline_steps", imported["pipeline_steps"])
        set_state("model_spec", imported["model_spec"])
        set_state("prior_config", imported["prior_config"])
        set_state("dna_lag_weeks", imported["dna_lag_weeks"])
        set_state("scenarios", imported["scenarios"])
        set_state("data_loaded", bool(imported["raw_sources"]))
        set_state("trace", imported["trace"])
        set_state("model_run_id", imported["model_run_id"])
        set_state("market_spec_config", imported["market_spec_config"])
        set_state("media_input_specs", imported.get("media_input_specs") or [])
        set_state("media_cost_mappings", imported.get("media_cost_mappings"))
        set_state("media_input_support", imported.get("media_input_support") or [])
        set_state(
            "monetary_spend_support",
            imported.get("monetary_spend_support") or [],
        )
        set_state("model_type", imported["model_type"])
        set_state("outcome_definitions", imported["outcome_definitions"])
        set_state("funnel_links", imported["funnel_links"])
        set_state("media_outcome_pathways", imported["media_outcome_pathways"])
        set_state("net_billthrough_metadata", imported["net_billthrough_metadata"])
        set_state("migration_review", imported.get("migration_review"))
        workflow_state = imported.get("workflow_state") or {}
        set_state("current_page", workflow_state.get("current_page", 0))
        set_state("active_scenario", workflow_state.get("active_scenario"))
        set_state("project_notes", imported.get("notes") or "")
        set_state("calibration_records", imported.get("calibration_records") or [])
        set_state(
            "model_comparison_candidates",
            imported.get("model_comparison_candidates") or [],
        )
        imported_diagnostics = imported.get("diagnostics") or {}
        set_state("scorecard", imported_diagnostics.get("scorecard"))
        set_state("backtest_results", imported_diagnostics.get("backtest_results"))
        if imported.get("curve_bank_files") or imported.get(
            "curve_bank_binary_files"
        ):
            restored_curve_dir = curve_bank_dir()
            restored_curve_dir.mkdir(parents=True, exist_ok=True)
            for filename, contents in imported["curve_bank_files"].items():
                target = restored_curve_dir / Path(filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents)
            for filename, contents in imported.get(
                "curve_bank_binary_files", {}
            ).items():
                target = restored_curve_dir / Path(filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
            set_state(
                "curve_bank_entry_id",
                Path(
                    next(
                        iter(
                            imported["curve_bank_files"]
                            or imported.get("curve_bank_binary_files", {})
                        )
                    )
                ).stem,
            )
        if imported["market_spec_config"] is None:
            st.caption(
                "This bundle predates the market-specific redesign - no market descriptors or "
                "media-unit mappings to import. Add them on Channel & Media Units / Market "
                "Descriptors if needed."
            )
        if imported["outcome_definitions"] is None:
            st.caption(
                "This bundle predates the outcome-schema work - no DNA outcome mappings to "
                "import. The Family History outcome catalogue is still derived automatically "
                "from this project's structure; add DNA outcomes on Structure: Segments & "
                "Markets if needed."
            )

        # Re-derive the frame and posterior params from the raw artefacts
        # (cheap - pandas prep + posterior summarisation, no re-fit) so the
        # imported approval can be verified against them rather than blindly
        # trusted or blindly discarded.
        reconstructed = reconstruct_model_state(imported)
        set_state("frame", reconstructed["frame"])
        set_state("model_meta", reconstructed["model_meta"])
        set_state("posterior_params", reconstructed["posterior_params"])
        set_state("model_trained", reconstructed["posterior_params"] is not None)
        resume_audit = audit_project_resumability(imported)
        if resume_audit["resumable"]:
            st.success(
                f"Resumability audit passed at checkpoint "
                f"'{resume_audit['checkpoint']}'."
            )
        else:
            st.warning(
                "Bundle imported, but its declared checkpoint is incomplete: "
                + ", ".join(resume_audit["missing_required"])
            )
        for audit_warning in resume_audit["warnings"]:
            st.caption(audit_warning)

        verified_approval, message = verify_imported_approval(imported, reconstructed)
        set_state(
            "model_approval", verified_approval.to_dict() if verified_approval else None
        )
        (st.success if verified_approval else st.warning)(message)

        if imported["trace"] is not None and reconstructed["frame"] is None:
            st.info(
                "Imported a fitted trace, but couldn't reconstruct the modelling frame (missing "
                "or inconsistent transformed data / model spec) - re-run Model Configuration's "
                '"Prepare modelling frame" step, or re-fit, to continue.'
            )
        st.success("Project imported. Review each page to pick up where you left off.")
    finally:
        tmp_path.unlink(missing_ok=True)

st.markdown("---")
st.markdown("### Excel export")
model_type_for_export = get_state("model_type", "shared")
if get_state("trace") is not None and get_state("model_spec"):
    _export_spec = ModelSpec.from_dict(get_state("model_spec"))
    render_drift_status(
        resolve_outcome_definitions(
            get_state("outcome_definitions"),
            _export_spec.segment_outcomes,
            _export_spec.segment_ltv,
        ),
        get_state("model_meta"),
    )
    _current_pathways = [
        MediaOutcomePathway.from_dict(p)
        for p in (get_state("media_outcome_pathways") or [])
    ]
    _pathway_drift_df = pathways_drift_dataframe(
        _current_pathways, get_state("model_meta")
    )
    if not _pathway_drift_df.empty:
        _changed_pathways = _pathway_drift_df[
            _pathway_drift_df["drift_status"] != "Fitted and current"
        ]
        if not _changed_pathways.empty:
            st.info(
                f"{len(_changed_pathways)} media-outcome pathway(s) differ from this fit's captured "
                "pathway metadata (informational only - the pathway catalogue does not yet drive "
                "fitting; PR F)."
            )
    if model_type_for_export == "shared":
        st.caption(
            "Curve bank, total-FH contribution and segment x channel Shapley attribution (Model A)."
        )
    else:
        st.caption(
            "Curve bank, evidence tiers, a CPA table per market/channel, market-aware Shapley "
            "attribution (total and market x segment x channel detail, computed with each market's "
            "own beta/hill_K), diagnostics and approval metadata, and the scenario comparison."
        )
    if st.button("Build Excel summary"):
        meta = get_state("model_meta")
        params = get_state("posterior_params")
        frame = get_state("frame")
        trace = get_state("trace")
        spec = ModelSpec.from_dict(get_state("model_spec"))
        entries = load_all_entries(curve_bank_dir())
        entries_df = entries_to_dataframe(entries) if entries else None

        if model_type_for_export == "shared":
            contributions = compute_shapley_contributions(
                frame, meta, params, n_permutations=100
            )
            total_df = total_fh_contribution(
                frame,
                meta,
                params,
                contributions,
                spec.segment_ltv,
                outcome_ids=fh_gsa_outcome_ids(meta),
            )
            seg_df = outcome_channel_summary(
                frame, meta, params, contributions, spec.segment_ltv
            )
            sheets = {
                "Total FH Contribution": total_df,
                "Segment x Channel": seg_df,
                "Curve Bank": entries_df,
            }
        else:
            scorecard = get_state("scorecard") or {}
            diagnostics_df = pd.DataFrame(scorecard.get("in_sample_fit") or [])
            approval_dict = get_state("model_approval")
            approval_df = pd.DataFrame([approval_dict]) if approval_dict else None
            scenarios = get_state("scenarios") or []
            scenarios_df = compare_scenarios(scenarios) if scenarios else None
            ms_contributions = compute_shapley_contributions_market_specific(
                frame, meta, params, n_permutations=100
            )
            ms_total_df = total_contribution_market_specific(
                frame,
                meta,
                params,
                ms_contributions,
                spec.segment_ltv,
                outcome_ids=fh_gsa_outcome_ids(meta),
                by_market=True,
            )
            ms_seg_df = outcome_channel_market_summary(
                frame, meta, params, ms_contributions, spec.segment_ltv
            )
            sheets = {
                "Curve Bank": entries_df,
                "Evidence Tiers": evidence_tiers_dataframe(trace, frame, meta),
                "CPA": market_specific_cpa_table(meta, params),
                "Total Contribution": ms_total_df,
                "Market x Segment x Channel": ms_seg_df,
                "Diagnostics": diagnostics_df,
                "Approval": approval_df,
                "Scenarios": scenarios_df,
            }

        PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
        excel_path = PROJECT_EXPORT_ROOT / f"{project_name}_summary.xlsx"
        export_excel_summary(excel_path, sheets)
        with open(excel_path, "rb") as f:
            st.download_button(
                "Download Excel summary (.xlsx)",
                f,
                file_name=excel_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
else:
    st.info("Train a model first to build an Excel summary.")

st.markdown("---")
st.markdown("### Project report")
st.caption(
    "A single reproducible document - objective, data, model, diagnostics, curve bank, scenarios, "
    "known limitations, and a pointer to the decision log - built from this project's actual current "
    "state, not a static template. Available at any point in the workflow; sections say plainly what "
    "hasn't happened yet rather than being left out."
)
if st.button("Build project report"):
    spec_dict = get_state("model_spec")
    spec = ModelSpec.from_dict(spec_dict) if spec_dict else None
    frame = get_state("frame")
    data_window = None
    if frame is not None and frame.get("dates") is not None and len(frame["dates"]):
        data_window = (
            str(pd.Timestamp(frame["dates"].min()).date()),
            str(pd.Timestamp(frame["dates"].max()).date()),
        )
    approval_dict = get_state("model_approval")
    approval = ModelApproval.from_dict(approval_dict) if approval_dict else None
    entries = load_all_entries(curve_bank_dir())
    market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))

    sections = build_report_sections(
        spec=spec,
        model_type=get_state("model_type", "shared"),
        pipeline_steps=get_state("pipeline_steps") or [],
        data_window=data_window,
        dna_lag_weeks=get_state("dna_lag_weeks", 4),
        scorecard=get_state("scorecard"),
        approval=approval,
        curve_bank_entries=entries,
        scenarios=get_state("scenarios") or [],
        market_spec_config=market_config,
        outcome_definitions=get_state("outcome_definitions"),
    )

    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    md_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.md"
    html_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.html"
    md_path.write_text(render_markdown(project_name, sections))
    html_path.write_text(render_html(project_name, sections))
    st.success("Report built.")
    c1, c2 = st.columns(2)
    with open(md_path, "rb") as f:
        c1.download_button(
            "Download report (.md)", f, file_name=md_path.name, mime="text/markdown"
        )
    with open(html_path, "rb") as f:
        c2.download_button(
            "Download report (.html)", f, file_name=html_path.name, mime="text/html"
        )

st.markdown("---")
st.markdown("### What's out of scope")
st.markdown("""
Per `docs/project_objectives.md` and `docs/limitations.md`, deliberately **not** built:

- **CPA/inflation as first-class optimiser objectives** - "minimise CPA," "maintain response/delivery
  under inflation" from the original redesign brief; `avg_cpa`/`dna_avg_cpa` are reported as output
  metrics, not optimisation targets themselves. What *is* built: explicit, product-aware optimisation
  objectives (maximise FH GSAs, DNA kits, or LTV-weighted expected value) that never silently combine
  Family History GSAs and DNA kit sales into one "volume" number.
- **Media-unit spend constraints** (locked/min/max media units) - `SpendConstraint` still operates in
  spend terms only.
- **PowerPoint export** - Excel + the project bundle + this report cover handover today.
- **Automating currency conversion** - the tool stores exchange-rate context but never silently
  converts or applies an inflation assumption without it being visible in the UI.
- **Stage 2 media x context interactions** - explicitly out of scope for the core model per the brief.
""")

st.markdown("---")
st.caption(
    "This is the last step in the workflow. Revisit any page from the sidebar to refine the model or plans."
)
