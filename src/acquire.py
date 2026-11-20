"""Acquire and clean TMDb movie data for StreamVault analysis."""

from __future__ import annotations

import math
import os
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from dotenv import load_dotenv


BASE_URL = "https://api.themoviedb.org/3"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "id_list.csv"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_movies.csv"
ACQUISITION_LOG_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_acquisition_log.csv"


def load_raw_movie_ids(path: str | Path = RAW_DATA_PATH) -> list[str]:
    """Read every source ID as text so invalid values remain auditable."""
    ids = pd.read_csv(path, dtype={"tmdb_id": "string"}, keep_default_na=False)
    if "tmdb_id" not in ids.columns:
        raise ValueError("Input CSV must contain a 'tmdb_id' column")
    return ids["tmdb_id"].tolist()


def build_acquisition_log(tmdb_ids: Iterable[object]) -> pd.DataFrame:
    """Classify every source value and mark repeated valid IDs."""
    rows = []
    first_seen: dict[int, int] = {}

    # Keep one log row for every input, even when its ID cannot be used.
    for source_record, raw_id in enumerate(tmdb_ids, start=1):
        raw_value = "" if pd.isna(raw_id) else str(raw_id)
        normalized_value = raw_value.strip()
        row = {
            "source_record": source_record,
            "raw_tmdb_id": raw_value,
            "tmdb_id": None,
            "status": None,
            "reason": None,
            "duplicate_of_record": None,
            "used_cached_data": False,
        }

        if not normalized_value:
            row.update(status="invalid", reason="missing_id")
        else:
            # Only positive whole-number IDs are safe to send to TMDb.
            try:
                numeric_id = Decimal(normalized_value)
            except InvalidOperation:
                row.update(status="invalid", reason="not_numeric")
            else:
                if not numeric_id.is_finite():
                    row.update(status="invalid", reason="not_finite")
                elif numeric_id != numeric_id.to_integral_value():
                    row.update(status="invalid", reason="not_integer")
                elif numeric_id <= 0:
                    row.update(status="invalid", reason="non_positive")
                else:
                    tmdb_id = int(numeric_id)
                    row["tmdb_id"] = tmdb_id
                    if tmdb_id in first_seen:
                        row.update(
                            status="duplicate",
                            reason="duplicate_id",
                            duplicate_of_record=first_seen[tmdb_id],
                        )
                    else:
                        first_seen[tmdb_id] = source_record
                        row["status"] = "pending"
        rows.append(row)

    return pd.DataFrame(
        rows,
        columns=[
            "source_record",
            "raw_tmdb_id",
            "tmdb_id",
            "status",
            "reason",
            "duplicate_of_record",
            "used_cached_data",
        ],
    )


def load_movie_ids(path: str | Path = RAW_DATA_PATH) -> list[int]:
    """Read unique, positive integer TMDb IDs from the supplied CSV."""
    manifest = build_acquisition_log(load_raw_movie_ids(path))
    return manifest.loc[manifest["status"] == "pending", "tmdb_id"].astype(int).tolist()


