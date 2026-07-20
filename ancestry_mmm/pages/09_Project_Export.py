"""Page 9: project export/import bundle (Parquet + JSON + NetCDF) and Excel export for handover."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, curve_bank_dir, PROJECT_EXPORT_ROOT
from ancestry_mmm.core.persistence import export_project, import_project, export_excel_summary, UnsafeZipEntryError
from ancestry_mmm.core.curve_bank import load_all_entries, entries_to_dataframe
from ancestry_mmm.core.attribution import compute_shapley_contributions, total_fh_contribution, segment_channel_summary
from ancestry_mmm.core.schema import ModelSpec

st.set_page_config(page_title="Project Export - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("💾 Project Export & Handover")
st.caption(
    "Streamlit session state is never the system of record - it only drives in-session "
    "interactivity. This bundle (Parquet + JSON + NetCDF, all open formats) is what an analyst "
    "actually keeps: pause here, resume later, hand it off, or replay the same pipeline on "
    "refreshed weekly data."
)

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
        )
    st.success(f"Bundle written to {output_path}")
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
        # Always overwrite (not just when present) so a stale approval from
        # the current session's in-progress model doesn't linger attached to
        # whatever gets imported.
        set_state("model_approval", imported["model_approval"])
        if imported["trace"] is not None:
            set_state("trace", imported["trace"])
            st.info("Imported a fitted trace. Re-run Model Training's setup (without re-fitting) if you need model_meta/posterior_params - or just re-fit to refresh.")
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
st.markdown("### Roadmap: what's beyond this build")
st.markdown("""
This is the Phase 1 core plus the scenario planner (Phase 2) and this basic persistence layer
(Phase 3), per the requirements brief's own phasing. Deliberately **not** built yet:

- **PowerPoint export** - Excel + the project bundle cover handover today; a slide export is a
  templating exercise on top of the same summary tables, not a modelling change.
- **Australia / Canada as fully separate market builds** - the geo hierarchy (partial pooling,
  per-market unpooled override) is implemented and exercised by the synthetic demo's 3 markets,
  but real cross-market synthesis needs real AU/CA data to mean anything.
- **Live geo-test / in-platform-test feed into the curve bank** - the comparison-and-agreement
  workflow exists (Results & Curve Bank page), but nothing pulls test results in automatically.
- **Stage 2 media x context interactions** - explicitly out of scope for the core model per the brief.
""")
