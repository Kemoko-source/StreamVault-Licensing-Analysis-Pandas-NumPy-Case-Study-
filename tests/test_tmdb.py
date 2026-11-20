"""Focused tests for the TMDb acquisition module."""

from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd
import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.acquire import acquire_movies, clean_movie_data, fetch_movie, load_movie_ids


def assert_fetch_configuration(api_key, session, settings, expected_key):
    assert api_key == expected_key
    assert isinstance(session, requests.Session)
    assert settings == {"max_attempts": 3, "backoff_seconds": 1.0}


def test_load_movie_ids_filters_invalid_and_duplicate_values(tmp_path):
    path = tmp_path / "ids.csv"
    pd.DataFrame({"tmdb_id": ["550", "550", "-1", "N/A", "tt0468569"]}).to_csv(
        path, index=False
    )

    assert load_movie_ids(path) == [550]


def test_clean_movie_data_normalizes_types_and_bad_values():
    movies = pd.DataFrame(
        [{
            "tmdb_id": "550",
            "title": "Fight Club",
            "release_date": "1999-10-15",
            "runtime": "139",
            "budget": "-1",
            "revenue": "100000000",
            "popularity": "61.5",
            "vote_average": "8.4",
            "vote_count": "30000",
        }]
    )

    cleaned = clean_movie_data(movies)

    assert cleaned.loc[0, "tmdb_id"] == 550
    assert cleaned.loc[0, "release_year"] == 1999
    assert pd.isna(cleaned.loc[0, "budget"])
    assert cleaned.loc[0, "revenue"] == 100000000


def test_clean_movie_data_preserves_zero_financials_and_rejects_invalid_values():
    movies = pd.DataFrame(
        [
            {
                "tmdb_id": "550",
                "title": "  Fight Club  ",
                "runtime": "139.5",
                "budget": "0",
                "revenue": "0",
                "vote_average": "10.1",
                "vote_count": "20.5",
            },
            {
                "tmdb_id": "550.5",
                "title": "Invalid ID",
                "budget": "100",
                "revenue": "200",
            },
            {
                "tmdb_id": "551",
                "title": "   ",
                "budget": "100",
                "revenue": "200",
            },
        ]
    )

    cleaned = clean_movie_data(movies)

    assert len(cleaned) == 1
    assert cleaned.loc[0, "title"] == "Fight Club"
    assert cleaned.loc[0, "budget"] == 0
    assert cleaned.loc[0, "revenue"] == 0
    assert pd.isna(cleaned.loc[0, "runtime"])
    assert pd.isna(cleaned.loc[0, "vote_average"])
    assert pd.isna(cleaned.loc[0, "vote_count"])


def test_clean_movie_data_preserves_duplicate_ids_for_acquisition_reconciliation():
    movies = pd.DataFrame(
        [
            {"tmdb_id": 550, "title": "First copy"},
            {"tmdb_id": 550, "title": "Second copy"},
        ]
    )

    cleaned = clean_movie_data(movies)

    assert cleaned["tmdb_id"].tolist() == [550, 550]


def test_fetch_movie_extracts_collection_and_top_billed_actor():
    movie = {
        "title": "Sample",
        "belongs_to_collection": {"id": 99, "name": "Sample Collection"},
    }
    credits = {
        "cast": [{"name": "Lead Actor"}, {"name": "Supporting Actor"}],
        "crew": [{"job": "Director", "name": "Director Name"}],
    }

    with patch("src.acquire.tmdb_get", side_effect=[movie, credits]):
        record = fetch_movie(10, "test-key")

    assert record["collection_id"] == 99
    assert record["collection_name"] == "Sample Collection"
    assert record["collection_metadata_status"] == "present"
    assert record["top_billed_actor"] == "Lead Actor"


def test_fetch_movie_distinguishes_confirmed_standalone_from_missing_field():
    with patch(
        "src.acquire.tmdb_get",
        side_effect=[
            {"title": "Standalone", "belongs_to_collection": None},
            {"cast": [], "crew": []},
        ],
    ):
        standalone = fetch_movie(11, "test-key")
    with patch(
        "src.acquire.tmdb_get",
        side_effect=[{"title": "Unknown"}, {"cast": [], "crew": []}],
    ):
        unknown = fetch_movie(12, "test-key")

    assert standalone["collection_id"] is None
    assert standalone["collection_metadata_status"] == "present"
    assert unknown["collection_metadata_status"] == "missing"


