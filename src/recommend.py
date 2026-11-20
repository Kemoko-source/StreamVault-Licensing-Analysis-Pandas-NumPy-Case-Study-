"""Build candidate, talent, diagnosis, and client-facing decision deliverables."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from src.analyze import build_content_shortlist
else:
    from analyze import build_content_shortlist


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOVIES_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_movies.csv"
ACQUISITION_LOG_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_acquisition_log.csv"
OFFERS_PATH = PROJECT_ROOT / "data" / "raw" / "license_offers_template.csv"
REPORT_DIR = PROJECT_ROOT / "reports"
FRANCHISE_PATH = REPORT_DIR / "franchise_targets.csv"
STANDALONE_PATH = REPORT_DIR / "standalone_shortlist.csv"
TALENT_PATH = REPORT_DIR / "talent_signals.csv"
DIAGNOSIS_PATH = REPORT_DIR / "data_diagnosis.csv"
RECONCILIATION_PATH = REPORT_DIR / "candidate_reconciliation.csv"
DECISION_NOTES_PATH = REPORT_DIR / "decision_notes.md"
CLIENT_MEMO_PATH = REPORT_DIR / "client_memo.md"

OFFER_FIELDS = (
    "license_fee_usd",
    "rights_available",
    "territory",
    "license_start_date",
    "license_end_date",
    "quote_date",
    "offer_source",
)


def _scored_movies(movies: pd.DataFrame) -> pd.DataFrame:
    scored = build_content_shortlist(movies, limit=max(len(movies), 1))
    metadata_columns = [
        "tmdb_id",
        "collection_id",
        "collection_name",
        "collection_metadata_status",
        "director",
        "top_billed_actor",
        "top_cast",
    ]
    # Keep classification and talent fields beside each title's audience score.
    metadata = movies.copy()
    for column in metadata_columns:
        if column not in metadata:
            metadata[column] = pd.NA
    metadata = metadata[metadata_columns].drop_duplicates("tmdb_id")
    if "top_cast" in metadata:
        first_cast = metadata["top_cast"].astype("string").str.split("|", regex=False).str[0]
        metadata["top_billed_actor"] = metadata["top_billed_actor"].combine_first(first_cast)
    return scored.merge(metadata, on="tmdb_id", how="left", validate="many_to_one")


def build_franchise_targets(movies: pd.DataFrame, limit: int = 3) -> pd.DataFrame:
    """Rank multi-title TMDb collections by mean adjusted audience score."""
    scored = _scored_movies(movies)
    columns = [
        "cohort",
        "rank",
        "collection_id",
        "collection_name",
        "title_count",
        "mean_adjusted_rating",
        "total_adjusted_rating",
        "weighted_vote_average",
        "total_votes",
        "member_tmdb_ids",
        "member_titles",
        "reason",
    ]
    rows = []

    # Missing collection data is not enough to call a title a franchise.
    confirmed = scored.loc[
        scored["collection_metadata_status"].eq("present")
        & scored["collection_id"].notna()
    ]
    for cohort, cohort_rows in confirmed.groupby("cohort", sort=False):
        groups = []
        for collection_id, group in cohort_rows.groupby("collection_id", sort=False):
            if group["tmdb_id"].nunique() < 2:
                continue
            group = group.sort_values(
                ["release_year", "tmdb_id"], na_position="last", kind="mergesort"
            )
            votes = pd.to_numeric(group["vote_count"], errors="coerce").to_numpy(
                dtype=float
            )
            ratings = pd.to_numeric(group["vote_average"], errors="coerce").to_numpy(
                dtype=float
            )
            positive = votes > 0
            weighted_average = (
                float(np.average(ratings[positive], weights=votes[positive]))
                if positive.any()
                else np.nan
            )
            name_values = group["collection_name"].dropna()
            name = (
                str(name_values.iloc[0])
                if not name_values.empty
                else f"Collection {int(collection_id)}"
            )
            # Mean score avoids giving longer collections an automatic advantage.
            mean_score = float(group["adjusted_rating"].mean())
            total_score = float(group["adjusted_rating"].sum())
            title_count = int(group["tmdb_id"].nunique())
            total_votes = int(np.nansum(votes))
            titles = group["title"].astype(str).tolist()
            ids = group["tmdb_id"].astype(int).tolist()
            groups.append(
                {
                    "cohort": cohort,
                    "collection_id": int(collection_id),
                    "collection_name": name,
                    "title_count": title_count,
                    "mean_adjusted_rating": mean_score,
                    "total_adjusted_rating": total_score,
                    "weighted_vote_average": weighted_average,
                    "total_votes": total_votes,
                    "member_tmdb_ids": "|".join(map(str, ids)),
                    "member_titles": " | ".join(titles),
                    "reason": (
                        f"{title_count} analyzed titles; mean vote-adjusted "
                        f"score {mean_score:.2f} across {total_votes:,} votes."
                    ),
                }
            )

        groups.sort(
            key=lambda row: (
                -row["mean_adjusted_rating"],
                -row["total_adjusted_rating"],
                -row["total_votes"],
                row["collection_id"],
            )
        )
        for rank, row in enumerate(groups[:limit], start=1):
            row["rank"] = rank
            rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def build_standalone_shortlist(movies: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    """Rank confirmed standalone titles by vote-adjusted audience score."""
    scored = _scored_movies(movies)
    columns = [
        "cohort",
        "rank",
        "tmdb_id",
        "title",
        "release_year",
        "adjusted_rating",
        "vote_average",
        "vote_count",
        "genres",
        "director",
        "top_billed_actor",
        "reason",
    ]
    # Only an explicit empty collection field confirms a standalone title.
    standalone = scored.loc[
        scored["collection_metadata_status"].eq("present")
        & scored["collection_id"].isna()
    ].copy()
    standalone["vote_count"] = pd.to_numeric(
        standalone["vote_count"], errors="coerce"
    )
    standalone["adjusted_rating"] = pd.to_numeric(
        standalone["adjusted_rating"], errors="coerce"
    )
    standalone = standalone.sort_values(
        ["cohort", "adjusted_rating", "vote_count", "tmdb_id"],
        ascending=[True, False, False, True],
        kind="mergesort",
    )
    standalone["rank"] = standalone.groupby("cohort", sort=False).cumcount() + 1
    standalone = standalone.loc[standalone["rank"] <= limit, columns[:-1]]
    if standalone.empty:
        return pd.DataFrame(columns=columns)
    standalone["reason"] = standalone.apply(
        lambda row: (
            f"Vote-adjusted score {row['adjusted_rating']:.2f} supported by "
            f"{int(row['vote_count']):,} votes; confirmed outside a collection."
        ),
        axis=1,
    )
    return standalone[columns].reset_index(drop=True)


def build_talent_signals(
    movies: pd.DataFrame,
    minimum_titles: int = 3,
    limit: int = 10,
) -> pd.DataFrame:
    """Summarize repeated director and top-billed actor associations."""
    if minimum_titles < 2 or limit < 1:
        raise ValueError("minimum_titles must be at least 2 and limit must be positive")
    scored = _scored_movies(movies)
    columns = [
        "cohort",
        "role",
        "rank",
        "talent",
        "title_count",
        "mean_adjusted_rating",
        "rating_std_dev",
        "weighted_vote_average",
        "total_votes",
        "titles",
    ]
    rows = []

    for cohort, cohort_rows in scored.groupby("cohort", sort=False):
        for role, source_column, split_names in (
            ("director", "director", True),
            ("top_billed_actor", "top_billed_actor", False),
        ):
            if source_column not in cohort_rows:
                continue
            talent_rows = cohort_rows[["tmdb_id", "title", "adjusted_rating", "vote_average", "vote_count", source_column]].copy()
            talent_rows["talent"] = (
                talent_rows[source_column].astype("string").str.split("|", regex=False)
                if split_names
                else talent_rows[source_column].map(
                    lambda value: [value] if pd.notna(value) else []
                )
            )
            # Split multi-director credits so each director gets their own signal.
            talent_rows = talent_rows.explode("talent")
            talent_rows["talent"] = talent_rows["talent"].astype("string").str.strip()
            talent_rows = talent_rows.loc[
                talent_rows["talent"].notna() & talent_rows["talent"].ne("")
            ]

            for talent, group in talent_rows.groupby("talent", sort=False):
                title_count = int(group["tmdb_id"].nunique())
                if title_count < minimum_titles:
                    continue
                votes = pd.to_numeric(group["vote_count"], errors="coerce").to_numpy(
                    dtype=float
                )
                ratings = pd.to_numeric(group["vote_average"], errors="coerce").to_numpy(
                    dtype=float
                )
                positive = votes > 0
                weighted_average = (
                    float(np.average(ratings[positive], weights=votes[positive]))
                    if positive.any()
                    else np.nan
                )
                rows.append(
                    {
                        "cohort": cohort,
                        "role": role,
                        "talent": str(talent),
                        "title_count": title_count,
                        "mean_adjusted_rating": float(group["adjusted_rating"].mean()),
                        "rating_std_dev": float(group["adjusted_rating"].std(ddof=0)),
                        "weighted_vote_average": weighted_average,
                        "total_votes": int(np.nansum(votes)),
                        "titles": " | ".join(
                            group.drop_duplicates("tmdb_id")["title"].astype(str)
                        ),
                    }
                )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=columns)
    result = result.sort_values(
        ["cohort", "role", "mean_adjusted_rating", "title_count", "total_votes"],
        ascending=[True, True, False, False, False],
        kind="mergesort",
    )
    result["rank"] = result.groupby(["cohort", "role"], sort=False).cumcount() + 1
    return result.loc[result["rank"] <= limit, columns].reset_index(drop=True)


def build_negotiation_template(
    franchise_targets: pd.DataFrame,
    standalone_shortlist: pd.DataFrame,
) -> pd.DataFrame:
    """Create one quote row per franchise package or standalone candidate."""
    candidates: dict[str, dict] = {}
    # Use one offer row per package, even when it ranks in both time windows.
    for _, row in franchise_targets.iterrows():
        candidate_id = f"collection:{int(row['collection_id'])}"
        candidate = candidates.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "candidate_type": "franchise_bundle",
                "candidate_name": row["collection_name"],
                "collection_id": int(row["collection_id"]),
                "member_tmdb_ids": row["member_tmdb_ids"],
                "member_titles": row["member_titles"],
                "all_year_rank": pd.NA,
                "all_year_score": pd.NA,
                "post_2000_rank": pd.NA,
                "post_2000_score": pd.NA,
            },
        )
        rank_column = "all_year_rank" if row["cohort"] == "all_years" else "post_2000_rank"
        score_column = "all_year_score" if row["cohort"] == "all_years" else "post_2000_score"
        candidate[rank_column] = row["rank"]
        candidate[score_column] = row["total_adjusted_rating"]
        candidate["member_tmdb_ids"] = row["member_tmdb_ids"]
        candidate["member_titles"] = row["member_titles"]

    for _, row in standalone_shortlist.iterrows():
        candidate_id = f"title:{int(row['tmdb_id'])}"
        candidate = candidates.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "candidate_type": "standalone",
                "candidate_name": row["title"],
                "collection_id": pd.NA,
                "member_tmdb_ids": str(int(row["tmdb_id"])),
                "member_titles": row["title"],
                "all_year_rank": pd.NA,
                "all_year_score": pd.NA,
                "post_2000_rank": pd.NA,
                "post_2000_score": pd.NA,
            },
        )
        rank_column = "all_year_rank" if row["cohort"] == "all_years" else "post_2000_rank"
        score_column = "all_year_score" if row["cohort"] == "all_years" else "post_2000_score"
        candidate[rank_column] = row["rank"]
        candidate[score_column] = row["adjusted_rating"]

    template = pd.DataFrame(candidates.values())
    if template.empty:
        template = pd.DataFrame(
            columns=[
                "candidate_id",
                "candidate_type",
                "candidate_name",
                "collection_id",
                "member_tmdb_ids",
                "member_titles",
                "all_year_rank",
                "all_year_score",
                "post_2000_rank",
                "post_2000_score",
            ]
        )
    for column in OFFER_FIELDS:
        template[column] = pd.NA
    return template.sort_values(
        ["candidate_type", "all_year_rank", "post_2000_rank", "candidate_name"],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)


def _offers_are_populated(path: Path) -> bool:
    if not path.exists():
        return False
    existing = pd.read_csv(path)
    for column in OFFER_FIELDS:
        if column in existing and existing[column].map(
            lambda value: pd.notna(value) and bool(str(value).strip())
        ).any():
            return True
    return False


def _complete_offer_count(offers: pd.DataFrame) -> int:
    if not all(column in offers for column in OFFER_FIELDS):
        return 0
    # Count complete rows individually; one incomplete quote should not zero the rest.
    populated = pd.DataFrame(
        {
            column: offers[column].map(
                lambda value: pd.notna(value) and bool(str(value).strip())
            )
            for column in OFFER_FIELDS
        },
        index=offers.index,
    )
    return int(populated.all(axis=1).sum())


def build_data_diagnosis(
    movies: pd.DataFrame,
    acquisition_log: pd.DataFrame,
    offers: pd.DataFrame,
) -> pd.DataFrame:
    """Rank observed data and decision risks with evidence and impacts."""
    source_count = len(acquisition_log)
    success_count = int(acquisition_log["status"].eq("success").sum())
    valid_unique_count = int(
        acquisition_log.loc[
            acquisition_log["status"].isin(["success", "api_error"]), "tmdb_id"
        ].nunique()
    )
    unresolved = acquisition_log.loc[
        acquisition_log["status"].eq("api_error")
        & ~acquisition_log["used_cached_data"].fillna(False).astype(bool)
    ]
    invalid_count = int(acquisition_log["status"].eq("invalid").sum())
    duplicate_count = int(acquisition_log["status"].eq("duplicate").sum())
    complete_offer_count = _complete_offer_count(offers)
    collection_unknown = (
        len(movies)
        if "collection_metadata_status" not in movies
        else int(movies["collection_metadata_status"].ne("present").sum())
    )
    rows = [
        {
            "risk_rank": 1,
            "severity": "Critical",
            "issue": "No verified licensing offers",
            "evidence": (
                f"{complete_offer_count} of {len(offers)} negotiation candidates have "
                "all required price, rights, scope, date, and source fields."
            ),
            "candidates_affected": len(offers) - complete_offer_count,
            "recommendation_impact": (
                "No $14M bid or return can be validated; the current portfolio model "
                "must not be treated as a purchase recommendation."
            ),
            "action": "Obtain itemized fees and confirmed rights terms for each package.",
        },
        {
            "risk_rank": 2,
            "severity": "High",
            "issue": "Valid candidate IDs not retrieved",
            "evidence": (
                f"{success_count} of {valid_unique_count} unique valid IDs are in the "
                f"current data; {int(unresolved['tmdb_id'].nunique())} remain unresolved."
            ),
            "candidates_affected": int(unresolved["tmdb_id"].nunique()),
            "recommendation_impact": (
                "Missing titles could change ratings, talent rankings, or collection "
                "membership; their dollar effect cannot be estimated from available data."
            ),
            "action": "Investigate failures and include them in the next refresh.",
        },
        {
            "risk_rank": 3,
            "severity": "High",
            "issue": "Collection metadata incomplete",
            "evidence": (
                f"{collection_unknown} of {len(movies)} analyzed titles lack confirmed "
                "collection metadata."
            ),
            "candidates_affected": collection_unknown,
            "recommendation_impact": (
                "Unknown titles cannot safely be classified as franchise members or "
                "standalones, which can distort the bundle-versus-hit comparison."
            ),
            "action": "Refresh collection metadata before finalizing target lists.",
        },
        {
            "risk_rank": 4,
            "severity": "Medium",
            "issue": "Invalid source IDs",
            "evidence": f"{invalid_count} source records were non-numeric, non-integer, or non-positive.",
            "candidates_affected": invalid_count,
            "recommendation_impact": (
                "These records cannot be matched to titles; they may represent intended "
                "candidates that are absent from every ranking."
            ),
            "action": "Resolve each invalid source value with the data owner.",
        },
        {
            "risk_rank": 5,
            "severity": "Low",
            "issue": "Duplicate source IDs",
            "evidence": f"{duplicate_count} repeated input records were linked to their first occurrence.",
            "candidates_affected": duplicate_count,
            "recommendation_impact": (
                "No unique title is lost, but raw row counts overstate the candidate list "
                "unless duplicates are separated."
            ),
            "action": "Retain the row-level reconciliation and deduplicate by TMDb ID.",
        },
        {
            "risk_rank": 6,
            "severity": "High",
            "issue": "Audience ratings are not deal economics",
            "evidence": (
                "The dataset contains ratings, votes, popularity, and theatrical "
                "budget/revenue, but no license fees or verified rights offers."
            ),
            "candidates_affected": len(movies),
            "recommendation_impact": (
                "An audience-based ranking cannot show whether a title is affordable, "
                "available, or likely to return a profit."
            ),
            "action": "Treat the ranking as a negotiation shortlist, not a valuation.",
        },
    ]
    return pd.DataFrame(rows).sort_values("risk_rank").reset_index(drop=True)


def _names(frame: pd.DataFrame, cohort: str, column: str, limit: int) -> list[str]:
    selected = frame.loc[frame["cohort"].eq(cohort), column]
    return selected.head(limit).astype(str).tolist()


def _write_decision_notes(
    movies: pd.DataFrame,
    log: pd.DataFrame,
    franchises: pd.DataFrame,
    standalones: pd.DataFrame,
    talent: pd.DataFrame,
    diagnosis: pd.DataFrame,
) -> None:
    all_franchises = franchises.loc[franchises["cohort"].eq("all_years")]
    modern_franchises = franchises.loc[franchises["cohort"].eq("2000_onward")]
    all_standalones = standalones.loc[standalones["cohort"].eq("all_years")]
    modern_standalones = standalones.loc[standalones["cohort"].eq("2000_onward")]
    all_franchise_mean = (
        float(all_franchises.head(3)["mean_adjusted_rating"].mean())
        if not all_franchises.empty
        else np.nan
    )
    standalone_mean = (
        float(all_standalones.head(5)["adjusted_rating"].mean())
        if not all_standalones.empty
        else np.nan
    )
    preference = (
        "franchise packages"
        if np.isfinite(all_franchise_mean)
        and (not np.isfinite(standalone_mean) or all_franchise_mean >= standalone_mean)
        else "standalone titles"
    )
    source_records = len(log)
    success_count = int(log["status"].eq("success").sum())
    invalid_count = int(log["status"].eq("invalid").sum())
    duplicate_count = int(log["status"].eq("duplicate").sum())
    failed_ids = int(
        log.loc[
            log["status"].eq("api_error")
            & ~log["used_cached_data"].fillna(False).astype(bool),
            "tmdb_id",
        ].nunique()
    )
    note = f"""# Decision notes and assumptions

