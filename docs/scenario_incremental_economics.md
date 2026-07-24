# Scenario incremental economics

Scenario forecasting and media economics use different estimands.

For every month and outcome:

```text
predicted_total_outcome = mu(candidate plan)
predicted_counterfactual_outcome = mu(explicit counterfactual)
incremental_outcome = predicted_total_outcome
                      - predicted_counterfactual_outcome
```

Total forecasts retain baseline, trend, seasonality, promotions, controls, and
media. CPA and ROI never use that total as their response denominator.

Whole-plan incremental NBT CPA is:

```text
total monetary plan spend / incremental FH net bill-through
```

Incremental ROI is incremental value divided by total monetary plan spend and
is available only when every included outcome has a governed value mapping.
The counterfactual media-input plan is stored with every output.

`PlanningObjective` records the estimand, metric, selected outcomes, and value
currency. The Family History default is incremental net bill-through where
that metric exists; legacy models without NBT fall back to incremental FH GSA.

