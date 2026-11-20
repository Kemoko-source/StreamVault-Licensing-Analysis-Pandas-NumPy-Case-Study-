"""Offline end-to-end scalability check for a 500-film catalog."""

from decimal import Decimal
from unittest.mock import patch

import pandas as pd

from src.acquire import acquire_movies
from src.analyze import (
    build_content_shortlist,
    build_data_quality_summary,
    build_rating_summary,
)
from src.licensing import build_license_decision


def test_pipeline_handles_500_films_without_live_api_calls(tmp_path):
    # Generate predictable records to test scale without network access.
    def fake_fetch_movie(tmdb_id, api_key, session, **settings):
        assert api_key == "offline-test-key"
        assert session is not None
        assert settings == {"max_attempts": 3, "backoff_seconds": 1.0}
        release_year = 1960 + tmdb_id % 61
        rating = 5.0 + (tmdb_id % 50) / 10
        return {
            "tmdb_id": tmdb_id,
            "title": f"Film {tmdb_id}",
            "release_date": f"{release_year}-06-15",
            "runtime": 90 + tmdb_id % 60,
            "budget": 1_000_000 + tmdb_id * 1000,
            "revenue": 2_000_000 + tmdb_id * 2000,
            "genres": "Drama",
            "popularity": tmdb_id / 10,
            "vote_average": rating,
            "vote_count": 100 + tmdb_id * 10,
        }

    raw_ids = list(range(1, 501))
    with patch("src.acquire.fetch_movie", side_effect=fake_fetch_movie):
        movies = acquire_movies(
            raw_ids,
            "offline-test-key",
            output_path=tmp_path / "movies.csv",
            delay_seconds=0,
            log_path=tmp_path / "acquisition_log.csv",
        )

    acquisition_log = pd.read_csv(tmp_path / "acquisition_log.csv")
    assert len(movies) == 500
    assert acquisition_log["status"].eq("success").all()
    assert len(acquisition_log) == 500

    ratings = build_rating_summary(movies)
    quality = build_data_quality_summary(movies).set_index("metric")["value"]
    shortlist = build_content_shortlist(movies)

    assert ratings["film_count"].sum() >= 500
    assert quality["duplicate_tmdb_ids"] == 0
    assert quality["film_rows"] == 500
    assert len(shortlist) == 20

    # Use synthetic quotes to check that the optimizer stays within budget.
    candidate_ids = sorted(shortlist["tmdb_id"].unique())
    offers = pd.DataFrame(
        [
            {
                "candidate_id": f"title:{tmdb_id}",
                "candidate_type": "standalone",
                "candidate_name": f"Film {tmdb_id}",
                "member_tmdb_ids": str(tmdb_id),
                "member_titles": f"Film {tmdb_id}",
                "all_year_rank": index + 1,
                "all_year_score": 8.0 - index / 100,
                "post_2000_rank": index + 1,
                "post_2000_score": 7.5 - index / 100,
                "license_fee_usd": 1_000_000 + index * 1000,
                "rights_available": "yes",
                "territory": "US",
                "license_start_date": "2027-01-01",
                "license_end_date": "2027-12-31",
                "quote_date": "2026-11-01",
                "offer_source": "synthetic scale test",
            }
            for index, tmdb_id in enumerate(candidate_ids)
        ]
    )

    decision, _ = build_license_decision(
        offers,
        budget_usd=Decimal("14000000"),
    )
    assert decision["decision_status"].eq("optimized").all()
    assert decision["total_license_cost_usd"].le(14_000_000).all()
