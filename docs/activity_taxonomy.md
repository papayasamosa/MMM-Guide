# Activity taxonomy and economics governance

Every model driver that represents marketing activity should have an
`ActivityDefinition`. This prevents paid-media assumptions from leaking into
owned, earned, mediator, control, or event reporting.

The governed dimensions are:

- ownership: `paid`, `owned`, `earned`, `external_event`
- model role: `intervention`, `mediator`, `demand_capture`, `control`, `event`
- economics: `paid_media_cost`, `fully_loaded_cost`, `campaign_cost`,
  `response_only`, `not_applicable`
- planning: `optimisable`, `scenario_only`, `fixed`, `excluded`

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

