"""Run the complete acquisition-to-licensing-report workflow."""

from __future__ import annotations

import os

import pandas as pd
from dotenv import load_dotenv

from src.acquire import (
    ACQUISITION_LOG_PATH,
    PROJECT_ROOT,
    acquire_movies,
    load_raw_movie_ids,
)
from src.analyze import run_analysis
from src.licensing import run_license_decision
from src.recommend import run_recommendations


def run_pipeline() -> dict[str, pd.DataFrame]:
    """Refresh source data, produce analyses, and evaluate verified offers."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise RuntimeError("TMDB_API_KEY is not set in the environment or project .env")

    # Each step writes inputs or reports needed by the step that follows.
    movies = acquire_movies(load_raw_movie_ids(), api_key)
    acquisition_log = pd.read_csv(ACQUISITION_LOG_PATH)
    rating_summary, quality_summary = run_analysis()
    recommendations = run_recommendations()
    license_summary, license_candidates = run_license_decision()

    return {
        "movies": movies,
        "acquisition_log": acquisition_log,
        "rating_summary": rating_summary,
        "quality_summary": quality_summary,
        **recommendations,
        "license_summary": license_summary,
        "license_candidates": license_candidates,
    }


def main() -> None:
    outputs = run_pipeline()
    errors = outputs["acquisition_log"].loc[
        outputs["acquisition_log"]["status"].eq("api_error"), "reason"
    ].value_counts()
    print(f"Analyzed {len(outputs['movies'])} movies.")
    if not errors.empty:
        print("Acquisition issues:", errors.to_dict())
    print("\nRating summary:")
    print(outputs["rating_summary"].to_string(index=False))
    print("\nLicensing decision:")
    print(outputs["license_summary"].to_string(index=False))
    print(f"\nReports: {PROJECT_ROOT / 'reports'}")


if __name__ == "__main__":
    main()
