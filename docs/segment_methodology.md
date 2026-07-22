# Segment Methodology

## The three segments

Fixed by `core.schema.DEFAULT_SEGMENTS`, though the underlying outcome column each maps to is
user-configured on the Structure page:

- **New** - first-time subscribers with no prior Ancestry relationship. Most media-responsive
  segment.
- **DNA cross-sell (`DNA_CrossSell`)** - a high-value path driven heavily by DNA-targeted media,
  plus a halo effect from that same media onto the other two segments.
- **Winback** - lapsed subscribers; lower media sensitivity, stronger promotional response.

These are modelled **jointly**, not as three separate single-KPI models, so response strength,
promotional sensitivity, and the DNA halo pathway are all estimated with partial pooling across
segments: segments borrow strength from each other where data is thin, and diverge where the data
supports it (`core/hierarchical_model.py`).

Since PR E, `segment` is a descriptive grouping only - the model's actual fitting identity is
`outcome_id` (`docs/outcomes.md`). A segment can carry more than one independently-fitted outcome
(e.g. a "New" sign-up KPI and a "New" GSA KPI both with `segment="New"` but distinct `outcome_id`s),
so every `beta`/`halo_strength` reference below is really indexed by `outcome_id`, not by segment
name.

## The DNA halo pathway

DNA-targeted channels (`ModelSpec.dna_channels`) get an explicit halo term: their effect on the DNA
cross-sell segment is fixed at full weight (1.0), and their effect on the other two segments is a
separate, partially-pooled parameter (`halo_strength[outcome]`, PyMC coord `"outcome"`), shrunk
toward zero by default and
only pulled away from zero where the data supports it, with an additional decision-time lag
(`dna_lag_weeks`) beyond normal adstock carryover. This is deliberately explicit rather than folded
into the channel's regular coefficient, so the halo effect is visible and auditable on its own
(Results & Curve Bank page, "DNA halo strength by segment").

## Segment response today vs. under the market-specific redesign

| | Today | Phase 2+ |
|---|---|---|
| Response strength | `beta[outcome, channel]` - varies by outcome, shared across markets | `beta[market, outcome, channel]` - varies by both |
| Saturation (`K`), decay, shape (`S`) | Shared across outcomes *and* markets | Market-specific (`K`); decay/`S` stay channel-level initially (`docs/modelling_methodology.md`) |
| DNA halo | `halo_strength[outcome]`, shared across markets | Unchanged in Phase 2 scope - a documented future extension, not part of the current redesign |
| Segment reporting | Outcome x channel detail, total-FH contribution, contribution waterfall | Same reports, market-filterable |

## Overall (total-FH) aggregation

"Overall" is never a separately-fitted fourth outcome - it is always the defined sum:

```
overall incremental response = New response + DNA cross-sell response + Winback response
```

(`core/attribution.py::total_fh_contribution`). Where segments have different business value
(`ModelSpec.segment_ltv`), an LTV-weighted total is also available. The redesign brief is explicit
that this aggregation rule must be preserved once market-specific curves exist - the UI must let a
user switch between Overall / New / DNA cross-sell / Winback, always derived the same way, never an
independently-fitted "Overall" model.

## Why segment reporting is retained under the redesign

Recorded in full in `docs/decision_log.md`; in short: the three segments have materially different
media response, promotional sensitivity, and value (`docs/ancestry_fh_mmm.md` section 2) - collapsing
them back into a blended KPI to simplify the market-specific redesign would reintroduce exactly the
measurement gap the original tool was built to close. Market-specificity and segment-specificity are
orthogonal; the redesign adds the former without touching the latter.
