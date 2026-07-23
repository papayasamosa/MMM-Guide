"""
Joint hierarchical Family-History (FH) MMM.

One Negative-Binomial outcome model per market, covering all FH segments
(New, DNA cross-sell, Winback, ...) jointly rather than as separate
unrelated fits. Channel-level adstock and saturation curves are *shared*
across segments and markets; segment-specific response strength, promo
sensitivity and the DNA halo pathway are estimated through partial
pooling, so segments borrow strength where data is thin and diverge where
the data supports it. See ancestry_mmm/core/schema.py for the ModelSpec
that defines markets/segments/channels/DNA channels/promo columns feeding
this builder, and data/preprocessor.prepare_fh_modeling_frame for how a
joined DataFrame becomes the arrays this function consumes.

Deliberately staged: geometric adstock + Hill saturation only for this
build (Stage 1 per the requirements brief - "ship a robust core before
harder-to-justify refinements"). Media x context interaction terms are out
of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from .transformations import pt_geometric_adstock_matrix, pt_hill_function
from .schema import ModelSpec
from .outcomes import outcome_eligibility
from .pathways import (
    MediaOutcomePathway,
    ResolvedPathwayMasks,
    resolve_pathway_masks,
    resolve_validated_pathway_masks,
)
from .net_billthrough import assert_model_frame_net_billthrough_complete


@dataclass
class FHModelMeta:
    """
    Structural metadata about a built model that isn't fully recoverable from
    the InferenceData's coords alone (e.g. which channels are DNA channels,
    the halo lag). core/predict.py uses this to replay the model's math in
    plain NumPy for scenario planning and out-of-sample diagnostics.

    `outcome_ids` is this model's primary identity dimension (PR E, "make
    OutcomeDefinition the canonical modelling schema" - docs/decision_log.md)
    - NOT segment. Two distinct KPIs (e.g. a Family History sign-up and a
    Family History GSA) can share a `segment` while being two independent
    `outcome_id`s in `outcome_ids`, each with its own fitted response curve.
    `outcome_id_to_segment`/`_product`/`_metric`/`_metric_key`/`_unit`/`_role`/
    `_eligibility`/`_source_column` carry the rest of each fitted outcome_id's
    catalogue entry (see core.outcomes.OutcomeDefinition) for anything that
    needs to group or label by those dimensions without re-deriving them.
    `_metric_key` is the stable key `core.outcomes.select_outcome_ids`
    matches on (PR E.2); `_eligibility` is each outcome_id's resolved
    `core.outcomes.outcome_eligibility()` result at fit time.
    `outcome_catalogue_at_fit` is the exact `OutcomeDefinition` list this fit
    was built from - the source of truth for detecting drift between what a
    model was fit on and what the catalogue currently says (core.outcomes.
    outcome_status's "Stale" detection).

    `pathway_catalogue_at_fit` (PR F) is the exact `MediaOutcomePathway` list
    (`core.pathways`) captured when this fit was built, if a pathway
    catalogue was configured - pure pass-through metadata for
    `core.pathways.pathway_drift_status`'s drift detection, exactly like
    `outcome_catalogue_at_fit` but for the pathway catalogue.

    `pathway_masks` (PR G1) is the *operational* resolution of that
    catalogue - `core.pathways.resolve_pathway_masks`'s output, computed
    once at build time and reused both by this builder (to construct the
    right priors/masks) and by `core.predict`/`core.market_specific_predict`/
    `core.attribution`/`core.market_specific_attribution` (to replay the
    identical structure in NumPy) - the single source of truth for which
    `(outcome, channel)` cells are `primary_direct`/`active_cross_product`/
    `exploratory_cross_product`/excluded, so a fitted model's curves/
    attribution/scenario numbers can never silently diverge from what was
    actually fit. See docs/media_outcome_pathways.md and this file's
    `build_fh_hierarchical_model` for the full behaviour.

    `dna_outcome_id` is specifically the Family History DNA-cross-sell
    outcome - the halo/cross-product pathway's traditional target.
    `direct_dna_outcome_ids` lists every outcome_id that gets a *direct*
    (`primary_direct`, per `pathway_masks`) pathway from DNA-targeted media -
    `dna_outcome_id` is always a member; DNA-product outcomes (kit sales -
    see core.outcomes) are the other members once they're included in a fit.

    PR G1 (`core.pathways.resolve_pathway_masks`) generalised what were once
    two DNA-specific media inputs into the general `primary_mask`/
    `cross_product_lag_media` machinery every channel now shares - see this
    module's `build_fh_hierarchical_model` and `pathway_masks`'s docstring
    below for the operational detail; `direct_dna_outcome_ids`/
    `kit_only_outcome_ids`/`halo_eligible_outcome_ids` remain as this fit's
    *legacy-default* DNA routing (used only when no pathway catalogue
    overrides a DNA-channel cell), not a separate mechanism from
    `pathway_masks` itself. Two genuinely separate media inputs still feed
    the legacy-default DNA routing (not one shared lagged series gated by a
    multiplier - see docs/dna_fh_causal_structure.md and docs/decision_log.md
    for why the older `halo_strength = 1` encoding of "direct" was replaced):
    the undelayed saturated DNA spend (a purchase-driven response) for
    `direct_dna_outcome_ids`, and that same spend further lagged by
    `dna_lag_weeks` (a delayed, decision-cycle response) for
    `halo_eligible_outcome_ids`. `dna_outcome_id` is the one outcome that
    gets *both* pathways simultaneously by legacy default (`kit_only_outcome_ids`
    excludes it) - a DNA-kit outcome genuinely has no halo/cross-product
    pathway onto itself, but the FH DNA-cross-sell outcome may plausibly
    respond to DNA media both immediately and with a delay, so both terms are
    estimated (the delayed one regularised, shrunk toward zero by default -
    see `active_cross_product_strength_est`'s prior in the model builders)
    and summed.
    """

    markets: List[str]
    outcome_ids: List[str]
    channels: List[str]
    dna_channels: List[str]
    dna_channel_idx: List[int]
    non_dna_idx: List[int]
    dna_outcome_id: str
    dna_lag_weeks: int
    unpooled_markets: List[str]
    control_names: List[str]
    outcome_id_to_segment: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_product: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_metric: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_metric_key: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_unit: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_role: Dict[str, str] = field(default_factory=dict)
    outcome_id_to_eligibility: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    outcome_id_to_source_column: Dict[str, str] = field(default_factory=dict)
    outcome_catalogue_at_fit: List[Any] = field(default_factory=list)
    outcome_control_names: Dict[str, List[str]] = field(default_factory=dict)
    direct_dna_outcome_ids: List[str] = field(default_factory=list)
    pathway_catalogue_at_fit: List[Any] = field(default_factory=list)
    # None (the default) means "not supplied - resolve the legacy default for
    # me" (see __post_init__); it is never left as None after construction.
    # Deliberately not `field(default_factory=ResolvedPathwayMasks)` - that
    # would make "not supplied" indistinguishable from "resolved to
    # genuinely no primary/active/exploratory cells at all" (a real, if
    # unusual, outcome when a pathway catalogue explicitly excludes every
    # channel for every outcome), which __post_init__ would then incorrectly
    # overwrite with the legacy default instead of respecting it.
    pathway_masks: Optional[ResolvedPathwayMasks] = None
    net_billthrough_metadata: Optional[Any] = None

    def __post_init__(self) -> None:
        if not self.direct_dna_outcome_ids:
            self.direct_dna_outcome_ids = [self.dna_outcome_id]
        # A bundle round-tripped through JSON (core.persistence) - or a
        # hand-built test fixture - may pass a plain dict here rather than a
        # real ResolvedPathwayMasks instance; normalise defensively rather
        # than requiring every caller to know about this field.
        if isinstance(self.pathway_masks, dict):
            self.pathway_masks = ResolvedPathwayMasks.from_dict(self.pathway_masks)
        # A caller that never mentions pathway_masks at all (a bundle saved
        # before PR G1 with no such key at all, or a FHModelMeta built by
        # hand rather than through build_fh_hierarchical_model/
        # build_fh_market_specific_model - e.g. a test fixture, or curve-
        # replay code reconstructing meta from stored fields) leaves this
        # None - resolve the legacy default for it here, exactly reproducing
        # what build_fh_hierarchical_model/build_fh_market_specific_model
        # compute when no pathway catalogue is configured (see
        # resolve_pathway_masks's docstring). An *explicitly* passed
        # ResolvedPathwayMasks - including a genuinely empty one, e.g. a
        # catalogue that excludes every channel for every outcome - is never
        # overwritten; only None (truly unset) triggers this.
        if self.pathway_masks is None:
            self.pathway_masks = (
                resolve_pathway_masks(
                    self.outcome_ids,
                    self.channels,
                    [],
                    dna_channel_idx=self.dna_channel_idx,
                    dna_outcome_id=self.dna_outcome_id,
                    direct_dna_outcome_ids=self.direct_dna_outcome_ids,
                    dna_lag_weeks=self.dna_lag_weeks,
                )
                if self.outcome_ids and self.channels
                else ResolvedPathwayMasks()
            )

    @property
    def kit_only_outcome_ids(self) -> List[str]:
        """DNA-product outcome_ids (`direct_dna_outcome_ids` minus
        `dna_outcome_id`) - these have ONLY a direct pathway to DNA media,
        no halo/delayed pathway, since a kit sale isn't a delayed response
        onto itself."""
        return [s for s in self.direct_dna_outcome_ids if s != self.dna_outcome_id]

    @property
    def halo_eligible_outcome_ids(self) -> List[str]:
        """Every outcome_id that can have a halo (delayed) pathway from DNA
        media - every outcome_id except the kit-only ones. Includes
        `dna_outcome_id` itself (which can have both a direct and a halo
        component) and every ordinary FH outcome_id not in
        `direct_dna_outcome_ids` at all."""
        kit_only = set(self.kit_only_outcome_ids)
        return [s for s in self.outcome_ids if s not in kit_only]


def _default_dna_outcome_id(
    outcome_ids: List[str],
    dna_outcome_id: Optional[str],
    dna_channel_idx: Optional[List[int]] = None,
) -> str:
    """
    Resolve which outcome_id is the FH DNA cross-sell outcome (the halo
    pathway's traditional target). PR E.1 removed the old substring-based
    fallback ("the first outcome_id containing 'dna'") - with DNA-product
    kit-sale outcomes now in the same catalogue (e.g. `dna_new_kit`), that
    heuristic is genuinely ambiguous and was never validated to point at a
    Family History outcome at all
    (`core.outcomes.validate_fh_dna_cross_sell_outcome_id`/
    `infer_legacy_fh_dna_cross_sell_outcome_id` is the migration-only
    replacement, used by the Structure page - never called from here).

    `dna_outcome_id` must be passed explicitly (typically
    `spec.fh_dna_cross_sell_outcome_id`) whenever this fit actually has
    DNA-targeted channels (`dna_channel_idx` non-empty) - a fit with no DNA
    channels at all has no halo/direct-DNA pathway to target, so an
    unresolved id is harmless (defaults to `outcome_ids[0]`, never read by
    any pathway-dependent code) rather than blocking a plain FH-only fit
    with an unrelated configuration requirement.
    """
    if dna_outcome_id is not None:
        if dna_outcome_id not in outcome_ids:
            raise ValueError(
                f"dna_outcome_id '{dna_outcome_id}' is not one of the model's outcome_ids: {outcome_ids}"
            )
        return dna_outcome_id
    if not dna_channel_idx:
        return outcome_ids[0]
    raise ValueError(
        "This fit has DNA-targeted channels but no FH DNA cross-sell outcome was given. Pass "
        "dna_outcome_id explicitly (typically spec.fh_dna_cross_sell_outcome_id, configured on the "
        "Structure page) - automatic substring-based inference has been removed as ambiguous now "
        "that DNA-product kit-sale outcomes can also be in the catalogue."
    )


def _resolve_direct_dna_outcome_ids(
    outcome_ids: List[str],
    dna_outcome_id: str,
    direct_dna_outcome_ids: Optional[List[str]],
) -> List[str]:
    """`dna_outcome_id` is always a direct (non-halo-shrunk) recipient of DNA
    media, whether or not the caller lists it explicitly. Every id passed
    must be one of this model's outcome_ids."""
    resolved = list(direct_dna_outcome_ids) if direct_dna_outcome_ids else []
    if dna_outcome_id not in resolved:
        resolved.append(dna_outcome_id)
    unknown = [s for s in resolved if s not in outcome_ids]
    if unknown:
        raise ValueError(
            f"direct_dna_outcome_ids contains unknown outcome_id(s): {unknown}"
        )
    return resolved


def _market_grouped_adstock_and_saturation(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    decay_rate: pt.TensorVariable,
    hill_K: pt.TensorVariable,
    hill_S: pt.TensorVariable,
) -> pt.TensorVariable:
    """
    Apply shared adstock + Hill saturation per market block, so carryover
    never leaks across a market boundary. `market_bounds` are (start, end)
    row-index pairs describing contiguous per-market slices of X_media
    (X_media is expected sorted by [market, date] - see prepare_fh_modeling_frame).
    """
    n_obs, n_channels = X_media.shape
    blocks = []
    for start, end in market_bounds:
        X_slice = pt.as_tensor_variable(X_media[start:end])
        adstocked = pt_geometric_adstock_matrix(X_slice, decay_rate, normalize=True)
        blocks.append(adstocked)
    adstocked_full = pt.concatenate(blocks, axis=0)
    saturated = pt_hill_function(adstocked_full, hill_K, hill_S)
    return saturated


def _market_grouped_lag(
    X: pt.TensorVariable,
    market_bounds: List[tuple],
    lag_weeks: int,
) -> pt.TensorVariable:
    """Shift a (n_obs, k) tensor by `lag_weeks`, resetting to zero at each market boundary."""
    blocks = []
    for start, end in market_bounds:
        n = end - start
        block = X[start:end]
        if lag_weeks <= 0:
            blocks.append(block)
        elif lag_weeks >= n:
            blocks.append(pt.zeros_like(block))
        else:
            pad = pt.zeros_like(block[:lag_weeks])
            blocks.append(pt.concatenate([pad, block[: n - lag_weeks]], axis=0))
    return pt.concatenate(blocks, axis=0)


def build_fh_hierarchical_model(
    frame: Dict[str, Any],
    spec: ModelSpec,
    dna_lag_weeks: int = 4,
    dna_outcome_id: Optional[str] = None,
    prior_config: Optional[Dict] = None,
    direct_dna_outcome_ids: Optional[List[str]] = None,
) -> "tuple[pm.Model, FHModelMeta]":
    """
    Build the joint hierarchical FH model.

    Args:
        frame: output of data.preprocessor.prepare_fh_modeling_frame
        spec: the ModelSpec used to build `frame`
        dna_lag_weeks: extra lag (beyond adstock carryover) applied to DNA-channel
            saturated media before it entering the DNA halo pathway
        dna_outcome_id: which outcome_id is the FH DNA cross-sell outcome
            (auto-detected from the outcome_ids if not given)
        prior_config: optional dict of prior overrides (see defaults below)
        direct_dna_outcome_ids: outcome_ids that get DNA-targeted media's
            full, undamped response rather than the shrunk-toward-zero halo -
            `dna_outcome_id` is always included even if omitted here. Pass
            the DNA-product kit-sale outcome_ids (core.outcomes) alongside
            it when fitting them in the same run - they are DNA media's
            *direct* target, not a halo recipient
            (docs/dna_fh_causal_structure.md). Defaults to
            `[dna_outcome_id]` - a fit with no DNA-product outcomes behaves
            exactly as before.

    Returns:
        (unfit PyMC Model, FHModelMeta). Fit the model with core.models.fit_model;
        keep the FHModelMeta alongside the trace - core.predict needs it to
        replay this model's math in NumPy for scenario planning/diagnostics.
    """
    prior_config = prior_config or {}
    assert_model_frame_net_billthrough_complete(frame)

    markets: List[str] = frame["markets"]
    market_idx: np.ndarray = frame["market_idx"]
    market_bounds: List[tuple] = frame["market_bounds"]
    channels: List[str] = frame["channels"]
    dna_channel_idx: List[int] = frame["dna_channel_idx"]
    outcome_ids: List[str] = frame["outcome_ids"]
    X_media: np.ndarray = frame["X_media"]
    Y: np.ndarray = frame["Y"]
    promo: np.ndarray = frame["promo"]
    X_controls: np.ndarray = frame["X_controls"]
    control_names: List[str] = frame["control_names"]
    fourier: np.ndarray = frame["fourier"]
    trend: np.ndarray = frame["trend"]
    unpooled_markets: List[str] = frame.get("unpooled_markets") or []

    n_obs, n_channels = X_media.shape
    n_outcomes = len(outcome_ids)
    n_fourier = fourier.shape[1]
    n_controls = X_controls.shape[1]

    dna_outcome_id = _default_dna_outcome_id(
        outcome_ids, dna_outcome_id, dna_channel_idx
    )
    direct_dna_outcome_ids = _resolve_direct_dna_outcome_ids(
        outcome_ids, dna_outcome_id, direct_dna_outcome_ids
    )
    non_dna_idx = [i for i, c in enumerate(channels) if i not in dna_channel_idx]

    # Normalise to real MediaOutcomePathway instances defensively - a caller
    # may have passed plain dicts (e.g. straight from session state) rather
    # than converting them first (PR G1 - core.pathways.resolve_pathway_masks
    # is what makes this catalogue operational; see FHModelMeta's docstring).
    pathway_catalogue: List[MediaOutcomePathway] = [
        p if isinstance(p, MediaOutcomePathway) else MediaOutcomePathway.from_dict(p)
        for p in (frame.get("media_outcome_pathways") or [])
    ]
    outcome_catalogue = frame.get("outcomes") or []
    outcome_products = {
        outcome.outcome_id: outcome.product for outcome in outcome_catalogue
    }
    channel_products = {
        channel: ("DNA" if index in dna_channel_idx else "Family History")
        for index, channel in enumerate(channels)
    }
    pathway_masks = resolve_validated_pathway_masks(
        outcome_ids,
        channels,
        pathway_catalogue,
        channel_products=channel_products,
        outcome_products=outcome_products,
        fitted_outcome_ids=outcome_ids,
        diagnostic_only_outcome_ids=[
            outcome.outcome_id
            for outcome in outcome_catalogue
            if getattr(outcome, "role", None) == "diagnostic"
        ],
        dna_channel_idx=dna_channel_idx,
        dna_outcome_id=dna_outcome_id,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        dna_lag_weeks=dna_lag_weeks,
    )

    channel_mean_spend = X_media.mean(axis=0)
    channel_mean_spend = np.where(channel_mean_spend > 0, channel_mean_spend, 1.0)

    with pm.Model() as model:
        model.add_coord("obs", np.arange(n_obs))
        model.add_coord("market", markets)
        model.add_coord("outcome", outcome_ids)
        model.add_coord("channel", channels)
        model.add_coord("fourier", np.arange(n_fourier))

        # -----------------------------------------------------------------
        # Shared channel-level adstock + saturation curves (pooled across
        # outcomes AND markets - "share what should genuinely be shared").
        # -----------------------------------------------------------------
        decay_rate = pm.Beta(
            "decay_rate",
            mu=prior_config.get("decay_mu", 0.5),
            sigma=prior_config.get("decay_sigma", 0.2),
            dims="channel",
        )
        # Gamma (not HalfNormal): K is a half-saturation *spend level*, so its
        # prior should be centred near typical spend and bounded away from
        # zero. HalfNormal's mode sits at 0, which is both poor prior belief
        # (K=0 means everything is instantly saturated) and numerically
        # unstable (see pt_hill_function's docstring on the log(K) gradient).
        K_prior_mean = channel_mean_spend * prior_config.get("K_scale", 1.0)
        K_alpha = prior_config.get("K_alpha", 3.0)
        hill_K = pm.Gamma(
            "hill_K",
            alpha=K_alpha,
            beta=K_alpha / K_prior_mean,
            dims="channel",
        )
        hill_S = pm.Gamma(
            "hill_S",
            alpha=prior_config.get("S_alpha", 4.0),
            beta=prior_config.get("S_beta", 4.0),
            dims="channel",
        )

        sat_media = pm.Deterministic(
            "sat_media",
            _market_grouped_adstock_and_saturation(
                X_media, market_bounds, decay_rate, hill_K, hill_S
            ),
            dims=("obs", "channel"),
        )

        # -----------------------------------------------------------------
        # Outcome-specific response multipliers via partial pooling.
        # log_beta[o, c] = mu_channel[c] + sigma_pool[c] * z[o, c]
        # sigma_pool[c] is the *learned* pooling strength: outcomes borrow
        # strength when it's small, diverge when the data supports it.
        # -----------------------------------------------------------------
        # Kept fairly tight by default: eta sums *all* channels' contributions
        # additively before the final exp(), so a wide per-channel prior
        # compounds across channels into an implausible tail very fast.
        mu_channel = pm.Normal(
            "mu_channel",
            mu=prior_config.get("channel_effect_mu", -2.5),
            sigma=prior_config.get("channel_effect_sigma", 0.5),
            dims="channel",
        )
        sigma_pool = pm.HalfNormal(
            "sigma_pool",
            sigma=prior_config.get("pooling_sigma_prior", 0.3),
            dims="channel",
        )
        z_offset = pm.Normal("z_offset", mu=0, sigma=1, dims=("outcome", "channel"))
        log_beta = pm.Deterministic(
            "log_beta",
            mu_channel[None, :] + sigma_pool[None, :] * z_offset,
            dims=("outcome", "channel"),
        )
        beta = pm.Deterministic("beta", pt.exp(log_beta), dims=("outcome", "channel"))

        # -----------------------------------------------------------------
        # Pathway-driven channel contributions (PR G1 - core.pathways.
        # resolve_pathway_masks, called once above as `pathway_masks`,
        # generalises the old DNA-only direct/halo split to every channel):
        #
        # - `primary_direct` cells (the vast majority - every non-DNA
        #   channel's relationship to every outcome by legacy default, plus
        #   a DNA channel's relationship to its own direct_dna_outcome_ids)
        #   get `beta[o, c]` at full weight, no extra shrinkage, on the
        #   *undelayed* saturated media - `eta_primary`, one masked matmul
        #   for every such cell at once.
        # - `active_cross_product` cells (the old unconditional DNA-halo
        #   pathway, generalised) get `beta[o, c] * active_strength[o, c]`
        #   on `cross_product_lag_media` (saturated media further lagged by
        #   `pathway_masks.cross_product_lag_weeks`) - `active_strength` is
        #   a HalfNormal-shrunk-toward-zero multiplier, one per active cell
        #   (not shared across channels the way the old per-outcome-only
        #   `halo_strength` was, when a fit has more than one DNA channel -
        #   a deliberate refinement, see docs/decision_log.md).
        # - `exploratory_cross_product` cells use the same structure as
        #   `active_cross_product` but a *tighter* HalfNormal sigma by
        #   default (`exploratory_cross_product_sigma` <
        #   `active_cross_product_sigma`) - "strongly shrunk toward zero",
        #   per the instruction document.
        # - `excluded` cells appear in none of the three masks, so they
        #   never enter any matmul above - zero contribution, deterministically,
        #   not merely a tight prior (required test: "excluded pathways
        #   produce no coefficient or contribution").
        #
        # With no pathway catalogue configured, `pathway_masks` resolves to
        # exactly this codebase's pre-PR-G1 legacy defaults (see
        # `resolve_pathway_masks`'s docstring and its equivalence tests) -
        # `dna_outcome_id` on a DNA channel is the one cell legitimately in
        # both `primary` and `active`, reproducing the old "gets both a
        # direct and a halo term" treatment exactly.
        # -----------------------------------------------------------------
        primary_mask = pt.constant(pathway_masks.primary_matrix(outcome_ids, channels))
        eta_primary = pm.Deterministic(
            "eta_primary",
            pm.math.dot(sat_media, (beta * primary_mask).T),
            dims=("obs", "outcome"),
        )

        active_cells = pathway_masks.active_cells(outcome_ids, channels)
        exploratory_cells = pathway_masks.exploratory_cells(outcome_ids, channels)

        all_cross_cells = active_cells + exploratory_cells
        lagged_media_by_weeks = {
            lag: _market_grouped_lag(sat_media, market_bounds, lag)
            for lag in sorted(
                {
                    pathway_masks.lag_for_component(
                        outcome_ids[cell[0]], channels[cell[1]]
                    )
                    for cell in all_cross_cells
                }
            )
        }

        def _cross_product_eta(
            cells: list, var_name: str, role_default: float
        ) -> pt.TensorVariable:
            # Explicit pathway scale > role default > the validated hard
            # defaults supplied by the caller.  A vector sigma makes the
            # configured scale operational for each individual pathway.
            sigmas = [
                pathway_masks.prior_for_component(
                    outcome_ids[cell[0]],
                    channels[cell[1]],
                    default=role_default,
                )
                for cell in cells
            ]
            strength_est = pm.HalfNormal(
                f"{var_name}_est", sigma=pt.constant(sigmas), shape=len(cells)
            )
            strength_matrix = pt.zeros((n_outcomes, n_channels))
            eta = pt.zeros((n_obs, n_outcomes))
            for idx, (oi, ci) in enumerate(cells):
                strength_matrix = pt.set_subtensor(
                    strength_matrix[oi, ci], strength_est[idx]
                )
                lagged = lagged_media_by_weeks[
                    pathway_masks.lag_for_component(
                        outcome_ids[oi], channels[ci]
                    )
                ]
                cell_matrix = pt.zeros((n_outcomes, n_channels))
                cell_matrix = pt.set_subtensor(cell_matrix[oi, ci], strength_est[idx])
                eta = eta + pm.math.dot(lagged, (beta * cell_matrix).T)
            pm.Deterministic(var_name, strength_matrix, dims=("outcome", "channel"))
            return eta

        eta_active = (
            _cross_product_eta(
                active_cells,
                "active_cross_product_strength",
                prior_config.get("active_cross_product_sigma", 0.25),
            )
            if active_cells
            else pt.zeros((n_obs, n_outcomes))
        )
        eta_exploratory = (
            _cross_product_eta(
                exploratory_cells,
                "exploratory_cross_product_strength",
                prior_config.get("exploratory_cross_product_sigma", 0.08),
            )
            if exploratory_cells
            else pt.zeros((n_obs, n_outcomes))
        )
        eta_active = pm.Deterministic(
            "eta_active_cross_product", eta_active, dims=("obs", "outcome")
        )
        eta_exploratory = pm.Deterministic(
            "eta_exploratory_cross_product", eta_exploratory, dims=("obs", "outcome")
        )
        eta_channels = pm.Deterministic(
            "eta_channels",
            eta_primary + eta_active + eta_exploratory,
            dims=("obs", "outcome"),
        )

        # -----------------------------------------------------------------
        # Outcome-specific promotional sensitivity (non-negative: promos lift).
        # -----------------------------------------------------------------
        promo_coef = pm.HalfNormal(
            "promo_coef", sigma=prior_config.get("promo_sigma", 0.5), dims="outcome"
        )
        eta_promo = promo * promo_coef[None, :]

        # -----------------------------------------------------------------
        # Geo hierarchy: market-level baseline offsets, partially pooled by
        # default; markets in `unpooled_markets` get an effectively
        # independent (wide, unpooled) prior instead of sharing strength.
        # -----------------------------------------------------------------
        market_pool_sigma = pm.HalfNormal(
            "market_pool_sigma",
            sigma=prior_config.get("market_pool_sigma_prior", 0.4),
            dims="outcome",
        )
        unpooled_sigma_const = prior_config.get("unpooled_market_sigma", 2.0)
        sigma_rows = []
        for m in markets:
            if m in unpooled_markets:
                sigma_rows.append(
                    pt.as_tensor_variable(np.full(n_outcomes, unpooled_sigma_const))
                )
            else:
                sigma_rows.append(market_pool_sigma)
        market_sigma_stack = pt.stack(sigma_rows)  # (n_market, n_outcome)

        market_offset_raw = pm.Normal(
            "market_offset_raw", mu=0, sigma=1, dims=("market", "outcome")
        )
        market_offset = pm.Deterministic(
            "market_offset",
            market_offset_raw * market_sigma_stack,
            dims=("market", "outcome"),
        )
        eta_market = market_offset[market_idx]

        # -----------------------------------------------------------------
        # Baseline, trend, seasonality (calendar-anchored Fourier).
        # -----------------------------------------------------------------
        intercept = pm.Normal(
            "intercept",
            mu=prior_config.get(
                "intercept_mu", np.log(np.clip(Y.mean(axis=0), 1, None))
            ),
            sigma=prior_config.get("intercept_sigma", 1.0),
            dims="outcome",
        )
        trend_coef = pm.Normal(
            "trend_coef",
            mu=0,
            sigma=prior_config.get("trend_sigma", 0.5),
            dims="outcome",
        )
        eta_trend = trend[:, None] * trend_coef[None, :]

        gamma_fourier = pm.Normal(
            "gamma_fourier",
            mu=0,
            sigma=prior_config.get("fourier_sigma", 0.4),
            dims=("fourier", "outcome"),
        )
        eta_season = pm.math.dot(fourier, gamma_fourier)

        eta = (
            intercept[None, :]
            + eta_market
            + eta_trend
            + eta_season
            + eta_channels
            + eta_promo
        )

        # -----------------------------------------------------------------
        # Outcome-level controls, e.g. DNA kit price acting only on the DNA
        # cross-sell outcome's equation. Keyed by outcome_id (frame["outcome_controls"] -
        # data.preprocessor.prepare_fh_modeling_frame) - segment-level
        # ModelSpec.segment_control_cols config is resolved to every
        # outcome_id sharing that segment there, so two outcomes on one
        # segment both get that segment's controls applied to their own
        # equation independently.
        # -----------------------------------------------------------------
        outcome_controls = frame.get("outcome_controls") or {}
        outcome_control_names = frame.get("outcome_control_names") or {}
        for oid, arr in outcome_controls.items():
            if oid not in outcome_ids:
                continue
            o_idx = outcome_ids.index(oid)
            names = outcome_control_names.get(
                oid, [f"ctrl_{i}" for i in range(arr.shape[1])]
            )
            coord_name = f"{oid}_control"
            model.add_coord(coord_name, names)
            coef = pm.Normal(
                f"outcome_control_coef_{oid}",
                mu=0,
                sigma=prior_config.get("control_sigma", 0.5),
                dims=coord_name,
            )
            contrib = pm.math.dot(pt.as_tensor_variable(arr), coef)
            eta = pt.set_subtensor(eta[:, o_idx], eta[:, o_idx] + contrib)

        if n_controls > 0:
            model.add_coord("control", control_names)
            control_coef = pm.Normal(
                "control_coef",
                mu=0,
                sigma=prior_config.get("control_sigma", 0.5),
                dims="control",
            )
            eta = (
                eta
                + pm.math.dot(pt.as_tensor_variable(X_controls), control_coef)[:, None]
            )

        # Clip is a numerical safety net (not a modelling assumption): eta is
        # a sum of several additive terms before this exp(), so pathological
        # prior draws (e.g. during prior-predictive checks) can otherwise
        # overflow into values NegativeBinomial sampling can't handle.
        mu = pm.Deterministic(
            "mu", pt.clip(pt.exp(eta), 1e-6, 1e9), dims=("obs", "outcome")
        )

        alpha = pm.Gamma(
            "alpha",
            alpha=prior_config.get("alpha_shape", 2.0),
            beta=prior_config.get("alpha_rate", 0.1),
            dims="outcome",
        )

        pm.NegativeBinomial(
            "y_obs", mu=mu, alpha=alpha[None, :], observed=Y, dims=("obs", "outcome")
        )

    outcome_catalogue: List[Any] = frame.get("outcomes") or []
    meta = FHModelMeta(
        markets=markets,
        outcome_ids=outcome_ids,
        channels=channels,
        dna_channels=[channels[i] for i in dna_channel_idx],
        dna_channel_idx=dna_channel_idx,
        non_dna_idx=non_dna_idx,
        dna_outcome_id=dna_outcome_id,
        dna_lag_weeks=dna_lag_weeks,
        unpooled_markets=unpooled_markets,
        control_names=control_names,
        outcome_id_to_segment={o.outcome_id: o.segment for o in outcome_catalogue},
        outcome_id_to_product={o.outcome_id: o.product for o in outcome_catalogue},
        outcome_id_to_metric={o.outcome_id: o.metric for o in outcome_catalogue},
        outcome_id_to_metric_key={
            o.outcome_id: o.metric_key for o in outcome_catalogue
        },
        outcome_id_to_unit={o.outcome_id: o.unit for o in outcome_catalogue},
        outcome_id_to_role={o.outcome_id: o.role for o in outcome_catalogue},
        outcome_id_to_eligibility={
            o.outcome_id: outcome_eligibility(o) for o in outcome_catalogue
        },
        outcome_id_to_source_column={
            o.outcome_id: o.source_column for o in outcome_catalogue
        },
        outcome_catalogue_at_fit=outcome_catalogue,
        outcome_control_names=frame.get("outcome_control_names") or {},
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        pathway_catalogue_at_fit=pathway_catalogue,
        pathway_masks=pathway_masks,
        net_billthrough_metadata=frame.get("net_billthrough_metadata"),
    )
    return model, meta
