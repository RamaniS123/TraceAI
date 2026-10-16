"""Tests for GET /health (AC-09: works without a token; AC-11: body shape)."""
import pytest

pytestmark = [pytest.mark.phase3, pytest.mark.no_reset]  # applies to every test in this file


def test_health_returns_200_when_healthy(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_body_has_contract_shape(client):
    body = client.get("/health").json()
    assert body == {"status": "healthy", "api": "available", "storage": "available"}


def test_health_does_not_need_a_token(client):
    # `client` sends no Authorization header, so a 401 here would be a bug.
    response = client.get("/health")
    assert response.status_code != 401
