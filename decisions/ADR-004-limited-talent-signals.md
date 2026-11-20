# ADR-004: Treat billed talent as a limited audience signal

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decision owner:** StreamVault Analysis Team

## Context

Negotiators want to use directors and actors as clues when prioritizing titles.
The available credits list billing order, but it does not verify who was the
lead actor or show that a person caused a movie's audience score.

## Decision

Report directors and the first billed cast member only when they appear in at
least three analyzed movies. Describe these results as past audience
associations, not proof of future success.

## Alternatives considered

### Alternative A: Treat the first cast member as a verified lead actor

- **How it would work:** Label the first listed cast member as the movie's lead.
- **Why it is attractive:** It gives the negotiation team a simple actor field.
- **Why rejected:** Billing order is only a proxy and does not confirm the role.

### Alternative B: Count every cast member as a talent signal

- **How it would work:** Include all actors listed in the credits.
- **Why it is attractive:** It would produce a larger set of names.
- **Why rejected:** Supporting and minor roles would be treated as equal evidence.

## Consequences

- **What this buys:** A short, repeatable list of talent associated with several well-rated movies.
- **What this costs:** Newer or less prolific talent may not meet the three-movie minimum.
- **What it costs the client if I am wrong:** A negotiator may overvalue a name whose past titles do not predict audience demand.
- **What would make me revisit this:** Verified lead-role data or evidence linking talent to viewing performance.

## What this survives

The rule counts distinct analyzed movie IDs, so it remains consistent when the
catalog grows. The three-movie threshold stays a business assumption and should
be reviewed if the catalog size changes substantially.