## Recommendation rule

The primary audience comparison recommends **{preference}** for initial quote requests. It compares the mean vote-adjusted score of the top three eligible franchise groups with the mean score of the top five eligible standalone titles. The 2000-onward comparison is shown separately; Finance's view is not substituted for the all-years view.

## Scoring and grouping assumptions

- Each title's vote-adjusted score shrinks its average audience rating toward the dataset mean. The shrinkage strength is the median positive vote count in the analyzed set. This reduces the influence of a high score with few votes; it does not predict license demand or revenue.
- A franchise bundle is a TMDb collection with at least two analyzed titles in the relevant cohort. Bundles are ranked by mean adjusted score, with total score and votes as tie-breakers. Mean score avoids automatically favoring longer collections; the package's total score is also reported.
- A title is called standalone only when the source explicitly includes collection metadata and reports no collection. Missing collection metadata is classified as unknown, not standalone.
- The top-billed actor is the first cast member in source billing order. Billing order is only a proxy for lead status.
- Talent signals include directors and top-billed actors with at least three analyzed titles. Mean score, spread, title count, and vote support are descriptive associations, not evidence that talent causes licensing success.
- The $14M budget-share figure in the deal note distributes budget in proportion to adjusted audience score across the eight primary negotiation targets. This assumes score points have equal additive value. It is a planning anchor only, not a market valuation or profit estimate.

