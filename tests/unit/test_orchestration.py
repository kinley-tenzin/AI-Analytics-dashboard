"""Static checks for the orchestration files (the DAG itself is validated inside Airflow)."""

import ast
import re
import tomllib

import pytest

from connectors.synthetic import fake_api
from druksmart_common.config import REPO_ROOT
from ingestion import cli

ORCH = REPO_ROOT / "orchestration"


def _pins(lines):
    out = {}
    for line in lines:
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==")
            out[re.sub(r"\[.*\]", "", name).strip().lower()] = version.strip()
    return out


def test_image_requirements_match_pyproject_pins():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    expected = _pins(project["dependencies"] + project["optional-dependencies"]["warehouse"])
    image = _pins((ORCH / "docker" / "requirements-pipeline.txt").read_text("utf-8").splitlines())
    assert image == expected


def test_synthetic_mode_env_matches_the_synthetic_service():
    values = dict(
        line.split("=", 1)
        for line in (ORCH / "synthetic_mode.env").read_text("utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert values["ODOO_API_KEY"] == fake_api.ODOO_KEY
    assert values["ERPNEXT_API_KEY"] == fake_api.ERP_KEY
    assert values["ERPNEXT_API_SECRET"] == fake_api.ERP_SECRET
    instances = fake_api.fixture_instances()
    assert values["ODOO_INSTANCE_ID"] == instances["odoo"]
    assert values["ERPNEXT_INSTANCE_ID"] == instances["erpnext"]


def test_shell_script_uses_unix_line_endings():
    assert b"\r\n" not in (ORCH / "bin" / "run_step.sh").read_bytes()


def test_dag_declares_every_pipeline_stage_and_no_business_logic():
    source = (ORCH / "dags" / "druksmart_elt.py").read_text("utf-8")
    ast.parse(source)
    for task_id in (
        "validate_",
        "prepare_raw_schema",
        "extract_load_",
        "dbt_staging_intermediate",
        "dbt_build_marts",
        "dbt_test_marts",
        "publish_validated_marts",
    ):
        assert task_id in source
    # the DAG must delegate to the project's CLIs, not import connectors / ingestion / dbt
    imports = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imports if m and m.split(".")[0] in {"connectors", "ingestion", "dbt"}}


@pytest.mark.parametrize("mode", ["configured", ""])
def test_as_of_is_refused_outside_synthetic_mode(monkeypatch, mode):
    monkeypatch.setenv("DRUKSMART_SOURCE_MODE", mode or "configured")
    with pytest.raises(cli.ConfigError, match="synthetic"):
        cli._as_of("2026-10-31T17:30:00Z")


def test_as_of_needs_a_time_zone_in_synthetic_mode(monkeypatch):
    monkeypatch.setenv("DRUKSMART_SOURCE_MODE", "synthetic")
    with pytest.raises(cli.ConfigError, match="time zone"):
        cli._as_of("2026-10-31T17:30:00")
    clock = cli._as_of("2026-10-31T17:30:00Z")["now"]
    assert clock().isoformat() == "2026-10-31T17:30:00+00:00"
