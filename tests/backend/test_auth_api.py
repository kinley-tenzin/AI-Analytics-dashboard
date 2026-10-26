"""Web application sign-in API and sign-in throttling (backend/access, Task 10.3)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from access import throttle
from access.models import LoginFailure
from django.test import Client
from django.utils import timezone

pytestmark = pytest.mark.django_db

PASSWORD = "pw-for-tests"


def post(client, url, body=None, **extra):
    return client.post(url, json.dumps(body or {}), content_type="application/json", **extra)


@pytest.fixture
def csrf_client():
    """A browser-like client: CSRF is enforced, the token comes from the session endpoint."""
    client = Client(enforce_csrf_checks=True)
    client.get("/api/v1/auth/session/")
    return client


def csrf_post(client, url, body=None):
    return post(client, url, body, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)


# --- session --------------------------------------------------------------------------------


def test_session_when_signed_out_is_a_normal_200(client):
    response = client.get("/api/v1/auth/session/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "authenticated": False, "user": None}
    assert "csrftoken" in response.cookies
    assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]


def test_session_when_signed_in_returns_the_scope_from_django(client, role_user):
    role_user("au_branch", "DrukSmart Branch Manager", branches=("odoo:odoo-sandbox:1",))
    client.login(username="au_branch", password=PASSWORD)
    user = client.get("/api/v1/auth/session/").json()["user"]
    assert user == {
        "username": "au_branch",
        "roles": ["DrukSmart Branch Manager"],
        "domains": ["accounts", "hr"],
        "branch_restricted": True,
        "author_domains": [],
    }


# --- sign in --------------------------------------------------------------------------------


def test_sign_in_creates_a_session_and_returns_the_scope(csrf_client, role_user):
    role_user("au_hr", "DrukSmart HR Manager")
    response = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_hr", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["user"]["domains"] == ["hr"]
    assert csrf_client.get("/api/v1/me/").status_code == 200


def test_session_cookie_is_httponly(csrf_client, role_user):
    role_user("au_cookie", "DrukSmart HR Manager")
    response = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_cookie", "password": PASSWORD}
    )
    cookie = response.cookies["sessionid"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


def test_sign_in_rotates_the_session_id(csrf_client, role_user):
    """No session fixation: an id from before sign-in is not reused."""
    role_user("au_fix", "DrukSmart HR Manager")
    session = csrf_client.session  # an attacker-planted, pre-existing anonymous session
    session["planted"] = True
    session.save()
    before = csrf_client.cookies["sessionid"].value
    csrf_post(csrf_client, "/api/v1/auth/login/", {"username": "au_fix", "password": PASSWORD})
    after = csrf_client.cookies["sessionid"].value
    assert before and after != before


def test_sign_in_requires_csrf(role_user):
    role_user("au_csrf", "DrukSmart HR Manager")
    client = Client(enforce_csrf_checks=True)
    response = post(client, "/api/v1/auth/login/", {"username": "au_csrf", "password": PASSWORD})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "username,password,active",
    [
        ("au_wrong", "not-the-password", True),
        ("nobody_here", PASSWORD, True),
        ("au_off", PASSWORD, False),
    ],
)
def test_failures_give_one_generic_answer(csrf_client, role_user, username, password, active):
    """Wrong password, unknown user and inactive account are indistinguishable."""
    for name in ("au_wrong", "au_off"):
        role_user(name, "DrukSmart HR Manager")
    if not active:
        from django.contrib.auth import get_user_model

        get_user_model().objects.filter(username="au_off").update(is_active=False)
    response = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {
        "status": "invalid_credentials",
        "message": "Username or password is incorrect.",
    }
    assert csrf_client.get("/api/v1/auth/session/").json()["authenticated"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "x"},
        {"username": "", "password": "x"},
        {"username": ["x"], "password": "x"},
    ],
)
def test_malformed_sign_in_requests(csrf_client, body):
    response = csrf_post(csrf_client, "/api/v1/auth/login/", body)
    assert response.status_code == 400
    assert response.json()["status"] == "invalid_request"


def test_sign_in_needs_post(client):
    assert client.get("/api/v1/auth/login/").status_code == 405


def test_user_without_role_can_sign_in_but_has_no_modules(csrf_client, role_user):
    role_user("au_norole", None)
    response = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_norole", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["user"]["domains"] == []
    assert csrf_client.get("/api/v1/kpis/").json()["functions"] == []


# --- sign out -------------------------------------------------------------------------------


def test_sign_out_ends_api_access(csrf_client, role_user):
    role_user("au_out", "DrukSmart Accounts Manager")
    csrf_post(csrf_client, "/api/v1/auth/login/", {"username": "au_out", "password": PASSWORD})
    response = csrf_post(csrf_client, "/api/v1/auth/logout/")
    assert response.status_code == 200 and response.json()["authenticated"] is False
    assert csrf_client.get("/api/v1/me/").status_code == 401
    assert csrf_client.get("/api/v1/kpis/").status_code == 401


def test_sign_out_requires_csrf(role_user):
    """A foreign page cannot sign the user out (CSRF)."""
    role_user("au_outcsrf", "DrukSmart HR Manager")
    client = Client(enforce_csrf_checks=True)
    client.login(username="au_outcsrf", password=PASSWORD)
    assert post(client, "/api/v1/auth/logout/").status_code == 403
    assert client.get("/api/v1/me/").status_code == 200


# --- throttling (defect D6) -----------------------------------------------------------------


def fail(client, username, times):
    for _ in range(times):
        csrf_post(client, "/api/v1/auth/login/", {"username": username, "password": "wrong"})


def test_five_failures_lock_the_username_even_for_the_right_password(csrf_client, role_user):
    role_user("au_lock", "DrukSmart HR Manager")
    fail(csrf_client, "au_lock", throttle.MAX_FAILURES)
    response = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "AU_Lock", "password": PASSWORD}
    )
    assert response.status_code == 429
    assert response.json()["status"] == "throttled"
    assert 0 < int(response["Retry-After"]) <= int(throttle.WINDOW.total_seconds()) + 1
    assert csrf_client.get("/api/v1/auth/session/").json()["authenticated"] is False


def test_four_failures_do_not_lock_and_success_clears_the_count(csrf_client, role_user):
    role_user("au_four", "DrukSmart HR Manager")
    fail(csrf_client, "au_four", throttle.MAX_FAILURES - 1)
    ok = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_four", "password": PASSWORD}
    )
    assert ok.status_code == 200
    assert not LoginFailure.objects.filter(username="au_four").exists()


def test_lock_expires_after_the_window(csrf_client, role_user):
    role_user("au_expire", "DrukSmart HR Manager")
    fail(csrf_client, "au_expire", throttle.MAX_FAILURES)
    LoginFailure.objects.update(created_at=timezone.now() - throttle.WINDOW - timedelta(seconds=1))
    ok = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_expire", "password": PASSWORD}
    )
    assert ok.status_code == 200


def test_lock_applies_to_the_django_form_and_admin_too(client, role_user):
    """The check is in the authentication backend, so no sign-in path bypasses it."""
    role_user("au_paths", "DrukSmart HR Manager")
    for _ in range(throttle.MAX_FAILURES):
        client.post("/accounts/login/", {"username": "au_paths", "password": "wrong"})
    assert throttle.lockout_seconds("au_paths") > 0
    assert client.login(username="au_paths", password=PASSWORD) is False
    response = client.post("/accounts/login/", {"username": "au_paths", "password": PASSWORD})
    assert response.status_code == 200  # the form is shown again: not signed in
    assert client.get("/api/v1/me/").status_code == 401


def test_lock_is_per_username(csrf_client, role_user):
    role_user("au_victim", "DrukSmart HR Manager")
    role_user("au_other", "DrukSmart HR Manager")
    fail(csrf_client, "au_victim", throttle.MAX_FAILURES)
    ok = csrf_post(
        csrf_client, "/api/v1/auth/login/", {"username": "au_other", "password": PASSWORD}
    )
    assert ok.status_code == 200


def test_no_credentials_are_stored(csrf_client):
    fail(csrf_client, "someone", 2)
    row = LoginFailure.objects.filter(username="someone").values().first()
    assert set(row) == {"id", "username", "ip_address", "created_at"}


def test_administrator_can_see_and_clear_failures_in_admin(client, django_user_model, csrf_client):
    fail(csrf_client, "locked_one", throttle.MAX_FAILURES)
    admin = django_user_model.objects.create_superuser("au_admin", password=PASSWORD)
    client.force_login(admin)
    listing = client.get("/admin/access/loginfailure/?q=locked_one")
    assert listing.status_code == 200 and b"locked_one" in listing.content
    ids = list(LoginFailure.objects.filter(username="locked_one").values_list("id", flat=True))
    client.post(
        "/admin/access/loginfailure/",
        {"action": "delete_selected", "_selected_action": ids, "post": "yes"},
    )
    assert throttle.lockout_seconds("locked_one") == 0
