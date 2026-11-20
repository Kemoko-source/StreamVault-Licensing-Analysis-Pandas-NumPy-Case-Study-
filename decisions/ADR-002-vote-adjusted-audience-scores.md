# ADR-002: Rank audience interest with vote-adjusted scores

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision owner:** StreamVault Analysis Team

## Context

A high rating with very few votes is weaker evidence than a similar rating
supported by many votes. The brief also requires both an all-years view and a
view of titles released from 2000 onward.

## Decision

Adjust each movie's rating toward the analyzed catalog's average, using the
median positive vote count as the adjustment strength. The median is a robust,
reproducible estimate of typical vote support and is less influenced by a few
extremely popular titles than the mean. This is a dataset-specific heuristic,
not a fitted empirical-Bayes prior. Report the full catalog and post-1999
results separately, and use both only to prioritize quote requests.

## Alternatives considered

### Alternative A: Rank by raw rating

- **How it would work:** Sort titles by their published average rating alone.
- **Why it is attractive:** It is simple to explain and reproduce.
- **Why rejected:** A title with very few votes could rank above a better-supported title.

### Alternative B: Rank by popularity

- **How it would work:** Sort titles by the source's popularity measure.
- **Why it is attractive:** It may reflect current attention.
- **Why rejected:** It does not show licensing demand, expected return, or price.

## Consequences

- **What this buys:** A shortlist that accounts for both ratings and vote support.
- **What this costs:** Scores depend on the movies in each run, so scores from different catalogs may not be directly comparable.
- **What it costs the client if I am wrong:** The quote order could favor titles whose audience score does not translate into viewing or revenue.
- **What would make me revisit this:** Reliable viewing, retention, or licensing-performance data becoming available.

## What this survives

The average and vote threshold are calculated from the current input rather than
being tied to a fixed number of movies. Adjoa can rerun the same rule on 500
titles, but the result remains an audience signal, not a financial forecast.