## Candidate reconciliation

- {source_records} source records were logged.
- {success_count} unique movies were retrieved into the current analysis.
- {duplicate_count} duplicate source rows were linked to earlier records; they do not represent unique missing movies.
- {invalid_count} source IDs could not be interpreted as positive integer TMDb IDs.
- {failed_ids} valid unique IDs remain unresolved in the current acquisition log.
- {len(movies)} titles made the current analysis. Unresolved or invalid records could alter rankings; their financial effect is unknown.

## Risk and operational assumptions

The highest-ranked data risk is absent licensing price and rights evidence. Without it, no actual purchase decision can be defended. The current report also excludes titles whose collection metadata is not confirmed from franchise/standalone classification.

Earlier refreshes returned intermittent HTTP 401 errors; later runs succeeded after bounded retries. The current acquisition log is the source of truth for this run. Cached records are retained on refresh failures and marked in the log. This is the improvement beyond the brief: Adjoa can refresh quarterly without a transient API failure silently deleting previously acquired titles.

The pipeline scales across the 500-film synthetic test, but the live API may still return not-found or authorization errors. Those rows remain visible in the reconciliation file. Recheck them on each refresh rather than assuming a failed request means the title is permanently unavailable.
"""
    DECISION_NOTES_PATH.write_text(note, encoding="utf-8")


def _write_client_memo(
    movies: pd.DataFrame,
    log: pd.DataFrame,
    franchises: pd.DataFrame,
    standalones: pd.DataFrame,
    talent: pd.DataFrame,
    offers: pd.DataFrame,
) -> None:
    all_franchises = franchises.loc[franchises["cohort"].eq("all_years")]
    modern_franchises = franchises.loc[franchises["cohort"].eq("2000_onward")]
    all_standalones = standalones.loc[standalones["cohort"].eq("all_years")]
    modern_standalones = standalones.loc[standalones["cohort"].eq("2000_onward")]
    top_bundle = all_franchises.iloc[0] if not all_franchises.empty else None
    all_franchise_mean = (
        float(all_franchises.head(3)["mean_adjusted_rating"].mean())
        if not all_franchises.empty
        else np.nan
    )
    standalone_mean = (
        float(all_standalones.head(5)["adjusted_rating"].mean())
        if not all_standalones.empty
        else np.nan
    )
    recommend_bundles = bool(
        np.isfinite(all_franchise_mean)
        and (not np.isfinite(standalone_mean) or all_franchise_mean >= standalone_mean)
    )
    recommendation = (
        "Quote franchise bundles first; buy one only if its itemized terms are better."
        if recommend_bundles
        else "Quote standalones first; consider a bundle only if its per-title terms are better."
    )

    def franchise_lines(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "- No confirmed multi-title franchise qualified."
        return "\n".join(
            f"- **{row.collection_name}** — {row.title_count} films; audience score "
            f"{row.mean_adjusted_rating:.2f} across {row.total_votes:,} votes."
            for row in frame.head(3).itertuples()
        )

    def standalone_lines(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "- No confirmed standalone title qualified."
        return "\n".join(
            f"- **{row.title}** — score {row.adjusted_rating:.2f}; "
            f"{int(row.vote_count):,} votes."
            for row in frame.head(5).itertuples()
        )

    def talent_line(role: str) -> str:
        rows = talent.loc[
            talent["cohort"].eq("all_years") & talent["role"].eq(role)
        ].head(3)
        if rows.empty:
            return "None met the three-title minimum."
        return "; ".join(
            f"{row.talent} ({row.title_count}; {row.mean_adjusted_rating:.2f})"
            for row in rows.itertuples()
        )

    if top_bundle is not None:
        slate_scores = float(all_franchises.head(3)["total_adjusted_rating"].sum())
        slate_scores += float(all_standalones.head(5)["adjusted_rating"].sum())
        budget_share = (
            float(top_bundle["total_adjusted_rating"]) / slate_scores
            if slate_scores > 0
            else 0.0
        )
        budget_anchor = 14_000_000 * budget_share
        deal_note = (
            f"For **{top_bundle['collection_name']}**, the score-share amount is "
            f"**${budget_anchor:,.0f} ({budget_share:.1%} of the budget)**, not a bid. "
            f"Key measure: score **{top_bundle['mean_adjusted_rating']:.2f}** across "
            f"{top_bundle['total_votes']:,} votes. Get a verified quote before spending."
        )
    else:
        deal_note = "No confirmed franchise qualified, so a package amount cannot be estimated."

    complete_offer_count = _complete_offer_count(offers)
    unresolved_count = int(
        log.loc[
            log["status"].eq("api_error")
            & ~log["used_cached_data"].fillna(False).astype(bool),
            "tmdb_id",
        ].nunique()
    )
    modern_franchise_lead = (
        str(modern_franchises.iloc[0]["collection_name"])
        if not modern_franchises.empty
        else "none qualified"
    )
    modern_standalone_lead = (
        str(modern_standalones.iloc[0]["title"])
        if not modern_standalones.empty
        else "none qualified"
    )
    all_franchise_lead = (
        str(all_franchises.iloc[0]["collection_name"])
        if not all_franchises.empty
        else "none qualified"
    )
    all_standalone_lead = (
        str(all_standalones.iloc[0]["title"])
        if not all_standalones.empty
        else "none qualified"
    )
    new_fetch_count = int(log["status"].eq("success").sum())
    cached_count = int(log["used_cached_data"].fillna(False).astype(bool).sum())
    duplicate_count = int(log["status"].eq("duplicate").sum())
    invalid_count = int(log["status"].eq("invalid").sum())
    memo = f"""# Memo to Kwame

