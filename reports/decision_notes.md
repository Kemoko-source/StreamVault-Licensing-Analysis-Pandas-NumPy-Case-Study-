# Decision notes and assumptions

## Recommendation rule

The primary audience comparison recommends **standalone titles** for initial quote requests. It compares the mean vote-adjusted score of the top three eligible franchise groups with the mean score of the top five eligible standalone titles. The 2000-onward comparison is shown separately; Finance's view is not substituted for the all-years view.

## Scoring and grouping assumptions

- Each title's vote-adjusted score shrinks its average audience rating toward the dataset mean. The shrinkage strength is the median positive vote count in the analyzed set. This reduces the influence of a high score with few votes; it does not predict license demand or revenue.
- A franchise bundle is a TMDb collection with at least two analyzed titles in the relevant cohort. Bundles are ranked by mean adjusted score, with total score and votes as tie-breakers. Mean score avoids automatically favoring longer collections; the package's total score is also reported.
- A title is called standalone only when the source explicitly includes collection metadata and reports no collection. Missing collection metadata is classified as unknown, not standalone.
- The top-billed actor is the first cast member in source billing order. Billing order is only a proxy for lead status.
- Talent signals include directors and top-billed actors with at least three analyzed titles. Mean score, spread, title count, and vote support are descriptive associations, not evidence that talent causes licensing success.
- The $14M budget-share figure in the deal note distributes budget in proportion to adjusted audience score across the eight primary negotiation targets. This assumes score points have equal additive value. It is a planning anchor only, not a market valuation or profit estimate.

## Candidate reconciliation

- 126 source records were logged.
- 112 unique movies were retrieved into the current analysis.
- 6 duplicate source rows were linked to earlier records; they do not represent unique missing movies.
- 3 source IDs could not be interpreted as positive integer TMDb IDs.
- 5 valid unique IDs remain unresolved in the current acquisition log.
- 112 titles made the current analysis. Unresolved or invalid records could alter rankings; their financial effect is unknown.

## Risk and operational assumptions

The highest-ranked data risk is absent licensing price and rights evidence. Without it, no actual purchase decision can be defended. The current report also excludes titles whose collection metadata is not confirmed from franchise/standalone classification.

Earlier refreshes returned intermittent HTTP 401 errors; later runs succeeded after bounded retries. The current acquisition log is the source of truth for this run. Cached records are retained on refresh failures and marked in the log. This is the improvement beyond the brief: Adjoa can refresh quarterly without a transient API failure silently deleting previously acquired titles.

The pipeline scales across the 500-film synthetic test, but the live API may still return not-found or authorization errors. Those rows remain visible in the reconciliation file. Recheck them on each refresh rather than assuming a failed request means the title is permanently unavailable.
