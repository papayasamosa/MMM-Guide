# Archived stacks

These two codebases are archived, not deleted — kept for reference and git history.
`ancestry_mmm/` (repo root) is the actively developed application.

## `archive/dashboard/`

The generic single-KPI "MMM Studio" Streamlit app that `ancestry_mmm/` was forked from
and re-scoped around Ancestry's actual FH New / DNA Cross-sell / Winback problem. Runs,
but its Results, Budget Optimization and Scenario Planning pages present numbers that are
partly fabricated (hardcoded R²/MAPE/LOO, a random-data decomposition chart, a fixed
0.3 "media share" constant) rather than computed from the fitted model, and its
"Lift-Factor" model declares adstock decay priors it never applies. See the Phase 0 audit
for the full list of issues before reusing any of this code.

## `archive/backend/` and `archive/frontend/`

"MMMpact" — a separate FastAPI + Next.js no-code web app. As committed, it does not run:
`archive/backend/main.py` imports `backend.core`, a package that was never added to the
repository (confirmed absent from git history), and three of the seven frontend pages
import API client functions that don't exist in `frontend/src/lib/api.ts`. Fixing it would
mean writing `backend/core/` from scratch (the import list closely mirrors
`archive/dashboard/core/__init__.py`'s exports, suggesting that was the original intent)
and reconciling the frontend's API surface with whatever gets written.
