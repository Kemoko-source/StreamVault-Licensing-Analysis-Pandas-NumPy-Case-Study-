"""Summarize TMDb coverage, data quality, and audience ratings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_movies.csv"
REPORT_DIR = PROJECT_ROOT / "reports"
RATING_SUMMARY_PATH = REPORT_DIR / "rating_summary.csv"
QUALITY_REPORT_PATH = REPORT_DIR / "data_quality_summary.csv"
CONTENT_SHORTLIST_PATH = REPORT_DIR / "content_shortlist.csv"
OFFER_TEMPLATE_PATH = PROJECT_ROOT / "data" / "raw" / "license_offers_template.csv"
QUALITY_MISSINGNESS_FIELDS = (
    "tmdb_id",
    "title",
    "release_year",
    "vote_average",
    "vote_count",
    "popularity",
    "genres",
    "budget",
    "revenue",
    "collection_id",
    "collection_name",
    "collection_metadata_status",
    "director",
    "top_billed_actor",
)


def build_rating_summary(movies: pd.DataFrame) -> pd.DataFrame:
    """Compare TMDb ratings for the full dataset and films from 2000 onward."""
    required = {"release_year", "vote_average", "vote_count"}
    missing_columns = required.difference(movies.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    years = pd.to_numeric(movies["release_year"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    ratings = pd.to_numeric(movies["vote_average"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    votes = pd.to_numeric(movies["vote_count"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )

    # Exclude ratings and vote counts outside their expected ranges.
    valid = (
        np.isfinite(ratings)
        & np.isfinite(votes)
        & (ratings >= 0)
        & (ratings <= 10)
        & (votes >= 0)
    )
    cohorts = {
        "all_years": valid,
        "2000_onward": valid & np.isfinite(years) & (years >= 2000),
    }

    rows = []
    for cohort, mask in cohorts.items():
        cohort_ratings = ratings[mask]
        cohort_votes = votes[mask]
        positive_vote_weights = cohort_votes > 0
        if positive_vote_weights.any():
            weighted_average = float(
                np.average(
                    cohort_ratings[positive_vote_weights],
                    weights=cohort_votes[positive_vote_weights],
                )
            )
        else:
            weighted_average = np.nan
        rows.append(
            {
                "cohort": cohort,
                "film_count": int(cohort_ratings.size),
                "mean_vote_average": float(np.mean(cohort_ratings))
                if cohort_ratings.size
                else np.nan,
                "median_vote_average": float(np.median(cohort_ratings))
                if cohort_ratings.size
                else np.nan,
                "vote_weighted_average": weighted_average,
                "total_votes": int(np.sum(cohort_votes)),
            }
        )

    return pd.DataFrame(rows)


def build_content_shortlist(movies: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    """Rank titles by vote-adjusted TMDb ratings for both required year cohorts."""
    required = {"tmdb_id", "title", "release_year", "vote_average", "vote_count"}
    missing_columns = required.difference(movies.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")
    if isinstance(limit, bool) or not isinstance(limit, (int, np.integer)) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    ids = pd.to_numeric(movies["tmdb_id"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    years = pd.to_numeric(movies["release_year"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    ratings = pd.to_numeric(movies["vote_average"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    votes = pd.to_numeric(movies["vote_count"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    titles = movies["title"].astype("string").str.strip()

    valid = (
        np.isfinite(ids)
        & (ids > 0)
        & (ids % 1 == 0)
        & titles.notna().to_numpy()
        & titles.ne("").fillna(False).to_numpy(dtype=bool)
        & np.isfinite(ratings)
        & (ratings >= 0)
        & (ratings <= 10)
        & np.isfinite(votes)
        & (votes >= 0)
        & (votes % 1 == 0)
    )
    if not valid.any():
        return pd.DataFrame(
            columns=[
                "cohort",
                "rank",
                "tmdb_id",
                "title",
                "release_year",
                "genres",
                "vote_average",
                "vote_count",
                "popularity",
                "adjusted_rating",
                "prior_mean_rating",
                "prior_vote_count",
            ]
        )

    # Pull low-vote ratings toward the catalog average to reduce noisy extremes.
    prior_mean = float(np.mean(ratings[valid]))
    positive_votes = votes[valid & (votes > 0)]
    # Median positive votes is a robust, representative support level for shrinkage.
    prior_vote_count = float(np.median(positive_votes)) if positive_votes.size else 0.0
    denominator = votes + prior_vote_count
    adjusted = np.full(len(movies), prior_mean, dtype=float)
    np.divide(
        votes * ratings + prior_vote_count * prior_mean,
        denominator,
        out=adjusted,
        where=valid & (denominator > 0),
    )

    # Keep the full-catalog view separate from Finance's post-1999 view.
    cohorts = {
        "all_years": valid,
        "2000_onward": valid & np.isfinite(years) & (years >= 2000),
    }
    rows = []
    for cohort, mask in cohorts.items():
        positions = np.flatnonzero(mask)
        cohort_rows = pd.DataFrame(
            {
                "tmdb_id": ids[positions].astype("int64"),
                "title": titles.iloc[positions].astype(str).to_numpy(),
                "release_year": pd.Series(years[positions]).astype("Int64"),
                "genres": movies["genres"].iloc[positions].to_numpy()
                if "genres" in movies
                else pd.NA,
                "vote_average": ratings[positions],
                "vote_count": votes[positions].astype("int64"),
                "popularity": pd.to_numeric(
                    movies["popularity"].iloc[positions], errors="coerce"
                ).to_numpy(dtype=float)
                if "popularity" in movies
                else np.nan,
                "adjusted_rating": adjusted[positions],
                "prior_mean_rating": prior_mean,
                "prior_vote_count": prior_vote_count,
            }
        )
        cohort_rows = cohort_rows.sort_values(
            ["adjusted_rating", "vote_count", "tmdb_id"],
            ascending=[False, False, True],
            kind="mergesort",
        ).head(limit)
        cohort_rows.insert(0, "cohort", cohort)
        cohort_rows.insert(1, "rank", np.arange(1, len(cohort_rows) + 1))
        rows.append(cohort_rows)

    return pd.concat(rows, ignore_index=True)


def build_offer_template(shortlist: pd.DataFrame) -> pd.DataFrame:
    """Prepare a unique quote-request list with both cohort ranks and blank offer fields."""
    required = {"cohort", "rank", "tmdb_id", "title"}
    missing_columns = required.difference(shortlist.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    all_years = shortlist.loc[
        shortlist["cohort"] == "all_years", ["tmdb_id", "title", "rank"]
    ].rename(columns={"rank": "all_year_rank"})
    modern = shortlist.loc[
        shortlist["cohort"] == "2000_onward", ["tmdb_id", "title", "rank"]
    ].rename(columns={"rank": "post_2000_rank"})

    # An outer merge keeps titles that appear in only one time window.
    offers = all_years.merge(modern, on="tmdb_id", how="outer", suffixes=("_all", "_post"))
    offers["title"] = offers["title_all"].combine_first(offers["title_post"])
    offers = offers.drop(columns=["title_all", "title_post"])
    for column in ("all_year_rank", "post_2000_rank"):
        offers[column] = pd.to_numeric(offers[column], errors="coerce").astype("Int64")
    offers = offers.sort_values(
        ["post_2000_rank", "all_year_rank", "tmdb_id"],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)

    for column in (
        "license_fee_usd",
        "rights_available",
        "territory",
        "license_start_date",
        "license_end_date",
        "quote_date",
        "offer_source",
    ):
        offers[column] = pd.NA

    return offers[
        [
            "tmdb_id",
            "title",
            "all_year_rank",
            "post_2000_rank",
            "license_fee_usd",
            "rights_available",
            "territory",
            "license_start_date",
            "license_end_date",
            "quote_date",
            "offer_source",
        ]
    ]


def build_data_quality_summary(movies: pd.DataFrame) -> pd.DataFrame:
    """Report dataset size, duplicate IDs, year coverage, and missing values."""
    rows = [
        {"metric": "film_rows", "value": len(movies)},
        {
            "metric": "duplicate_tmdb_ids",
            "value": int(movies["tmdb_id"].duplicated().sum())
            if "tmdb_id" in movies
            else np.nan,
        },
    ]

    if "release_year" in movies:
        years = pd.to_numeric(movies["release_year"], errors="coerce")
        rows.extend(
            [
                {"metric": "missing_release_year", "value": int(years.isna().sum())},
                {"metric": "films_before_2000", "value": int((years < 2000).sum())},
                {"metric": "films_2000_onward", "value": int((years >= 2000).sum())},
                {
                    "metric": "earliest_release_year",
                    "value": int(years.min()) if years.notna().any() else np.nan,
                },
                {
                    "metric": "latest_release_year",
                    "value": int(years.max()) if years.notna().any() else np.nan,
                },
            ]
        )

    for column in ("budget", "revenue"):
        if column in movies:
            values = pd.to_numeric(movies[column], errors="coerce")
            rows.append(
                {"metric": f"zero_{column}_values", "value": int(values.eq(0).sum())}
            )

    # Report missing values by field so problems are easy to trace.
    for column in QUALITY_MISSINGNESS_FIELDS:
        if column not in movies:
            continue
        rows.append(
            {
                "metric": f"missing_values_{column}",
                "value": int(movies[column].isna().sum()),
            }
        )
    return pd.DataFrame(rows)


def run_analysis(
    input_path: str | Path = INPUT_PATH,
    report_dir: str | Path = REPORT_DIR,
    *,
    movie_data: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Analyze provided movies or load them, then write reproducible summaries."""
    movies = movie_data.copy() if movie_data is not None else pd.read_csv(input_path)
    rating_summary = build_rating_summary(movies)
    quality_summary = build_data_quality_summary(movies)
    content_shortlist = build_content_shortlist(movies)
    offer_template = build_offer_template(content_shortlist)

    destination = Path(report_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if not OFFER_TEMPLATE_PATH.exists():
        OFFER_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        offer_template.to_csv(OFFER_TEMPLATE_PATH, index=False)
    rating_summary.to_csv(destination / RATING_SUMMARY_PATH.name, index=False)
    quality_summary.to_csv(destination / QUALITY_REPORT_PATH.name, index=False)
    content_shortlist.to_csv(destination / CONTENT_SHORTLIST_PATH.name, index=False)
    return rating_summary, quality_summary


def main() -> None:
    ratings, quality = run_analysis()
    print("Rating summary:")
    print(ratings.to_string(index=False))
    print("\nData quality summary:")
    print(quality.to_string(index=False))
    print("\nAudience-evidence shortlist (not a licensing ROI ranking):")
    print(pd.read_csv(CONTENT_SHORTLIST_PATH).to_string(index=False))
    print(
        "\nTMDb ratings and popularity are descriptive signals, not evidence "
        "of licensing cost, rights availability, or expected return."
    )


if __name__ == "__main__":
    main()
