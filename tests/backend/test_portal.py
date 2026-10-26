"""Django serving of the React web application under /app/ (backend/portal, Task 10.2)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

INDEX = (
    '<!doctype html><html><body><div id="root"></div>'
    '<script type="module" src="/app/assets/index-abc.js"></script></body></html>'
)


@pytest.fixture
def dist(tmp_path, settings):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / "index-abc.js").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("outside the build", encoding="utf-8")
    settings.DRUKSMART_FRONTEND_DIST = tmp_path
    return tmp_path


@pytest.mark.parametrize(
    "url", ["/app", "/app/", "/app/hr", "/app/accounts", "/app/login?next=/hr", "/app/x/y/z"]
)
def test_every_app_route_returns_the_app_shell(client, dist, url):
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert b'<div id="root">' in response.content


def test_app_shell_sets_csrf_cookie_and_is_not_cached(client, dist):
    response = client.get("/app/")
    assert "csrftoken" in response.cookies
    assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]


def test_app_shell_has_a_strict_content_security_policy(client, dist):
    csp = client.get("/app/")["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp
    assert client.get("/app/")["X-Frame-Options"] == "DENY"


def test_app_shell_needs_no_login_and_contains_no_data(client, dist):
    """The shell is static; data only comes from the authenticated API."""
    assert client.get("/app/overview").status_code == 200
    assert client.get("/api/v1/me/").status_code == 401


def test_hashed_assets_are_served_with_long_cache(client, dist):
    response = client.get("/app/assets/index-abc.js")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"console.log('app')"
    assert "immutable" in response["Cache-Control"]


def test_root_files_are_served(client, dist):
    response = client.get("/app/favicon.svg")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/svg+xml"


@pytest.mark.parametrize(
    "url",
    [
        "/app/assets/missing.js",
        "/app/missing.png",
        "/app/assets/../../secret.txt",
        "/app/assets/..%2F..%2Fsecret.txt",
    ],
)
def test_missing_files_and_path_traversal_are_404(client, dist, url):
    assert client.get(url).status_code == 404


def test_index_html_is_only_served_through_the_shell_view(client, dist):
    assert client.get("/app/index.html").status_code == 404


def test_only_safe_methods(client, dist):
    assert client.post("/app/").status_code == 405
    assert client.head("/app/").status_code == 200


def test_missing_build_is_explained(client, settings, tmp_path):
    settings.DRUKSMART_FRONTEND_DIST = tmp_path / "not-built"
    response = client.get("/app/")
    assert response.status_code == 503
    assert b"npm run build" in response.content


def test_logout_returns_to_the_app_sign_in_page(client, dist, role_user):
    role_user("portal_hr", "DrukSmart HR Manager")
    assert client.login(username="portal_hr", password="pw-for-tests")
    response = client.post("/accounts/logout/", {"next": "/app/login"})
    assert response.status_code == 302 and response["Location"] == "/app/login"
    assert client.get("/api/v1/me/").status_code == 401


def test_logout_refuses_foreign_redirects(client, dist):
    response = client.post("/accounts/logout/", {"next": "https://evil.example/"})
    assert response["Location"] != "https://evil.example/"


def test_django_login_returns_into_the_app(client, dist, role_user):
    role_user("portal_acc", "DrukSmart Accounts Manager")
    response = client.post(
        "/accounts/login/",
        {"username": "portal_acc", "password": "pw-for-tests", "next": "/app/accounts"},
    )
    assert response.status_code == 302 and response["Location"] == "/app/accounts"
    me = client.get("/api/v1/me/").json()["scope"]
    assert me["domains"] == ["accounts"]


def test_old_assistant_page_redirects_to_ask_ai(client, role_user):
    """Decision 3: after the website was verified, the old page redirects to Ask AI (Task 10.9)."""
    role_user("portal_old", "DrukSmart HR Manager")
    client.login(username="portal_old", password="pw-for-tests")
    response = client.get("/assistant/")
    assert response.status_code == 302 and response["Location"] == "/app/ask"
