"""Tests for the documented end-to-end pipeline."""

from unittest.mock import patch

import pandas as pd
import pytest

from src.acquire import AcquisitionSettings
from src import pipeline


def test_pipeline_runs_stages_in_order_and_returns_outputs():
    # Fake each stage so the test checks order without calling the live API.
    events = []
    movies = pd.DataFrame({"tmdb_id": [1]})
    log = pd.DataFrame({"status": ["success"]})
    ratings = pd.DataFrame({"cohort": ["all_years"]})
    quality = pd.DataFrame({"metric": ["film_rows"]})
    offers = pd.DataFrame({"candidate_id": ["title:1"]})
    recommendations = {
        "franchises": pd.DataFrame({"cohort": ["all_years"]}),
        "offers": offers,
    }
    license_summary = pd.DataFrame({"decision_status": ["no_eligible_offers"]})
    license_candidates = pd.DataFrame()

    def analyze(*, movie_data):
        assert movie_data is movies
        events.append("analyze")
        return ratings, quality

    def recommend(*, movie_data, acquisition_log_data):
        assert movie_data is movies
        assert acquisition_log_data is log
        events.append("recommend")
        return recommendations

    def license(*, offer_data):
        assert offer_data is offers
        events.append("license")
        return license_summary, license_candidates

    def acquire(ids, key, **settings):
        assert ids == ["1"]
        assert key == "offline-test-key"
        assert settings == {
            "delay_seconds": 0.25,
            "max_attempts": 3,
            "backoff_seconds": 1.0,
        }
        events.append("acquire")
        return movies

    with (
        patch.object(pipeline, "load_dotenv"),
        patch.object(pipeline.os, "getenv", return_value="offline-test-key"),
        patch.object(
            pipeline,
            "acquisition_settings_from_environment",
            return_value=AcquisitionSettings(),
        ),
        patch.object(pipeline, "load_raw_movie_ids", return_value=["1"]),
        patch.object(
            pipeline,
            "acquire_movies",
            side_effect=acquire,
        ),
        patch.object(pipeline.pd, "read_csv", return_value=log),
        patch.object(
            pipeline,
            "run_analysis",
            side_effect=analyze,
        ),
        patch.object(
            pipeline,
            "run_recommendations",
            side_effect=recommend,
        ),
        patch.object(
            pipeline,
            "run_license_decision",
            side_effect=license,
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
        patch.object(
            pipeline,
            "acquisition_settings_from_environment",
            return_value=AcquisitionSettings(),
        ),
        patch.object(pipeline, "acquire_movies") as acquire_movies,
    ):
        with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
            pipeline.run_pipeline()

    acquire_movies.assert_not_called()


def test_pipeline_stops_when_acquisition_log_is_missing(tmp_path):
    with (
        patch.object(pipeline, "load_dotenv"),
        patch.object(pipeline.os, "getenv", return_value="offline-test-key"),
        patch.object(
            pipeline,
            "acquisition_settings_from_environment",
            return_value=AcquisitionSettings(),
        ),
        patch.object(pipeline, "load_raw_movie_ids", return_value=["1"]),
        patch.object(
            pipeline,
            "acquire_movies",
            return_value=pd.DataFrame({"tmdb_id": [1]}),
        ),
        patch.object(
            pipeline,
            "ACQUISITION_LOG_PATH",
            tmp_path / "missing-acquisition-log.csv",
        ),
        patch.object(pipeline, "run_analysis") as run_analysis,
    ):
        with pytest.raises(FileNotFoundError, match="Acquisition did not create"):
            pipeline.run_pipeline()

    run_analysis.assert_not_called()
