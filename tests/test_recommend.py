"""Tests for recommendations when classification metadata is absent."""

import pandas as pd

from src.recommend import (
    OFFER_FIELDS,
    _complete_offer_count,
    _write_client_memo,
    build_franchise_targets,
    build_standalone_shortlist,
)


def test_missing_collection_metadata_does_not_crash_or_mark_titles_standalone():
    # Unknown collection status must not be treated as standalone.
    movies = pd.DataFrame(
        [
            {
                "tmdb_id": 1,
                "title": "Film One",
                "release_year": 2010,
                "vote_average": 8.0,
                "vote_count": 1000,
            },
            {
                "tmdb_id": 2,
                "title": "Film Two",
                "release_year": 2011,
                "vote_average": 7.5,
                "vote_count": 800,
            },
        ]
    )

    standalones = build_standalone_shortlist(movies)

    assert standalones.empty
    assert "reason" in standalones.columns


def test_single_candidate_collection_is_not_promoted_to_a_franchise_bundle():
    movies = pd.DataFrame(
        [
            {
                "tmdb_id": 1,
                "title": "One listed installment",
                "release_year": 2010,
                "vote_average": 8.0,
                "vote_count": 1000,
                "collection_id": 10,
                "collection_name": "Larger Collection",
                "collection_metadata_status": "present",
            }
        ]
    )

    franchises = build_franchise_targets(movies)

    assert franchises.empty


def test_complete_offer_count_counts_complete_rows_not_all_or_nothing():
    # Count the finished quote even when another candidate is still incomplete.
    complete_offer = {column: "provided" for column in OFFER_FIELDS}
    incomplete_offer = {**complete_offer, "license_fee_usd": ""}
    offers = pd.DataFrame([complete_offer, incomplete_offer])

    assert _complete_offer_count(offers) == 1
    assert _complete_offer_count(offers.iloc[0:0]) == 0


def test_client_memo_uses_clean_markdown_line_breaks(tmp_path, monkeypatch):
    from src import recommend

    monkeypatch.setattr(recommend, "CLIENT_MEMO_PATH", tmp_path / "client_memo.md")
    _write_client_memo(
        pd.DataFrame(),
        pd.DataFrame(columns=["status", "used_cached_data", "tmdb_id"]),
        pd.DataFrame(columns=["cohort"]),
        pd.DataFrame(columns=["cohort"]),
        pd.DataFrame(columns=["cohort", "role", "talent"]),
        pd.DataFrame(columns=OFFER_FIELDS),
    )

    memo = (tmp_path / "client_memo.md").read_text(encoding="utf-8")

    assert all(line == line.rstrip() for line in memo.splitlines())
