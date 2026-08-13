# Activity taxonomy and economics governance

Every model driver that represents marketing activity should have an
`ActivityDefinition`. This prevents paid-media assumptions from leaking into
owned, earned, mediator, control, or event reporting.

The governed dimensions are:

- stable identity: `activity_id` at market x activity grain
- reporting family: `channel` (multiple activities may share it)
- platform/supplier: `platform`
- campaign/tactic: `campaign_type`
- marketing objective: optional normalized `marketing_objective`
- message/content: `message_type`
- funnel classification: `funnel_stage`
- ownership: `paid`, `owned`, `earned`, `external_event`
- model role: `intervention`, `mediator`, `demand_capture`, `control`, `event`
- economics: `paid_media_cost`, `fully_loaded_cost`, `campaign_cost`,
  `response_only`, `not_applicable`
- planning: `optimisable`, `scenario_only`, `fixed`, `excluded`

The stored funnel-stage vocabulary is `brand_upper`, `mid_funnel`,
`performance_lower`, `cross_funnel`, `not_applicable`, and `unclassified`.
Funnel stage is explicit reporting metadata: it is never inferred from a
channel, platform, campaign, message, metric, or source-column name and never
creates causal structure or planning permission. Legacy records use
`unclassified` until an analyst classifies them. Marketing objective remains
an optional string with UI suggestions rather than a globally closed enum.

Only activities with a credible approved resource-to-activity mapping may be
freely optimised. Mediators, controls, and events cannot be optimisable.

Organic social may report incremental NBT, incremental value, and response per
1,000 impressions. Without an approved fully loaded cost it is response-only,
not zero-cost media.

Promotional CRM may be an intervention. Lifecycle CRM normally belongs in a
mediator or fixed/scenario-only role because sends are partly driven by the
customer base. Transactional email defaults to control or excluded.

PR and earned activity may use named events, coverage, quality-weighted reach,
share of voice, sentiment, or estimated exposure. They remain response-only
unless a governed campaign cost exists. Missing cost never means zero cost or
infinite ROI.

Activity definitions are persisted and fingerprinted. Changing ownership,
economic treatment, model role, or planning eligibility makes downstream
curves and scenarios stale without invalidating the fitted response model.
Reporting taxonomy changes use a separate reporting fingerprint and do not
change the fitted model fingerprint by themselves.

