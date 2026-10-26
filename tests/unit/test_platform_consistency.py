"""Cross-component consistency and regression guards for Milestone 8 defects (no services needed).

Superset and Django declare roles and branch scope separately (no SSO); these tests fail when the
two drift apart, and pin the integration fixes so they cannot silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _yaml(rel: str) -> dict:
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))


def test_superset_and_django_roles_grant_the_same_domains():
    from access.scope import ROLE_DOMAINS

    access = _yaml("superset/definitions/access.yml")
    technical = {access["embedding"]["guest_role"], access["embedding"]["service_role"]}
    superset = {
        r["name"]: frozenset(r["domains"]) for r in access["roles"] if r["name"] not in technical
    }
    assert superset == dict(ROLE_DOMAINS)


def test_demo_branch_manager_has_the_same_branch_in_both_systems():
    from access.management.commands.seed_demo_users import DEMO_USERS

    access = _yaml("superset/definitions/access.yml")
    rls = {k for rule in access["row_level_security"] for k in rule["branch_keys"]}
    django = {
        k
        for _, role, branches in DEMO_USERS
        if role == "DrukSmart Branch Manager"
        for k in branches
    }
    assert rls == django


def test_consumers_read_only_kpi_and_freshness_relations():
    for rel in ("superset/approved_datasets.yml", "backend/approved_datasets.yml"):
        relations = [d["relation"] for d in _yaml(rel)["datasets"]]
        assert all(r.startswith("kpi_") or r == "data_freshness" for r in relations), rel


def test_publication_grants_both_consumers():
    text = (REPO / "warehouse/publish.py").read_text(encoding="utf-8")
    assert '"DRUKSMART_SUPERSET_READER_USER"' in text and '"DRUKSMART_KPI_READER_USER"' in text


# ----------------------------------------------------------------- defect regression guards
FORBIDDEN_IN_AIRFLOW = (
    "POSTGRES_PASSWORD",
    "SUPERSET_ADMIN_PASSWORD",
    "SUPERSET_SECRET_KEY",
    "SUPERSET_DB_PASSWORD",
    "DJANGO_SECRET_KEY",
    "GEMINI_API_KEY",
    "BACKEND_DEMO_USER_PASSWORD",
    "SUPERSET_DEMO_USER_PASSWORD",
    "DRUKSMART_SUPERSET_READER_PASSWORD",
    "DRUKSMART_KPI_READER_PASSWORD",
    "ODOO_SANDBOX_ADMIN_PASSWORD",
    "ERPNEXT_SANDBOX_ADMIN_PASSWORD",
)


def test_d1_airflow_containers_get_no_unrelated_secrets():
    compose = _yaml("compose.yaml")
    for name, svc in compose["services"].items():
        # Containers that run pipeline code (airflow-db is Airflow's own PostgreSQL; its
        # POSTGRES_PASSWORD is the Airflow metadata password, not the warehouse superuser's).
        if svc.get("image") != "druksmart/airflow:3.3.2" or name == "synthetic-erp":
            continue
        assert "env_file" not in svc, f"{name} must not load the whole .env"
        env = svc.get("environment") or {}
        leaked = [k for k in FORBIDDEN_IN_AIRFLOW if k in env]
        assert not leaked, (name, leaked)
        mounts = svc.get("volumes") or []
        assert any(str(m).endswith("/opt/druksmart/.env:ro") for m in mounts), (
            f"{name}: the repository .env must be masked inside the container"
        )
    masked = (REPO / "orchestration/docker/no-secrets.env").read_text(encoding="utf-8")
    assert not re.search(r"^\s*[A-Z_]+\s*=", masked, re.M)


def test_d2_superset_does_not_cache_chart_data():
    config = (REPO / "superset/docker/superset_config.py").read_text(encoding="utf-8")
    assert re.search(r'DATA_CACHE_CONFIG\s*=\s*\{\s*"CACHE_TYPE":\s*"NullCache"', config)


def test_d3_freshness_shows_its_age_in_superset():
    datasets = {d["table"]: d for d in _yaml("superset/definitions/datasets.yml")["datasets"]}
    assert "hours_since_publication" in datasets["data_freshness"]["calculated_columns"]


def test_d4_sandboxes_restart_with_docker():
    for rel, services in (
        ("infrastructure/sandboxes/odoo/compose.yaml", ("db", "odoo")),
        (
            "infrastructure/sandboxes/erpnext/compose.yaml",
            ("db", "backend", "frontend", "websocket", "queue-short"),
        ),
    ):
        compose = _yaml(rel)
        for name in services:
            assert compose["services"][name].get("restart") == "unless-stopped", (rel, name)


FORBIDDEN_IN_BACKEND = (
    "POSTGRES_PASSWORD",
    "DRUKSMART_PIPELINE_PASSWORD",
    "DRUKSMART_BI_READER_PASSWORD",
    "DRUKSMART_SUPERSET_READER_PASSWORD",
    "SUPERSET_ADMIN_PASSWORD",
    "SUPERSET_SECRET_KEY",
    "SUPERSET_DB_PASSWORD",
    "AIRFLOW_ADMIN_PASSWORD",
    "AIRFLOW_DB_PASSWORD",
    "AIRFLOW_FERNET_KEY",
    "ODOO_API_KEY",
    "ERPNEXT_API_KEY",
    "ERPNEXT_API_SECRET",
)


def test_m9_backend_container_gets_only_its_own_settings():
    backend = _yaml("compose.yaml")["services"]["backend"]
    assert "env_file" not in backend
    leaked = [k for k in FORBIDDEN_IN_BACKEND if k in (backend.get("environment") or {})]
    assert not leaked, leaked
    assert any(str(m).endswith("/opt/druksmart/.env:ro") for m in backend["volumes"])
    assert all(p.startswith("127.0.0.1:") for p in backend["ports"])


# --- Milestone 10: website embedding --------------------------------------------------------
def test_m10_official_portal_dashboards_match_the_superset_definitions():
    import importlib.util
    import sys

    sys.path.insert(0, str(REPO / "superset" / "definitions"))
    from dashboards import DASHBOARDS

    spec = importlib.util.spec_from_file_location(
        "official", REPO / "backend/portal/migrations/0002_official_dashboards.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    portal = {(d["key"], d["superset_ref"]) for d in module.OFFICIAL}
    assert portal == {(d["key"], d["slug"]) for d in DASHBOARDS}
    access = _yaml("superset/definitions/access.yml")
    assert set(access["embedding"]["dashboards"]) == {d["key"] for d in DASHBOARDS}


def test_m10_guest_role_name_and_secret_in_superset_config():
    config = (REPO / "superset/docker/superset_config.py").read_text(encoding="utf-8")
    guest_role = _yaml("superset/definitions/access.yml")["embedding"]["guest_role"]
    assert f'GUEST_ROLE_NAME = "{guest_role}"' in config
    # Superset's built-in guest-token secret is public: the config must demand our own.
    assert 'GUEST_TOKEN_JWT_SECRET = _required("SUPERSET_GUEST_TOKEN_SECRET")' in config
    assert '"EMBEDDED_SUPERSET": True' in config
    assert 'TALISMAN_CONFIG["content_security_policy"]["frame-ancestors"]' in config


def test_m10_guest_role_has_no_dataset_access_of_its_own():
    access = _yaml("superset/definitions/access.yml")
    guest = next(r for r in access["roles"] if r["name"] == access["embedding"]["guest_role"])
    assert guest["domains"] == [] and guest["dashboards"] == [] and guest["base"] == "guest"
    removed = {tuple(p) for p in access["bases"]["guest"]["remove"]}
    assert {("can_explore", "Superset"), ("can_view_query", "Dashboard")} <= removed
    assert ("can_csv", "Superset") not in removed  # downloads stay possible


def test_m10_backend_gets_the_service_account_but_never_signs_tokens():
    services = _yaml("compose.yaml")["services"]
    backend = services["backend"]["environment"]
    assert "SUPERSET_PORTAL_SERVICE_PASSWORD" in backend
    for secret in ("SUPERSET_ADMIN_PASSWORD", "SUPERSET_GUEST_TOKEN_SECRET", "SUPERSET_SECRET_KEY"):
        assert secret not in backend, secret
    for name in ("superset", "superset-init"):
        env = services[name].get("environment") or {}
        assert "SUPERSET_GUEST_TOKEN_SECRET" in env, name
