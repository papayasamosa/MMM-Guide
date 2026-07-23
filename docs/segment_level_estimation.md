# Pathway-masked segment-level estimation

Both model builders use one resolved component contract.

```text
direct
  beta[outcome, channel] × saturated_media[channel]

cross_product
  beta[outcome, channel]
  × pathway_strength[outcome, channel]
  × lag_component(saturated_media[channel])

mediated / excluded
  no standard likelihood term
```

Direct and delayed components may coexist on one channel/outcome pair.
Every cross-product component has its own lag and HalfNormal strength-prior
scale. Active and exploratory components retain separate PyMC deterministics,
while NumPy replay stores their non-overlapping values in one
`pathway_strength[outcome][channel]` lookup.

`ResolvedPathwayComponent` is authoritative. `ResolvedPathwayMasks` retains
the older named masks and index-keyed dictionaries as derived bundle
compatibility caches only. Calculations enumerate components or call methods
that derive directly from them.

The fitting equation, NumPy replay, attribution, headline attribution, and
planning-only steady-state response all apply component eligibility
independently. Disabling a delayed halo therefore cannot remove an eligible
direct component on the same pair.

Full-context validation occurs before model construction and includes channel
and outcome product ownership, fitted outcomes, and diagnostic-only outcomes.
The Structure page previews the resolved terms before a fit.

Legacy routing remains available for uncovered cells so old projects reproduce
their prior direct/DNA-halo behaviour. Once an explicit component is supplied
for a pair, the explicit component set replaces that pair's legacy defaults.
