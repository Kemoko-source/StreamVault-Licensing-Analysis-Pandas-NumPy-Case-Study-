"""Tests for transient TMDb request retries."""

from unittest.mock import patch

import requests

from src.acquire import tmdb_get


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class FakeSession:
    """Return prepared responses so retry tests never use the live service."""

    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_retry_after_is_respected_for_rate_limit_response():
    session = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "2"}),
            FakeResponse(200, payload={"id": 550}),
        ]
    )

    with patch("src.acquire.time.sleep") as sleep:
        payload = tmdb_get("/movie/550", "test-key", session=session)

    assert payload == {"id": 550}
    assert session.calls == 2
    sleep.assert_called_once_with(2.0)


def test_network_errors_use_exponential_backoff():
    session = FakeSession(
        [
            requests.ConnectionError("reset"),
            requests.Timeout("timeout"),
            FakeResponse(200, payload={"id": 550}),
        ]
    )

    with patch("src.acquire.time.sleep") as sleep:
        payload = tmdb_get(
            "/movie/550",
            "test-key",
            session=session,
            backoff_seconds=0.25,
        )

    assert payload == {"id": 550}
    assert session.calls == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.25, 0.5]


def test_not_found_is_not_retried():
    # A missing movie is not a temporary server problem.
    session = FakeSession([FakeResponse(404)])

    try:
        tmdb_get("/movie/550", "test-key", session=session)
    except requests.HTTPError as error:
        assert error.response.status_code == 404
    else:
        raise AssertionError("A 404 response must raise an HTTPError")
    assert session.calls == 1


def test_authentication_error_gets_one_bounded_retry():
    session = FakeSession(
        [
            FakeResponse(401),
            FakeResponse(200, payload={"id": 550}),
        ]
    )

    with patch("src.acquire.time.sleep") as sleep:
        payload = tmdb_get("/movie/550", "test-key", session=session)

    assert payload == {"id": 550}
    assert session.calls == 2
    sleep.assert_called_once_with(1.0)


def test_repeated_authentication_error_stops_after_one_retry():
    session = FakeSession([FakeResponse(401), FakeResponse(401), FakeResponse(200)])

    with patch("src.acquire.time.sleep"):
        try:
            tmdb_get("/movie/550", "test-key", session=session)
        except requests.HTTPError as error:
            assert error.response.status_code == 401
        else:
            raise AssertionError("A repeated 401 must be surfaced")
    assert session.calls == 2


def test_invalid_retry_configuration_is_rejected():
    for options in ({"max_attempts": 0}, {"backoff_seconds": -1}):
        try:
            tmdb_get("/movie/550", "test-key", session=FakeSession([]), **options)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid retry settings must raise ValueError")
