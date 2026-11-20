"""Tests for the documented end-to-end pipeline."""

from unittest.mock import patch

import pandas as pd
import pytest

from src import pipeline


def test_pipeline_runs_stages_in_order_and_returns_outputs():
    # Fake each stage so the test checks order without calling the live API.
    events = []
    movies = pd.DataFrame({"tmdb_id": [1]})
    log = pd.DataFrame({"status": ["success"]})
    ratings = pd.DataFrame({"cohort": ["all_years"]})
    quality = pd.DataFrame({"metric": ["film_rows"]})
    recommendations = {"franchises": pd.DataFrame({"cohort": ["all_years"]})}
    license_summary = pd.DataFrame({"decision_status": ["no_eligible_offers"]})
    license_candidates = pd.DataFrame()

    with (
        patch.object(pipeline, "load_dotenv"),
        patch.object(pipeline.os, "getenv", return_value="offline-test-key"),
        patch.object(pipeline, "load_raw_movie_ids", return_value=["1"]),
        patch.object(
            pipeline,
            "acquire_movies",
            side_effect=lambda ids, key: events.append("acquire") or movies,
        ),
        patch.object(pipeline.pd, "read_csv", return_value=log),
        patch.object(
            pipeline,
            "run_analysis",
            side_effect=lambda: events.append("analyze") or (ratings, quality),
        ),
        patch.object(
            pipeline,
            "run_recommendations",
            side_effect=lambda: events.append("recommend") or recommendations,
        ),
        patch.object(
            pipeline,
            "run_license_decision",
            side_effect=lambda: events.append("license")
            or (license_summary, license_candidates),
        ),
    ):
        result = pipeline.run_pipeline()

    assert events == ["acquire", "analyze", "recommend", "license"]
    assert result["movies"] is movies
    assert result["license_summary"] is license_summary


def test_pipeline_reports_missing_api_key_before_acquiring():
    # Stop before acquisition when the API key is not configured.
    with (
        patch.object(pipeline, "load_dotenv"),
        patch.object(pipeline.os, "getenv", return_value=None),
        patch.object(pipeline, "acquire_movies") as acquire_movies,
    ):
        with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
            pipeline.run_pipeline()

    acquire_movies.assert_not_called()