**From:** Content Analysis Team  
**Date:** {date.today():%d %B %Y}  
**Subject:** Negotiation priorities for the $14M content budget

## What I found

Scores account for vote volume. All-years averages: **{standalone_mean:.2f}**
for the top five standalones versus **{all_franchise_mean:.2f}** for the top
three franchises. Since 2000, the leaders are **{modern_franchise_lead}** and
**{modern_standalone_lead}**; across all years, they are {all_franchise_lead}
and {all_standalone_lead}.

## What I built

| What you asked for | Status | Evidence |
|---|---|---|
| Compare both time periods | Complete | {len(movies)} films; all years and post-1999. |
| Account for candidate records | Gaps noted | {len(log)} rows: {new_fetch_count} fetched, {cached_count} reused, {duplicate_count} duplicates, {invalid_count} invalid, {unresolved_count} unresolved. |
| Shortlists and talent signals | Complete | Three franchises, five standalones, recurring directors and actors. |
| Check the budget | Waiting for offers | {complete_offer_count}/{len(offers)} offers have complete terms. |

## What I recommend

{recommendation} These scores show audience interest, not financial return.

**Three franchise targets:**  
{franchise_lines(all_franchises)}

**Five standalone targets** (all confirmed outside a collection; score, votes):  
{standalone_lines(all_standalones)}

