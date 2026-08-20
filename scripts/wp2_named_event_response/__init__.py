"""Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps Post PR #297`):
standalone synthetic-DGP evaluation of candidate named-event response
encodings. Decision support only.

This directory is deliberately outside the `ancestry_mmm` package:

- nothing in `ancestry_mmm/**` imports it (enforced by
  `ancestry_mmm/tests/test_wp2_named_event_response_evidence.py`);
- it fits small synthetic PyMC models with the repository's pinned
  stack (PyMC 5.28.5 / PyTensor 2.38.3 / ArviZ 0.23.4) and records
  results - it never touches production model builders, and no result
  here approves any statistical response method.

`run_evaluation.py` is the single entry point:
  uv run python scripts/wp2_named_event_response/run_evaluation.py --out <dir>

It is executed by the schedule/manual-only CI job
`named-event-response-recovery` in `.github/workflows/tests.yml`; real
NUTS sampling is too slow for blocking PR/push CI (same policy as
`candidate-a-recovery` and `fold-refit-recovery`).
"""
