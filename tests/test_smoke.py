"""Smoke tests: public pages load and protected pages require authentication."""
import pytest

pytestmark = pytest.mark.django_db


def test_landing_page_loads(client):
    assert client.get("/").status_code == 200


def test_dashboard_requires_login(client):
    response = client.get("/app/")
    assert response.status_code == 302
    assert "/accounts/login" in response.url


@pytest.mark.parametrize(
    "url",
    [
        "/app/",
        "/assistant/",
        "/tasks/",
        "/calendar/",
        "/email/",
        "/workflows/",
        "/integrations/",
        "/documents/",
        "/notifications/",
        "/analytics/",
        "/settings/",
        "/audit/",
    ],
)
def test_app_pages_render_for_authenticated_user(client, user, url):
    client.force_login(user)
    assert client.get(url).status_code == 200
