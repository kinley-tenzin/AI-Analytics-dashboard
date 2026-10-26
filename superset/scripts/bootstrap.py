"""Configure Superset from the version-controlled definitions (idempotent; safe to re-run).

    python superset/scripts/bootstrap.py            # everything
    python superset/scripts/bootstrap.py --check    # only test the warehouse connection

Steps (each creates the object when missing and otherwise UPDATES it to match the definitions):
  1. database connection "DrukSmart Warehouse" with the dedicated read-only account
     (DRUKSMART_SUPERSET_READER_USER), read-only transactions, no DML/CTAS/uploads;
  2. datasets for superset/approved_datasets.yml with labels and certified metrics
     (superset/definitions/datasets.yml);
  3. roles, their permissions and dataset access (superset/definitions/access.yml);
  4. default HR and Accounts dashboards with charts and native filters
     (superset/definitions/dashboards.py), owned by the admin and restricted to their roles;
  5. row-level security rules and demo users (local testing only); roles and demo users of
     earlier milestones listed under `retired_*` are removed;
  6. embedding in the DrukSmart website (Milestone 10): embedded configuration of the default
     dashboards (only DRUKSMART_WEB_ORIGIN may frame them) and the website backend's service
     account (SUPERSET_PORTAL_SERVICE_USER / _PASSWORD), which only issues guest tokens.

Reads settings from .env and never prints passwords. Superset must be running
(`docker compose --profile superset up -d`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
SUPERSET_DIR = HERE.parent
REPO = SUPERSET_DIR.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SUPERSET_DIR / "definitions"))

from dashboards import DASHBOARDS  # noqa: E402
from superset_api import SupersetClient, SupersetError  # noqa: E402

DATABASE_NAME = "DrukSmart Warehouse"
SCHEMA = "marts"
PLACEHOLDER = "CHANGE_ME"

COLUMN_PUT_KEYS = {
    "id",
    "column_name",
    "type",
    "advanced_data_type",
    "verbose_name",
    "description",
    "expression",
    "extra",
    "filterable",
    "groupby",
    "is_active",
    "is_dttm",
    "python_date_format",
    "datetime_format",
    "uuid",
}


def setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default if default is not None else "").strip()
    if not value or value == PLACEHOLDER:
        raise SystemExit(f"CONFIG ERROR: {name} is not set in .env (see .env.example)")
    return value


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('SUPERSET_PORT', '8088').strip() or '8088'}"


def admin_client() -> SupersetClient:
    return SupersetClient.login(
        base_url(), setting("SUPERSET_ADMIN_USER"), setting("SUPERSET_ADMIN_PASSWORD")
    )


# ---------------------------------------------------------------------------- 1. database
def database_payload() -> dict:
    user = setting("DRUKSMART_SUPERSET_READER_USER")
    password = setting("DRUKSMART_SUPERSET_READER_PASSWORD")
    db = setting("DRUKSMART_ANALYTICS_DB")
    # Fallback demonstrations read the SYNTHETIC test database (labelled in the freshness tables).
    if os.environ.get("DRUKSMART_CONSUMER_DATA", "live").strip().lower() == "synthetic":
        db += "_test"
    # Inside the compose network the warehouse is the `postgres` service on 5432.
    host = os.environ.get("SUPERSET_WAREHOUSE_HOST", "postgres:5432")
    uri = f"postgresql+psycopg2://{quote(user, safe='')}:{quote(password, safe='')}@{host}/{db}"
    extra = {
        "allows_virtual_table_explore": False,
        "schemas_allowed_for_file_upload": [],
        "metadata_params": {},
        # Defence in depth: every session is read-only and statements are time-limited, on top of
        # the account having SELECT on the approved relations only.
        "engine_params": {
            "connect_args": {
                "connect_timeout": 10,
                "options": "-c default_transaction_read_only=on -c statement_timeout=60000",
            }
        },
    }
    return {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": uri,
        "expose_in_sqllab": True,  # only Admin has SQL Lab; it sees the same approved relations
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "allow_file_upload": False,
        "allow_run_async": False,
        "extra": json.dumps(extra),
    }


def test_connection(api: SupersetClient, payload: dict) -> None:
    keys = ("database_name", "sqlalchemy_uri", "extra")
    api.post("/api/v1/database/test_connection/", {k: payload[k] for k in keys})


def ensure_database(api: SupersetClient) -> int:
    payload = database_payload()
    test_connection(api, payload)
    existing = api.find_one("database", "database_name", DATABASE_NAME)
    if existing:
        api.put(f"/api/v1/database/{existing['id']}", payload)
        print(f"[database] updated {DATABASE_NAME!r} (id {existing['id']}); connection OK")
        return existing["id"]
    created = api.post("/api/v1/database/", payload)
    print(f"[database] created {DATABASE_NAME!r} (id {created['id']}); connection OK")
    return created["id"]


# ---------------------------------------------------------------------------- 2. datasets
def ensure_datasets(api: SupersetClient, database_id: int, admin_id: int) -> dict[str, dict]:
    approved = load_yaml(SUPERSET_DIR / "approved_datasets.yml")
    approved_tables = [d["relation"] for d in approved["datasets"]]
    spec = load_yaml(SUPERSET_DIR / "definitions" / "datasets.yml")
    defined = {d["table"]: d for d in spec["datasets"]}
    if set(defined) != set(approved_tables):
        raise SystemExit(
            "datasets.yml must define exactly the approved datasets; "
            f"approved={sorted(approved_tables)} defined={sorted(defined)}"
        )

    existing = {
        (d["schema"], d["table_name"]): d
        for d in api.list_all(
            "dataset", [{"col": "database", "opr": "rel_o_m", "value": database_id}]
        )
    }
    result: dict[str, dict] = {}
    for table in approved_tables:
        ds = defined[table]
        row = existing.get((SCHEMA, table))
        if row is None:
            ds_id = api.post(
                "/api/v1/dataset/",
                {
                    "database": database_id,
                    "schema": SCHEMA,
                    "table_name": table,
                    "owners": [admin_id],
                },
            )["id"]
            action = "created"
        else:
            ds_id = row["id"]
            action = "updated"
        api.put(f"/api/v1/dataset/{ds_id}/refresh")  # pick up columns added in dbt
        current = api.get(f"/api/v1/dataset/{ds_id}")["result"]
        payload = dataset_payload(ds, current, spec["certified_by"], admin_id)
        api.put(f"/api/v1/dataset/{ds_id}?override_columns=false", payload)
        result[table] = {"id": ds_id, "columns": set(c["column_name"] for c in payload["columns"])}
        print(
            f"[dataset] {action} {SCHEMA}.{table} (id {ds_id}): "
            f"{len(payload['columns'])} columns, {len(payload['metrics'])} certified metrics"
        )
    return result


def dataset_payload(ds: dict, current: dict, certified_by: str, admin_id: int) -> dict:
    labels = ds.get("columns", {})
    present = {c["column_name"] for c in current["columns"] if not c.get("expression")}
    unknown = sorted(set(labels) - present)
    if unknown:
        raise SystemExit(f"{ds['table']}: columns in datasets.yml not in the view: {unknown}")
    columns = []
    calculated = set(ds.get("calculated_columns") or {})
    for col in current["columns"]:
        if col["column_name"] in calculated:
            continue  # re-declared below from datasets.yml
        spec = labels.get(col["column_name"], {})
        c = {k: v for k, v in col.items() if k in COLUMN_PUT_KEYS and v is not None}
        c["verbose_name"] = spec.get("label", col.get("verbose_name"))
        c["is_dttm"] = bool(spec.get("is_dttm", col.get("is_dttm")))
        c["groupby"] = spec.get("groupby", True)
        c["filterable"] = spec.get("filterable", True)
        columns.append({k: v for k, v in c.items() if v is not None})
    existing = {c["column_name"]: c for c in current["columns"]}
    for name, spec in (ds.get("calculated_columns") or {}).items():
        col = {
            "column_name": name,
            "verbose_name": spec["label"],
            "expression": spec["expression"],
            "type": spec.get("type"),
            "groupby": False,
            "filterable": False,
            "is_dttm": False,
        }
        if name in existing and existing[name].get("id"):
            col["id"] = existing[name]["id"]
        columns.append(col)

    existing_metrics = {m["metric_name"]: m for m in current.get("metrics", [])}
    metrics = []
    for m in ds["metrics"]:
        metric = {
            "metric_name": m["name"],
            "verbose_name": m["label"],
            "expression": m["expression"],
            "description": m.get("description"),
            "d3format": m.get("format"),
            "warning_text": m.get("warning"),
            "extra": json.dumps(
                {"certification": {"certified_by": certified_by, "details": f"KPI {m['kpi']}"}}
            ),
        }
        if m.get("currency"):
            metric["currency"] = {"symbol": m["currency"], "symbolPosition": "prefix"}
        if m["name"] in existing_metrics:
            metric["id"] = existing_metrics[m["name"]]["id"]
        metrics.append({k: v for k, v in metric.items() if v is not None})

    payload = {
        "description": " ".join(ds["description"].split()),
        "main_dttm_col": ds.get("main_dttm_col"),
        "currency_code_column": ds.get("currency_code_column"),
        "filter_select_enabled": True,
        "is_managed_externally": True,  # locks the governed definitions in the Superset UI
        "external_url": None,
        "owners": [admin_id],
        "columns": columns,
        "metrics": metrics,
    }
    return {k: v for k, v in payload.items() if v is not None or k == "external_url"}


# ---------------------------------------------------------------------------- 3. roles
def permission_index(api: SupersetClient) -> dict[tuple[str, str], int]:
    return {
        (p["permission"]["name"], p["view_menu"]["name"]): p["id"]
        for p in api.list_all("security/permissions-resources")
    }


def role_ids(api: SupersetClient) -> dict[str, int]:
    return {r["name"]: r["id"] for r in api.list_all("security/roles")}


def base_permissions(
    api: SupersetClient, base: dict, roles: dict[str, int], index: dict[tuple[str, str], int]
) -> set[int]:
    perms = api.get(f"/api/v1/security/roles/{roles[base['from']]}/permissions/")["result"]
    removed = [tuple(r) for r in base["remove"]]
    keep = set()
    for p in perms:
        pair = (p["permission_name"], p["view_menu_name"])
        if any(r[1] == pair[1] and r[0] in ("*", pair[0]) for r in removed):
            continue
        keep.add(p["id"])
    for name, view in base.get("add", []):
        if (name, view) not in index:
            raise SystemExit(f"permission {(name, view)} not found in this Superset version")
        keep.add(index[(name, view)])
    return keep


def ensure_roles(api: SupersetClient, access: dict, datasets: dict[str, dict]) -> dict[str, int]:
    roles = role_ids(api)
    for spec in access["roles"]:
        if spec["name"] not in roles:
            roles[spec["name"]] = api.post("/api/v1/security/roles/", {"name": spec["name"]})["id"]
    # superset creates `datasource_access` permissions together with the datasets.
    index = permission_index(api)
    bases = {name: base_permissions(api, b, roles, index) for name, b in access["bases"].items()}
    for spec in access["roles"]:
        perms = set(bases[spec["base"]])
        tables = sorted({t for d in spec["domains"] for t in access["domains"][d]})
        for table in tables:
            view = f"[{DATABASE_NAME}].[{table}](id:{datasets[table]['id']})"
            key = ("datasource_access", view)
            if key not in index:
                raise SystemExit(f"permission {key} not found; is the dataset registered?")
            perms.add(index[key])
        api.post(
            f"/api/v1/security/roles/{roles[spec['name']]}/permissions",
            {"permission_view_menu_ids": sorted(perms)},
        )
        actual = api.get(f"/api/v1/security/roles/{roles[spec['name']]}/permissions/")["result"]
        if {p["id"] for p in actual} != perms:
            raise SystemExit(f"role {spec['name']}: permissions were not set exactly")
        print(f"[role] {spec['name']}: {len(perms)} permissions, datasets {tables}")
    return roles


# ---------------------------------------------------------------------------- 4. dashboards
def native_filter(f: dict, charts: dict[str, int], chart_keys: list[str], datasets: dict) -> dict:
    if f["scope"] == "all_except_freshness":
        in_scope = [k for k in chart_keys if not k.endswith("_freshness")]
    else:
        in_scope = list(f["scope"])
    # A filter on a column must only reach charts whose dataset HAS that column.
    if f["type"] == "select":
        column = f["target"][1]
        in_scope = [k for k in in_scope if column in datasets[_chart_dataset[k]]["columns"]]
    in_ids = [charts[k] for k in in_scope]
    excluded = [charts[k] for k in chart_keys if k not in in_scope]
    config = {
        "id": f["id"],
        "name": f["name"],
        "type": "NATIVE_FILTER",
        "description": f.get("description", ""),
        "cascadeParentIds": [f["parent"]] if f.get("parent") else [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
        "chartsInScope": in_ids,
        "tabsInScope": [],
        "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
    }
    if f["type"] == "time":
        config.update(
            filterType="filter_time",
            targets=[{}],
            controlValues={"enableEmptyFilter": False},
        )
    else:
        table, column = f["target"]
        config.update(
            filterType="filter_select",
            targets=[{"datasetId": datasets[table]["id"], "column": {"name": column}}],
            controlValues={
                "enableEmptyFilter": bool(f.get("required")),
                "defaultToFirstItem": bool(f.get("default_first")),
                "multiSelect": not f.get("single", False),
                "searchAllOptions": False,
                "inverseSelection": False,
                "sortAscending": f.get("sort_ascending", True),
            },
        )
        if f.get("default_first"):
            # Without this flag (set by the UI's "Select first filter value by default") the first
            # value is SHOWN but not APPLIED, and charts load unfiltered; found by browser_check.py.
            config["requiredFirst"] = True
    return config


_chart_dashboard: dict[str, str] = {}
_chart_dataset: dict[str, str] = {}


def layout(dash: dict, charts: dict[str, int], names: dict[str, str]) -> dict:
    pos: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": dash["title"]}},
    }
    for r, row in enumerate(dash["rows"], start=1):
        row_id = f"ROW-{dash['key']}-{r}"
        pos["GRID_ID"]["children"].append(row_id)
        pos[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for key, width, height in row:
            parents = ["ROOT_ID", "GRID_ID", row_id]
            if key == "MARKDOWN":
                item_id = f"MARKDOWN-{dash['key']}-intro"
                pos[item_id] = {
                    "type": "MARKDOWN",
                    "id": item_id,
                    "children": [],
                    "parents": parents,
                    "meta": {"width": width, "height": height, "code": dash["intro"]},
                }
            else:
                item_id = f"CHART-{key}"
                pos[item_id] = {
                    "type": "CHART",
                    "id": item_id,
                    "children": [],
                    "parents": parents,
                    "meta": {
                        "width": width,
                        "height": height,
                        "chartId": charts[key],
                        "sliceName": names[key],
                        "uuid": None,
                    },
                }
                del pos[item_id]["meta"]["uuid"]
            pos[row_id]["children"].append(item_id)
    return pos


def cross_filter_config(dash: dict, charts: dict[str, int], datasets: dict) -> dict:
    """Cross-filtering: a click on a chart filters the other charts that have the clicked column."""
    config = {}
    for c in dash["charts"]:
        dims = set(c["params"].get("groupby", [])) | (
            {c["params"]["x_axis"]} if "x_axis" in c["params"] else set()
        )
        targets = [
            o["key"]
            for o in dash["charts"]
            if o["key"] != c["key"]
            and dims
            and dims <= datasets[o["dataset"]]["columns"]
            and not o["key"].endswith("_freshness")
        ]
        config[str(charts[c["key"]])] = {
            "id": charts[c["key"]],
            "crossFilters": {
                "scope": {
                    "rootPath": ["ROOT_ID"],
                    "excluded": [
                        charts[o["key"]] for o in dash["charts"] if o["key"] not in targets
                    ],
                },
                "chartsInScope": [charts[k] for k in targets],
            },
        }
    return config


def ensure_dashboards(
    api: SupersetClient, datasets: dict, admin_id: int, roles: dict[str, int], access: dict
) -> dict[str, int]:
    result = {}
    for dash in DASHBOARDS:
        dash_roles = [roles[r["name"]] for r in access["roles"] if dash["key"] in r["dashboards"]]
        existing = api.find_one("dashboard", "slug", dash["slug"])
        base = {
            "dashboard_title": dash["title"],
            "slug": dash["slug"],
            "published": True,
            "owners": [admin_id],
            "roles": dash_roles,
        }
        if existing:
            dash_id = existing["id"]
            api.put(f"/api/v1/dashboard/{dash_id}", base)
        else:
            dash_id = api.post("/api/v1/dashboard/", base)["id"]

        charts: dict[str, int] = {}
        names: dict[str, str] = {}
        for c in dash["charts"]:
            _chart_dataset[c["key"]] = c["dataset"]
            ds_id = datasets[c["dataset"]]["id"]
            params = dict(c["params"], datasource=f"{ds_id}__table")
            payload = {
                "slice_name": c["slice_name"],
                "viz_type": params["viz_type"],
                "datasource_id": ds_id,
                "datasource_type": "table",
                "params": json.dumps(params),
                "owners": [admin_id],
                "dashboards": [dash_id],
                "description": f"Default {dash['title']} chart (template, bootstrap.py).",
            }
            found = [
                ch
                for ch in api.list_all(
                    "chart", [{"col": "slice_name", "opr": "eq", "value": c["slice_name"]}]
                )
                if any(d.get("id") == dash_id for d in ch.get("dashboards", []))
                or not ch.get("dashboards")
            ]
            if found:
                charts[c["key"]] = found[0]["id"]
                api.put(f"/api/v1/chart/{found[0]['id']}", payload)
            else:
                charts[c["key"]] = api.post("/api/v1/chart/", payload)["id"]
            names[c["key"]] = c["slice_name"]

        keys = [c["key"] for c in dash["charts"]]
        metadata = {
            "native_filter_configuration": [
                native_filter(f, charts, keys, datasets) for f in dash["filters"]
            ],
            "cross_filters_enabled": True,
            "chart_configuration": cross_filter_config(dash, charts, datasets),
            "global_chart_configuration": {
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                "chartsInScope": [charts[k] for k in keys],
            },
            "color_scheme": "supersetColors",
            "refresh_frequency": 0,
            "expanded_slices": {},
            "label_colors": {},
            "timed_refresh_immune_slices": [],
            "default_filters": "{}",
        }
        api.put(
            f"/api/v1/dashboard/{dash_id}",
            {
                "position_json": json.dumps(layout(dash, charts, names)),
                "json_metadata": json.dumps(metadata),
            },
        )
        result[dash["key"]] = dash_id
        print(
            f"[dashboard] {dash['title']!r} (id {dash_id}, /superset/dashboard/{dash['slug']}/): "
            f"{len(charts)} charts, {len(dash['filters'])} native filters"
        )
    return result


# ---------------------------------------------------------------------------- 5. RLS, users
def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_rls(api: SupersetClient, access: dict, roles: dict[str, int], datasets: dict) -> None:
    existing = {r["name"]: r for r in api.list_all("rowlevelsecurity")}
    for rule in access.get("row_level_security", []):
        payload = {
            "name": rule["name"],
            "description": rule.get("description", ""),
            "filter_type": "Regular",
            "tables": [datasets[t]["id"] for t in rule["tables"]],
            "roles": [roles[rule["role"]]],
            "group_key": rule.get("group_key", ""),
            "clause": "branch_key IN ("
            + ", ".join(sql_literal(k) for k in rule["branch_keys"])
            + ")",
        }
        if rule["name"] in existing:
            api.put(f"/api/v1/rowlevelsecurity/{existing[rule['name']]['id']}", payload)
        else:
            api.post("/api/v1/rowlevelsecurity/", payload)
        print(f"[rls] {rule['name']!r}: role {rule['role']!r}, {len(rule['tables'])} datasets")


def ensure_demo_users(api: SupersetClient, access: dict, roles: dict[str, int]) -> None:
    password = os.environ.get("SUPERSET_DEMO_USER_PASSWORD", "").strip()
    if not password or password == PLACEHOLDER:
        print("[users] SUPERSET_DEMO_USER_PASSWORD not set: demo users skipped")
        return
    existing = {u["username"]: u for u in api.list_all("security/users")}
    for u in access.get("demo_users", []):
        payload = {
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "username": u["username"],
            "email": f"{u['username']}@example.com",
            "active": True,
            "roles": [roles[u["role"]]],
            "password": password,
        }
        if u["username"] in existing:
            api.put(f"/api/v1/security/users/{existing[u['username']]['id']}", payload)
        else:
            api.post("/api/v1/security/users/", payload)
        print(f"[users] {u['username']} -> {u['role']}")


def retire(api: SupersetClient, access: dict) -> None:
    """Remove roles and demo users of earlier milestones (ADR-044). Runs after the demo users
    were moved to their new roles; real users must be given a current role by the admin first."""
    for username in access.get("retired_demo_users", []):
        user = api.find_one("security/users", "username", username)
        if not user:
            continue
        try:
            api.delete(f"/api/v1/security/users/{user['id']}")
            print(f"[retire] demo user {username} removed")
        except SupersetError:
            # Still referenced (e.g. a saved Explore state or permalink): deactivate instead,
            # which blocks sign-in and keeps Superset's records intact.
            api.put(f"/api/v1/security/users/{user['id']}", {"active": False})
            print(f"[retire] demo user {username} deactivated (still referenced by saved state)")
    roles = role_ids(api)
    for name in access.get("retired_roles", []):
        if name in roles:
            api.delete(f"/api/v1/security/roles/{roles[name]}")
            print(f"[retire] role {name!r} removed")


# ---------------------------------------------------------------------------- 6. embedding
def web_origin() -> str:
    return setting("DRUKSMART_WEB_ORIGIN", "http://127.0.0.1:8000").rstrip("/")


def ensure_embedding(api: SupersetClient, access: dict, dashboards: dict[str, int]) -> None:
    """Embedded configuration of the default dashboards: only the website may frame them."""
    for key in access["embedding"]["dashboards"]:
        embedded = api.put(
            f"/api/v1/dashboard/{dashboards[key]}/embedded", {"allowed_domains": [web_origin()]}
        )["result"]
        print(f"[embedding] dashboard {key!r}: embedded id {embedded['uuid']} ({web_origin()})")


def ensure_service_user(api: SupersetClient, access: dict, roles: dict[str, int]) -> None:
    """The account the website backend uses to issue guest tokens (password from .env)."""
    username = setting("SUPERSET_PORTAL_SERVICE_USER", "druksmart_portal_service")
    password = os.environ.get("SUPERSET_PORTAL_SERVICE_PASSWORD", "").strip()
    if not password or password == PLACEHOLDER:
        print("[embedding] SUPERSET_PORTAL_SERVICE_PASSWORD not set: service account skipped")
        return
    spec = access["embedding"]
    payload = {
        **spec["service_user"],
        "username": username,
        "email": f"{username}@example.com",
        "active": True,
        "roles": [roles[spec["service_role"]]],
        "password": password,
    }
    existing = api.find_one("security/users", "username", username)
    if existing:
        api.put(f"/api/v1/security/users/{existing['id']}", payload)
    else:
        api.post("/api/v1/security/users/", payload)
    print(f"[embedding] service account {username} -> {spec['service_role']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only test the warehouse connection")
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env", override=False)
    try:
        api = admin_client()
    except SupersetError as exc:
        print(f"cannot log in to Superset at {base_url()} as SUPERSET_ADMIN_USER: {exc}")
        return 1
    with api:
        if args.check:
            test_connection(api, database_payload())
            print("[database] connection OK")
            return 0
        admin_id = api.get("/api/v1/me/")["result"]["id"]
        access = load_yaml(SUPERSET_DIR / "definitions" / "access.yml")
        database_id = ensure_database(api)
        datasets = ensure_datasets(api, database_id, admin_id)
        roles = ensure_roles(api, access, datasets)
        dashboards = ensure_dashboards(api, datasets, admin_id, roles, access)
        ensure_rls(api, access, roles, datasets)
        ensure_demo_users(api, access, roles)
        retire(api, access)
        ensure_embedding(api, access, dashboards)
        ensure_service_user(api, access, roles)
    print("bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
