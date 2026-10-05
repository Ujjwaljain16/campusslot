from sqlalchemy.exc import OperationalError

from app.db import get_db
from app.main import app


def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_ready_when_database_is_reachable(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_when_database_is_unavailable(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def close(self):
            pass

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_liveness_stays_ok_even_when_database_is_down(client):
    """Liveness must not depend on the database, otherwise Kubernetes would restart healthy pods."""

    def broken_db():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = broken_db
    assert client.get("/health").status_code == 200


def test_info_exposes_build_metadata(client):
    body = client.get("/api/info").json()
    assert body["name"] == "CampusSlot"
    assert {"version", "git_sha", "environment"} <= body.keys()
    assert body["day_open_hour"] < body["day_close_hour"]


def test_metrics_endpoint_serves_prometheus_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# HELP" in response.text
