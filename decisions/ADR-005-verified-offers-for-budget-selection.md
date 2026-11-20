# ADR-005: Require verified offers before selecting a budget portfolio

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision owner:** StreamVault Analysis Team

## Context

The project has a $14 million budget and must compare franchise bundles with
standalone movies. The audience data does not include license fees, confirmed
rights, territories, or license dates.

## Decision

Treat each franchise as one package and each standalone as one offer. Select
only candidates with a complete, valid price and rights record, choosing the
highest total audience score within the budget separately for each time period.

## Alternatives considered

### Alternative A: Recommend the highest-scoring titles without prices

- **How it would work:** Fill the budget with the best audience scores and assume the titles can be purchased.
- **Why it is attractive:** It produces a portfolio even before negotiations.
- **Why rejected:** It invents affordability and availability that the data cannot verify.

### Alternative B: Split each franchise into individual movie offers

- **How it would work:** Treat each movie in a collection as separately purchasable.
- **Why it is attractive:** It gives more flexibility under the budget.
- **Why rejected:** It may not match the rights package a seller actually offers.

## Consequences

- **What this buys:** A budget check based on actual supplied offers and whole packages.
- **What this costs:** No portfolio is selected until prices and rights terms are complete and comparable.
- **What it costs the client if I am wrong:** Inaccurate or mismatched offer terms could select a portfolio that cannot be bought as modeled.
- **What would make me revisit this:** Itemized quotes, verified rights, or evidence that packages can be split.

## What this survives

The same selection rule runs separately for both time periods and does not
depend on the current 13-candidate list. The optimizer should be benchmarked
again before use with a much larger offer list.
