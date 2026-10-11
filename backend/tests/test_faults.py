import pytest

from app.main import settings


@pytest.fixture
def faults(monkeypatch):
    """Switch the fault settings for one test. The middleware reads them on every request."""

    def apply(rate=0.0, latency_ms=0):
        monkeypatch.setattr(settings, "fault_error_rate", rate)
        monkeypatch.setattr(settings, "fault_latency_ms", latency_ms)

    return apply


def test_no_faults_by_default(client):
    assert settings.fault_error_rate == 0.0
    assert client.get("/api/rooms").status_code == 200


def test_every_request_fails_at_rate_one_but_the_probes_stay_healthy(client, faults):
    """A release that is Ready and still fails requests is the case a canary has to catch."""
    faults(rate=1.0)
    assert client.get("/api/rooms").status_code == 500
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_the_injected_failures_are_counted_as_5xx_in_the_metrics(client, faults):
    faults(rate=1.0)
    client.get("/api/rooms")
    metrics = client.get("/metrics").text
    assert any(
        line.startswith("http_requests_total") and 'status="5xx"' in line and "/api/rooms" in line
        for line in metrics.splitlines()
    )


def test_a_partial_rate_fails_some_requests_and_serves_the_rest(client, faults):
    faults(rate=0.5)
    statuses = [client.get("/api/rooms").status_code for _ in range(60)]
    assert 10 < statuses.count(500) < 50
    assert set(statuses) == {200, 500}


def test_extra_latency_is_added_to_api_requests(client, faults):
    import time

    faults(latency_ms=200)
    started = time.perf_counter()
    assert client.get("/api/rooms").status_code == 200
    assert time.perf_counter() - started >= 0.2


def test_faults_are_ignored_in_production(client, faults, monkeypatch):
    """The switch must be impossible to leave on in production. The app reads APP_ENV at start, so
    this builds a fresh app instead of changing the shared one."""
    from fastapi.testclient import TestClient

    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "app_env", "production")
    faults(rate=1.0)
    production_app = main_module.create_app()
    with TestClient(production_app) as production_client:
        assert production_client.get("/health").status_code == 200
        # Fault injection never ran, so this reaches the route (which may fail on the database
        # for other reasons, but not with the injected 500).
        response = production_client.get("/")
        assert response.status_code == 200
