"""Tests for the NumPy-based analysis summaries."""

import math

import pandas as pd

from src.analyze import (
    build_content_shortlist,
    build_data_quality_summary,
    build_offer_template,
    build_rating_summary,
)


def test_rating_summary_compares_all_years_and_2000_onward():
    # The out-of-range rating should be excluded from both summaries.
    movies = pd.DataFrame(
        {
            "release_year": [1999, 2000, 2010, 2020],
            "vote_average": [8.0, 6.0, 10.0, 12.0],
            "vote_count": [10, 30, 0, 5],
        }
    )

    summary = build_rating_summary(movies).set_index("cohort")

    assert summary.loc["all_years", "film_count"] == 3
    assert math.isclose(summary.loc["all_years", "mean_vote_average"], 8.0)
    assert math.isclose(summary.loc["all_years", "vote_weighted_average"], 6.5)
    assert summary.loc["2000_onward", "film_count"] == 2
    assert summary.loc["2000_onward", "total_votes"] == 30


def test_quality_summary_reports_duplicates_missing_years_and_year_cohorts():
    movies = pd.DataFrame(
        {
            "tmdb_id": [1, 1, 3],
            "release_year": [1999, 2000, None],
            "title": ["Old", None, "Unknown year"],
        }
    )

    quality = build_data_quality_summary(movies).set_index("metric")["value"]

    assert quality["film_rows"] == 3
    assert quality["duplicate_tmdb_ids"] == 1
    assert quality["missing_release_year"] == 1
    assert quality["films_before_2000"] == 1
    assert quality["films_2000_onward"] == 1
    assert quality["missing_values_title"] == 1


def test_quality_summary_counts_zero_financial_values_without_reclassifying_them():
    # Zero is kept as a value and counted for review.
    movies = pd.DataFrame({"budget": [0, 100, None], "revenue": [0, 200, 300]})

    quality = build_data_quality_summary(movies).set_index("metric")["value"]

    assert quality["zero_budget_values"] == 1
    assert quality["zero_revenue_values"] == 1


def test_content_shortlist_smooths_low_vote_ratings_and_separates_year_cohorts():
    # One perfect vote should not outrank a strong rating with many votes.
    movies = pd.DataFrame(
        {
            "tmdb_id": [1, 2, 3],
            "title": ["Low vote", "Supported title", "Classic"],
            "release_year": [2022, 2021, 1999],
            "genres": ["Drama", "Comedy", "Drama"],
            "vote_average": [10.0, 9.0, 7.0],
            "vote_count": [1, 100, 20],
            "popularity": [1.0, 2.0, 3.0],
        }
    )

    shortlist = build_content_shortlist(movies, limit=2)
    all_years = shortlist[shortlist["cohort"] == "all_years"]
    modern = shortlist[shortlist["cohort"] == "2000_onward"]

    assert all_years.iloc[0]["title"] == "Supported title"
    assert "Classic" not in set(modern["title"])
    assert modern.iloc[0]["rank"] == 1
    assert shortlist["prior_vote_count"].eq(20).all()


def test_content_shortlist_rejects_non_positive_limit():
    movies = pd.DataFrame(
        {
            "tmdb_id": [1],
            "title": ["Movie"],
            "release_year": [2020],
            "vote_average": [8.0],
            "vote_count": [10],
        }
    )

    try:
        build_content_shortlist(movies, limit=0)
    except ValueError as exc:
        assert "positive integer" in str(exc)
    else:
        raise AssertionError("A zero shortlist limit must be rejected")


def test_offer_template_unifies_candidates_and_keeps_offer_fields_blank():
    # The same title gets one quote row even if it appears in both cohorts.
    shortlist = pd.DataFrame(
        {
            "cohort": ["all_years", "all_years", "2000_onward", "2000_onward"],
            "rank": [1, 2, 1, 2],
            "tmdb_id": [1, 2, 1, 3],
            "title": ["Shared title", "Classic", "Shared title", "Modern title"],
        }
    )

    offers = build_offer_template(shortlist).set_index("tmdb_id")

    assert set(offers.index) == {1, 2, 3}
    assert offers.loc[1, "all_year_rank"] == 1
    assert offers.loc[1, "post_2000_rank"] == 1
    assert pd.isna(offers.loc[2, "post_2000_rank"])
    assert offers["license_fee_usd"].isna().all()
    assert offers["rights_available"].isna().all()
