# ADR-003: Classify franchises only from confirmed collection data

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision owner:** StreamVault Analysis Team

## Context

The recommendation compares franchise bundles with standalone movies. Missing
collection information does not prove that a movie is standalone, and collection
names alone may not uniquely identify a group.

## Decision

Group movies by a confirmed collection ID and call a group a franchise only
when at least two analyzed movies belong to it. Call a movie standalone only
when collection information is present and explicitly empty; leave missing
information unclassified.

## Alternatives considered

### Alternative A: Infer franchises from similar titles

- **How it would work:** Group movies by matching words in their titles.
- **Why it is attractive:** It could fill gaps when collection data is absent.
- **Why rejected:** Similar wording can join unrelated movies or miss titles with different names.

### Alternative B: Treat every movie without a collection ID as standalone

- **How it would work:** Put both empty and missing collection values on the standalone list.
- **Why it is attractive:** It would create a longer, more complete-looking list.
- **Why rejected:** Missing data would be presented as a verified fact.

## Consequences

- **What this buys:** Clear evidence for franchise and standalone labels.
- **What this costs:** Some movies remain unclassified when collection data is missing.
- **What it costs the client if I am wrong:** A bundle or standalone opportunity could be missed, changing the negotiation shortlist.
- **What would make me revisit this:** A verified collection source that fills or corrects missing collection IDs.

## What this survives

Grouping uses collection IDs rather than fixed title names, so the same rule
can process a larger catalog. The two-title minimum is applied within each time
period, and titles with unknown collection data stay unknown at any scale.
