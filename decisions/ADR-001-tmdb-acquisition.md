# ADR-001: Use TMDb data and reconcile every source record

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision owner:** StreamVault Analysis Team

## Context

The analysis needs movie, credit, audience, and collection details for the
supplied ID list. Failed and repeated IDs must remain visible, and one failed
request should not erase a previously acquired record.

## Decision

Use TMDb movie and credits data for catalog details. Log each source row,
retry temporary request failures within a fixed limit, and keep the last local
record when a refresh fails.

## Alternatives considered

### Alternative A: Use a fixed hand-maintained catalog

- **How it would work:** Store all movie details in a spreadsheet and update it manually.
- **Why it is attractive:** It avoids network requests and API setup.
- **Why rejected:** It is harder to refresh consistently and does not provide a clear, repeatable record of failed IDs.

### Alternative B: Stop the whole run when any ID fails

- **How it would work:** Reject all results if one movie cannot be fetched.
- **Why it is attractive:** Every record in a run would be freshly retrieved.
- **Why rejected:** A temporary failure would block useful results and could disrupt quarterly refreshes.

## Consequences

- **What this buys:** A row-by-row account of invalid IDs, duplicates, successful requests, and failures.
- **What this costs:** Results depend on an external data source and may include cached records.
- **What it costs the client if I am wrong:** A missed or stale title could alter a shortlist; its financial effect cannot be estimated without rights and price data.
- **What would make me revisit this:** A better licensed source, repeated API outages, or a change to the source ID list.

## What this survives

The 500-title offline test checks that logging and processing are not tied to
the current list size. It uses simulated responses; a larger live refresh
still needs to respect request limits and report service failures.