**Repeated talent** (films, score): Directors — {talent_line('director')};
first-billed actors — {talent_line('top_billed_actor')}. Billing is only a
lead-actor clue, not proof of success.

**Deal note:** {deal_note}

## What I could not stand behind

No license fees or confirmed rights were supplied; I cannot recommend a bid or
return. {unresolved_count} valid IDs remain unresolved and could change the
rankings; their dollar impact is unknown. The score-share amount is only a
planning comparison.
"""
    CLIENT_MEMO_PATH.write_text(memo, encoding="utf-8")


def run_recommendations(
    movies_path: str | Path = MOVIES_PATH,
    acquisition_log_path: str | Path = ACQUISITION_LOG_PATH,
    offers_path: str | Path = OFFERS_PATH,
) -> dict[str, pd.DataFrame]:
    movies = pd.read_csv(movies_path)
    acquisition_log = pd.read_csv(acquisition_log_path)
    franchises = build_franchise_targets(movies)
    standalones = build_standalone_shortlist(movies)
    talent = build_talent_signals(movies)
    offers = build_negotiation_template(franchises, standalones)

    offer_path = Path(offers_path)
    if not _offers_are_populated(offer_path):
        offer_path.parent.mkdir(parents=True, exist_ok=True)
        offers.to_csv(offer_path, index=False)
    else:
        # Keep quotes that a user has already entered.
        offers = pd.read_csv(offer_path)

    diagnosis = build_data_diagnosis(movies, acquisition_log, offers)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    franchises.to_csv(FRANCHISE_PATH, index=False)
    standalones.to_csv(STANDALONE_PATH, index=False)
    talent.to_csv(TALENT_PATH, index=False)
    diagnosis.to_csv(DIAGNOSIS_PATH, index=False)
    acquisition_log.to_csv(RECONCILIATION_PATH, index=False)
    _write_decision_notes(
        movies, acquisition_log, franchises, standalones, talent, diagnosis
    )
    _write_client_memo(movies, acquisition_log, franchises, standalones, talent, offers)
    return {
        "franchises": franchises,
        "standalones": standalones,
        "talent": talent,
        "diagnosis": diagnosis,
        "offers": offers,
    }


def main() -> None:
    outputs = run_recommendations()
    print("Franchise targets:")
    print(outputs["franchises"].to_string(index=False))
    print("\nStandalone shortlist:")
    print(outputs["standalones"].to_string(index=False))
    print("\nTalent signals:")
    print(outputs["talent"].to_string(index=False))
    print(f"\nClient memo: {CLIENT_MEMO_PATH}")


if __name__ == "__main__":
    main()