def tmdb_get(
    endpoint: str,
    api_key: str,
    session: requests.Session | None = None,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
) -> dict:
    """Fetch one TMDb endpoint and return its JSON object."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    if not math.isfinite(backoff_seconds) or backoff_seconds < 0:
        raise ValueError("backoff_seconds cannot be negative")

    client = session or requests.Session()
    authentication_retry_used = False
    for attempt in range(max_attempts):
        try:
            response = client.get(
                f"{BASE_URL}{endpoint}",
                params={"api_key": api_key},
                timeout=30,
            )
        except (requests.Timeout, requests.ConnectionError):
            if attempt + 1 == max_attempts:
                raise
            time.sleep(backoff_seconds * (2**attempt))
            continue

        # A 401 gets one retry; rate limits and server errors use the remaining attempts.
        is_authentication_error = response.status_code == 401
        retryable_status = (
            response.status_code == 429
            or 500 <= response.status_code < 600
            or (is_authentication_error and not authentication_retry_used)
        )
        if retryable_status and attempt + 1 < max_attempts:
            if is_authentication_error:
                authentication_retry_used = True
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = backoff_seconds * (2**attempt)
            if not math.isfinite(delay) or delay < 0:
                delay = backoff_seconds * (2**attempt)
            time.sleep(delay)
            continue

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected TMDb response for {endpoint}")
        return payload

    raise RuntimeError("TMDb request loop ended unexpectedly")


def fetch_movie(tmdb_id: int, api_key: str, session: requests.Session | None = None) -> dict:
    """Fetch movie and credit details for one numeric TMDb ID."""
    movie = tmdb_get(f"/movie/{tmdb_id}", api_key, session)
    credits = tmdb_get(f"/movie/{tmdb_id}/credits", api_key, session)

    genres = "|".join(item["name"] for item in movie.get("genres", []) if item.get("name"))
    companies = "|".join(
        item["name"] for item in movie.get("production_companies", []) if item.get("name")
    )
    languages = "|".join(
        item["name"] for item in movie.get("spoken_languages", []) if item.get("name")
    )
    cast = credits.get("cast", [])
    crew = credits.get("crew", [])
    collection = movie.get("belongs_to_collection")
    # Missing metadata is different from TMDb confirming there is no collection.
    collection_metadata_status = (
        "present" if "belongs_to_collection" in movie else "missing"
    )

    return {
        "tmdb_id": tmdb_id,
        "title": movie.get("title"),
        "original_title": movie.get("original_title"),
        "release_date": movie.get("release_date"),
        "runtime": movie.get("runtime"),
        "budget": movie.get("budget"),
        "revenue": movie.get("revenue"),
        "status": movie.get("status"),
        "genres": genres or None,
        "production_companies": companies or None,
        "spoken_languages": languages or None,
        "popularity": movie.get("popularity"),
        "vote_average": movie.get("vote_average"),
        "vote_count": movie.get("vote_count"),
        "adult": movie.get("adult"),
        "collection_id": collection.get("id") if isinstance(collection, dict) else None,
        "collection_name": collection.get("name") if isinstance(collection, dict) else None,
        "collection_metadata_status": collection_metadata_status,
        # Cast order is used only as a simple proxy for the top-billed actor.
        "top_billed_actor": cast[0].get("name") if cast and cast[0].get("name") else None,
        "top_cast": "|".join(item["name"] for item in cast[:5] if item.get("name")) or None,
        "director": "|".join(
            item["name"] for item in crew if item.get("job") == "Director"
        ) or None,
    }


def acquire_movies(
    tmdb_ids: Iterable[object],
    api_key: str,
    output_path: str | Path = PROCESSED_DATA_PATH,
    delay_seconds: float = 0.25,
    log_path: str | Path = ACQUISITION_LOG_PATH,
) -> pd.DataFrame:
    """Fetch unique valid IDs, save movies, and log the outcome of every input."""
    records: list[dict] = []
    session = requests.Session()
    log = build_acquisition_log(tmdb_ids)
    output = Path(output_path)
    cached = pd.DataFrame()
    if output.exists():
        # Load old rows so a temporary API failure does not erase the last copy.
        cached = pd.read_csv(output)
        if "tmdb_id" not in cached.columns:
            raise ValueError(f"Cached movie file has no 'tmdb_id' column: {output}")
        cached["tmdb_id"] = pd.to_numeric(cached["tmdb_id"], errors="coerce").astype(
            "Int64"
        )
        cached = cached.dropna(subset=["tmdb_id"]).drop_duplicates(
            subset=["tmdb_id"], keep="last"
        )

    requested_ids = set(
        log.loc[log["status"] == "pending", "tmdb_id"].astype(int).tolist()
    )
    if not cached.empty:
        cached = cached.loc[cached["tmdb_id"].isin(requested_ids)].copy()
        cached_ids = set(cached["tmdb_id"].astype(int).tolist())
    else:
        cached_ids = set()

    for index in log.index[log["status"] == "pending"]:
        tmdb_id = int(log.at[index, "tmdb_id"])
        try:
            records.append(fetch_movie(int(tmdb_id), api_key, session))
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else "unknown"
            log.at[index, "status"] = "api_error"
            log.at[index, "reason"] = f"http_{status}"
            log.at[index, "used_cached_data"] = tmdb_id in cached_ids
        except requests.Timeout:
            log.at[index, "status"] = "api_error"
            log.at[index, "reason"] = "timeout"
            log.at[index, "used_cached_data"] = tmdb_id in cached_ids
        except requests.ConnectionError:
            log.at[index, "status"] = "api_error"
            log.at[index, "reason"] = "connection_error"
            log.at[index, "used_cached_data"] = tmdb_id in cached_ids
        except requests.RequestException:
            log.at[index, "status"] = "api_error"
            log.at[index, "reason"] = "request_error"
            log.at[index, "used_cached_data"] = tmdb_id in cached_ids
        except ValueError:
            log.at[index, "status"] = "api_error"
            log.at[index, "reason"] = "invalid_response"
            log.at[index, "used_cached_data"] = tmdb_id in cached_ids
        else:
            log.at[index, "status"] = "success"
            log.at[index, "reason"] = None
        if delay_seconds:
            time.sleep(delay_seconds)

    log_output = Path(log_path)
    log_output.parent.mkdir(parents=True, exist_ok=True)
    log.to_csv(log_output, index=False)

    # New responses replace cached rows; cached rows remain for failed refreshes.
    refreshed = pd.DataFrame(records)
    if not refreshed.empty:
        refreshed = clean_movie_data(refreshed)
        refreshed_ids = set(refreshed["tmdb_id"].astype(int).tolist())
        if not cached.empty:
            cached = cached.loc[~cached["tmdb_id"].isin(refreshed_ids)]

    movies = pd.concat([cached, refreshed], ignore_index=True)
    if not movies.empty:
        movies = clean_movie_data(movies)
        input_order = dict(
            zip(
                log.loc[log["status"] == "pending", "tmdb_id"].astype(int),
                log.loc[log["status"] == "pending", "source_record"],
            )
        )
        movies["_source_record"] = movies["tmdb_id"].astype(int).map(input_order)
        movies = movies.sort_values("_source_record").drop(
            columns="_source_record"
        ).reset_index(drop=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        movies.to_csv(output, index=False)

    return movies


def clean_movie_data(movies: pd.DataFrame) -> pd.DataFrame:
    """Normalize types and invalidate impossible values without guessing at zeroes.

    Zero budgets and revenues are preserved so downstream analysis can review
    them explicitly instead of assuming they mean missing data.
    """
    cleaned = movies.copy()

    # Invalid IDs cannot be used to match source records reliably.
    if "tmdb_id" in cleaned:
        numeric_ids = pd.to_numeric(cleaned["tmdb_id"], errors="coerce")
        numeric_ids = numeric_ids.replace([float("inf"), float("-inf")], pd.NA)
        numeric_ids = numeric_ids.where(
            numeric_ids.gt(0) & numeric_ids.mod(1).eq(0)
        )
        cleaned["tmdb_id"] = numeric_ids.astype("Int64")

    if "collection_id" in cleaned:
        collection_ids = pd.to_numeric(cleaned["collection_id"], errors="coerce")
        collection_ids = collection_ids.replace([float("inf"), float("-inf")], pd.NA)
        collection_ids = collection_ids.where(
            collection_ids.gt(0) & collection_ids.mod(1).eq(0)
        )
        cleaned["collection_id"] = collection_ids.astype("Int64")

    # These fields must be whole numbers and cannot be negative.
    for column in ("runtime", "vote_count"):
        if column in cleaned:
            numeric = pd.to_numeric(cleaned[column], errors="coerce")
            numeric = numeric.replace([float("inf"), float("-inf")], pd.NA)
            numeric = numeric.where(numeric.ge(0) & numeric.mod(1).eq(0))
            cleaned[column] = numeric.astype("Int64")

    # Ratings have a 0-to-10 scale; the other values must be non-negative.
    for column in ("budget", "revenue", "popularity", "vote_average"):
        if column in cleaned:
            numeric = pd.to_numeric(cleaned[column], errors="coerce")
            numeric = numeric.replace([float("inf"), float("-inf")], pd.NA)
            if column == "vote_average":
                numeric = numeric.where(numeric.ge(0) & numeric.le(10))
            else:
                numeric = numeric.where(numeric.ge(0))
            cleaned[column] = numeric.astype("Float64")

    if "release_date" in cleaned:
        cleaned["release_date"] = pd.to_datetime(cleaned["release_date"], errors="coerce")
        cleaned["release_year"] = cleaned["release_date"].dt.year.astype("Int64")

    if "title" in cleaned:
        cleaned["title"] = cleaned["title"].astype("string").str.strip()
        cleaned["title"] = cleaned["title"].replace("", pd.NA)
    for column in ("collection_name", "collection_metadata_status", "top_billed_actor"):
        if column in cleaned:
            cleaned[column] = cleaned[column].astype("string").str.strip()
            cleaned[column] = cleaned[column].replace("", pd.NA)

    cleaned = cleaned.dropna(subset=["tmdb_id", "title"]).drop_duplicates(
        subset=["tmdb_id"], keep="first"
    )
    cleaned = cleaned.reset_index(drop=True)
    return cleaned


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise RuntimeError("TMDB_API_KEY is not set in the environment or project .env")

    ids = load_raw_movie_ids()
    movies = acquire_movies(ids, api_key)
    log = pd.read_csv(ACQUISITION_LOG_PATH)
    fetched = int(log["status"].eq("success").sum())
    reused = int(log["used_cached_data"].sum())
    print(
        f"Fetched {fetched} movies; reused {reused} cached records; "
        f"saved {len(movies)} total movies"
    )
    errors = log.loc[log["status"] == "api_error", "reason"].value_counts()
    if not errors.empty:
        print("API failures:", errors.to_dict())
    print(f"Saved to {PROCESSED_DATA_PATH}")


if __name__ == "__main__":
    main()