def test_acquire_movies_logs_success_invalid_duplicate_and_api_failure(tmp_path):
    # Keep errors and duplicates in the log while fetching only unique valid IDs.
    def fake_fetch_movie(tmdb_id, api_key, session, **settings):
        assert_fetch_configuration(api_key, session, settings, "test-key")
        if tmdb_id == 680:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return {"tmdb_id": tmdb_id, "title": f"Movie {tmdb_id}"}

    log_path = tmp_path / "logs" / "acquisition.csv"
    with patch("src.acquire.fetch_movie", side_effect=fake_fetch_movie) as fetch_mock:
        movies = acquire_movies(
            [550, "N/A", "-1", "550", "680", "1.5"],
            "test-key",
            output_path=tmp_path / "movies.csv",
            delay_seconds=0,
            log_path=log_path,
        )

    log = pd.read_csv(log_path)
    assert movies["tmdb_id"].tolist() == [550]
    assert [call.args[0] for call in fetch_mock.call_args_list] == [550, 680]
    assert log["source_record"].tolist() == [1, 2, 3, 4, 5, 6]
    assert log["status"].tolist() == [
        "success",
        "invalid",
        "invalid",
        "duplicate",
        "api_error",
        "invalid",
    ]
    assert log.loc[1, "reason"] == "not_numeric"
    assert log.loc[3, "duplicate_of_record"] == 1
    assert log.loc[4, "reason"] == "http_404"
    assert log.loc[5, "reason"] == "not_integer"


def test_acquire_movies_retains_cached_rows_when_refresh_fails(tmp_path):
    # Failed refreshes keep the old row and mark that cached data was used.
    output_path = tmp_path / "movies.csv"
    pd.DataFrame(
        [
            {"tmdb_id": 1, "title": "Old title"},
            {"tmdb_id": 2, "title": "Cached title"},
        ]
    ).to_csv(output_path, index=False)

    def fake_fetch_movie(tmdb_id, api_key, session, **settings):
        assert_fetch_configuration(api_key, session, settings, "test-key")
        if tmdb_id == 2:
            response = requests.Response()
            response.status_code = 401
            raise requests.HTTPError(response=response)
        return {"tmdb_id": tmdb_id, "title": f"New title {tmdb_id}"}

    with patch("src.acquire.fetch_movie", side_effect=fake_fetch_movie):
        movies = acquire_movies(
            [1, 2, 3],
            "test-key",
            output_path=output_path,
            delay_seconds=0,
            log_path=tmp_path / "acquisition_log.csv",
        )

    saved = pd.read_csv(output_path).set_index("tmdb_id")
    log = pd.read_csv(tmp_path / "acquisition_log.csv").set_index("tmdb_id")
    assert len(movies) == 3
    assert saved.loc[1, "title"] == "New title 1"
    assert saved.loc[2, "title"] == "Cached title"
    assert saved.loc[3, "title"] == "New title 3"
    assert log.loc[2, "status"] == "api_error"
    assert bool(log.loc[2, "used_cached_data"])


def test_acquire_movies_logs_duplicate_cached_rows(tmp_path):
    output_path = tmp_path / "movies.csv"
    pd.DataFrame(
        [
            {"tmdb_id": 1, "title": "First copy"},
            {"tmdb_id": 1, "title": "Second copy"},
        ]
    ).to_csv(output_path, index=False)

    def failed_refresh(tmdb_id, api_key, session, **settings):
        assert_fetch_configuration(api_key, session, settings, "test-key")
        assert tmdb_id == 1
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError(response=response)

    log_path = tmp_path / "acquisition_log.csv"
    with patch("src.acquire.fetch_movie", side_effect=failed_refresh):
        movies = acquire_movies(
            [1],
            "test-key",
            output_path=output_path,
            delay_seconds=0,
            log_path=log_path,
        )

    log = pd.read_csv(log_path)
    assert movies["title"].tolist() == ["Second copy"]
    assert log.loc[0, "duplicate_movie_rows_removed"] == 1


def test_acquire_movies_raises_and_saves_log_when_no_records_remain(tmp_path):
    output_path = tmp_path / "movies.csv"
    pd.DataFrame([{"tmdb_id": 99, "title": "Stale movie"}]).to_csv(
        output_path,
        index=False,
    )

    def failed_refresh(tmdb_id, api_key, session, **settings):
        assert_fetch_configuration(api_key, session, settings, "test-key")
        assert tmdb_id == 1
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError(response=response)

    log_path = tmp_path / "acquisition_log.csv"
    with patch("src.acquire.fetch_movie", side_effect=failed_refresh):
        with pytest.raises(RuntimeError, match="existing movie file was left unchanged"):
            acquire_movies(
                [1],
                "test-key",
                output_path=output_path,
                delay_seconds=0,
                log_path=log_path,
            )

    assert pd.read_csv(output_path).loc[0, "title"] == "Stale movie"
    assert pd.read_csv(log_path).loc[0, "reason"] == "http_404"


def test_acquire_movies_paces_between_ids_after_failures_only(tmp_path):
    def fetch_or_fail(tmdb_id, api_key, session, **settings):
        assert_fetch_configuration(api_key, session, settings, "test-key")
        if tmdb_id == 1:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return {"tmdb_id": tmdb_id, "title": f"Movie {tmdb_id}"}

    with (
        patch("src.acquire.fetch_movie", side_effect=fetch_or_fail),
        patch("src.acquire.time.sleep") as sleep,
    ):
        acquire_movies(
            [1, 2],
            "test-key",
            output_path=tmp_path / "movies.csv",
            delay_seconds=0.25,
            log_path=tmp_path / "acquisition_log.csv",
        )

    sleep.assert_called_once_with(0.25)