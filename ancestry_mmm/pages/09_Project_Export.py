"""Page 9: project export/import bundle (Parquet + JSON + NetCDF) and Excel export for handover."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, curve_bank_dir, PROJECT_EXPORT_ROOT
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    export_excel_summary,
    reconstruct_model_state,
    verify_imported_approval,
    UnsafeZipEntryError,
)
from ancestry_mmm.core.curve_bank import load_all_entries, entries_to_dataframe
from ancestry_mmm.core.attribution import compute_shapley_contributions, total_fh_contribution, segment_channel_summary
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.report import build_report_sections, render_markdown, render_html

st.set_page_config(page_title="Project Export - Ancestry FH MMM", page_icon="🧬", layout="wide")
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
        )
    st.success(f"Project bundle built: {output_path}")
    with open(output_path, "rb") as f:
        st.download_button("Download project bundle (.zip)", f, file_name=f"{project_name}.zip", mime="application/zip")

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
        set_state("transformed_data", imported["transformed_data"])
        set_state("pipeline_steps", imported["pipeline_steps"])
        set_state("model_spec", imported["model_spec"])
        set_state("prior_config", imported["prior_config"])
        set_state("dna_lag_weeks", imported["dna_lag_weeks"])
        set_state("scenarios", imported["scenarios"])
        set_state("data_loaded", bool(imported["raw_sources"]))
        set_state("trace", imported["trace"])
        set_state("model_run_id", imported["model_run_id"])
        set_state("market_spec_config", imported["market_spec_config"])
        if imported["market_spec_config"] is None:
            st.caption(
                "This bundle predates the market-specific redesign - no market descriptors or "
                "media-unit mappings to import. Add them on Channel & Media Units / Market "
                "Descriptors if needed."
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

        verified_approval, message = verify_imported_approval(imported, reconstructed)
        set_state("model_approval", verified_approval.to_dict() if verified_approval else None)
        (st.success if verified_approval else st.warning)(message)

        if imported["trace"] is not None and reconstructed["frame"] is None:
            st.info(
                "Imported a fitted trace, but couldn't reconstruct the modelling frame (missing "
                "or inconsistent transformed data / model spec) - re-run Model Configuration's "
                "\"Prepare modelling frame\" step, or re-fit, to continue."
            )
        st.success("Project imported. Review each page to pick up where you left off.")
    finally:
        tmp_path.unlink(missing_ok=True)

st.markdown("---")
st.markdown("### Excel export (curve bank + contributions)")
if get_state("trace") is not None and get_state("model_spec"):
    if st.button("Build Excel summary"):
        meta = get_state("model_meta")
        params = get_state("posterior_params")
        frame = get_state("frame")
        spec = ModelSpec.from_dict(get_state("model_spec"))
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=100)
        total_df = total_fh_contribution(frame, meta, params, contributions, spec.segment_ltv)
        seg_df = segment_channel_summary(frame, meta, params, contributions, spec.segment_ltv)
        entries = load_all_entries(curve_bank_dir())
        entries_df = entries_to_dataframe(entries) if entries else None

        PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
        excel_path = PROJECT_EXPORT_ROOT / f"{project_name}_summary.xlsx"
        export_excel_summary(excel_path, entries_df, total_df, seg_df)
        with open(excel_path, "rb") as f:
            st.download_button("Download Excel summary (.xlsx)", f, file_name=excel_path.name,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
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
    )

    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    md_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.md"
    html_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.html"
    md_path.write_text(render_markdown(project_name, sections))
    html_path.write_text(render_html(project_name, sections))
    st.success("Report built.")
    c1, c2 = st.columns(2)
    with open(md_path, "rb") as f:
        c1.download_button("Download report (.md)", f, file_name=md_path.name, mime="text/markdown")
    with open(html_path, "rb") as f:
        c2.download_button("Download report (.html)", f, file_name=html_path.name, mime="text/html")

st.markdown("---")
st.markdown("### What's out of scope")
st.markdown("""
Per `docs/project_objectives.md` and `docs/limitations.md`, deliberately **not** built:

- **Shapley attribution for market-specific models** - it's built around a single shared curve per
  channel and would misread Model C's market-indexed parameters.
- **CPA/inflation as first-class optimiser objectives** - "minimise CPA," "maintain response/delivery
  under inflation" from the original redesign brief; `avg_cpa` is reported as an output metric, not
  an optimisation target.
- **Media-unit spend constraints** (locked/min/max media units) - `SpendConstraint` still operates in
  spend terms only.
- **PowerPoint export** - Excel + the project bundle + this report cover handover today.
- **Automating currency conversion** - the tool stores exchange-rate context but never silently
  converts or applies an inflation assumption without it being visible in the UI.
- **Stage 2 media x context interactions** - explicitly out of scope for the core model per the brief.
""")

st.markdown("---")
st.caption("This is the last step in the workflow. Revisit any page from the sidebar to refine the model or plans.")
