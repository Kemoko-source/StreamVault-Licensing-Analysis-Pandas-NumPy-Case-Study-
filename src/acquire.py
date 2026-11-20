"""Acquire and clean TMDb movie data for StreamVault analysis."""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd
import requests
from dotenv import load_dotenv


BASE_URL = "https://api.themoviedb.org/3"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "id_list.csv"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_movies.csv"
ACQUISITION_LOG_PATH = PROJECT_ROOT / "data" / "processed" / "tmdb_acquisition_log.csv"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_REQUEST_DELAY_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class AcquisitionSettings:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS


def _validate_max_attempts(max_attempts: int) -> None:
    if isinstance(max_attempts, bool):
        raise ValueError("max_attempts must be a positive integer")
    if not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be a positive integer")
    if max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")


def _validate_nonnegative_seconds(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


def acquisition_settings_from_environment() -> AcquisitionSettings:
    """Read optional retry and request-pacing overrides from the environment."""
    try:
        max_attempts = int(
            os.getenv("TMDB_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))
        )
        backoff_seconds = float(
            os.getenv("TMDB_BACKOFF_SECONDS", str(DEFAULT_BACKOFF_SECONDS))
        )
        request_delay_seconds = float(
            os.getenv(
                "TMDB_REQUEST_DELAY_SECONDS",
                str(DEFAULT_REQUEST_DELAY_SECONDS),
            )
        )
    except ValueError as exc:
        raise ValueError(
            "TMDB_MAX_ATTEMPTS must be an integer and TMDB_BACKOFF_SECONDS and "
            "TMDB_REQUEST_DELAY_SECONDS must be numeric"
        ) from exc

    _validate_max_attempts(max_attempts)
    _validate_nonnegative_seconds(backoff_seconds, "TMDB_BACKOFF_SECONDS")
    _validate_nonnegative_seconds(
        request_delay_seconds,
        "TMDB_REQUEST_DELAY_SECONDS",
    )
    return AcquisitionSettings(
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        request_delay_seconds=request_delay_seconds,
    )


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
            "duplicate_movie_rows_removed": 0,
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
            "duplicate_movie_rows_removed",
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
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict:
    """Fetch one TMDb endpoint and return its JSON object."""
    _validate_max_attempts(max_attempts)
    _validate_nonnegative_seconds(backoff_seconds, "backoff_seconds")

    client = session or requests.Session()
    authentication_retry_used = False
    for attempt in range(max_attempts):
        try:
            response = client.get(
                f"{BASE_URL}{endpoint}",
                params={"api_key": api_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
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


def fetch_movie(
    tmdb_id: int,
    api_key: str,
    session: requests.Session | None = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict:
    """Fetch movie and credit details for one numeric TMDb ID."""
    movie = tmdb_get(
        f"/movie/{tmdb_id}",
        api_key,
        session,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    credits = tmdb_get(
        f"/movie/{tmdb_id}/credits",
        api_key,
        session,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )

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
    delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    log_path: str | Path = ACQUISITION_LOG_PATH,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> pd.DataFrame:
    """Fetch unique valid IDs, save movies, and log the outcome of every input."""
    _validate_max_attempts(max_attempts)
    _validate_nonnegative_seconds(delay_seconds, "delay_seconds")
    _validate_nonnegative_seconds(backoff_seconds, "backoff_seconds")
    records: list[dict] = []
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
        cached = cached.dropna(subset=["tmdb_id"])

    requested_ids = set(
        log.loc[log["status"] == "pending", "tmdb_id"].astype(int).tolist()
    )
    if not cached.empty:
        cached = cached.loc[cached["tmdb_id"].isin(requested_ids)].copy()
        cached = clean_movie_data(cached)
        cached = _deduplicate_movie_records(cached, log, keep="last")
        cached_ids = set(cached["tmdb_id"].astype(int).tolist())
    else:
        cached_ids = set()

    pending_indices = log.index[log["status"] == "pending"].tolist()
    with requests.Session() as session:
        for request_number, index in enumerate(pending_indices):
            if request_number and delay_seconds:
                time.sleep(delay_seconds)
            tmdb_id = int(log.at[index, "tmdb_id"])
            try:
                movie = fetch_movie(
                    tmdb_id,
                    api_key,
                    session,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                )
                if not str(movie.get("title") or "").strip():
                    raise ValueError("TMDb movie response has no title")
                records.append(movie)
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

    # New responses replace cached rows; cached rows remain for failed refreshes.
    refreshed = pd.DataFrame(records)
    if not refreshed.empty:
        refreshed = clean_movie_data(refreshed)
        refreshed = _deduplicate_movie_records(refreshed, log)
        refreshed_ids = set(refreshed["tmdb_id"].astype(int).tolist())
        if not cached.empty:
            cached = cached.loc[~cached["tmdb_id"].isin(refreshed_ids)]

    movies = pd.concat([cached, refreshed], ignore_index=True)
    if not movies.empty:
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

    log_output = Path(log_path)
    log_output.parent.mkdir(parents=True, exist_ok=True)
    log.to_csv(log_output, index=False)
    if movies.empty:
        raise RuntimeError(
            "No valid movie records are available; the acquisition log was saved to "
            f"{log_output}, and the existing movie file was left unchanged"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    movies.to_csv(output, index=False)

    return movies


def clean_movie_data(movies: pd.DataFrame) -> pd.DataFrame:
    """Normalize types and invalidate impossible values without guessing at zeroes.

    Zero budgets and revenues are preserved so downstream analysis can review
    them explicitly instead of assuming they mean missing data. Duplicate IDs
    remain present so acquisition can reconcile any removed rows in its log.
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

    cleaned = cleaned.dropna(subset=["tmdb_id", "title"])
    cleaned = cleaned.reset_index(drop=True)
    return cleaned


def _deduplicate_movie_records(
    movies: pd.DataFrame,
    acquisition_log: pd.DataFrame,
    keep: Literal["first", "last"] = "first",
) -> pd.DataFrame:
    """Drop repeated movie IDs only after recording each removal in the log."""
    duplicate_mask = movies["tmdb_id"].duplicated(keep=keep)
    duplicate_counts = movies.loc[duplicate_mask, "tmdb_id"].value_counts()
    for tmdb_id, dropped_count in duplicate_counts.items():
        matching_rows = acquisition_log.index[
            acquisition_log["tmdb_id"].eq(tmdb_id).fillna(False)
            & acquisition_log["status"].ne("duplicate")
        ]
        if matching_rows.empty:
            raise ValueError(
                f"Cannot reconcile duplicate movie ID {tmdb_id} to a source record"
            )
        log_index = matching_rows[0]
        current_count = int(
            acquisition_log.at[log_index, "duplicate_movie_rows_removed"]
        )
        acquisition_log.at[log_index, "duplicate_movie_rows_removed"] = (
            current_count + int(dropped_count)
        )
    return movies.loc[~duplicate_mask].reset_index(drop=True)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise RuntimeError("TMDB_API_KEY is not set in the environment or project .env")

    ids = load_raw_movie_ids()
    settings = acquisition_settings_from_environment()
    movies = acquire_movies(
        ids,
        api_key,
        delay_seconds=settings.request_delay_seconds,
        max_attempts=settings.max_attempts,
        backoff_seconds=settings.backoff_seconds,
    )
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
