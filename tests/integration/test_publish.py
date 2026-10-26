"""Atomic publication of tested marts (warehouse/publish.py), in the isolated _test database.

Uses throw-away objects; the warehouse test (pytest -m warehouse) rebuilds its marts anyway.
"""

import importlib.util
from dataclasses import replace

import psycopg
import pytest

from druksmart_common.config import REPO_ROOT, load_settings
from druksmart_common.db import connect
from ingestion.migrate import apply_migrations

pytestmark = pytest.mark.db

spec = importlib.util.spec_from_file_location("publish", REPO_ROOT / "warehouse" / "publish.py")
publish_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_module)


@pytest.fixture
def conn():
    settings = load_settings()
    with connect(settings.pipeline_test(), autocommit=True) as c:
        assert c.execute("select current_database()").fetchone()[0].endswith("_test")
        apply_migrations(c)
        yield c
        c.execute("DROP SCHEMA IF EXISTS pub_build_test CASCADE")


def _build(conn, value):
    conn.execute("DROP SCHEMA IF EXISTS pub_build_test CASCADE")
    conn.execute("CREATE SCHEMA pub_build_test")
    conn.execute("CREATE TABLE pub_build_test.kpi_sample (value int)")
    conn.execute("INSERT INTO pub_build_test.kpi_sample VALUES (%s)", (value,))
    conn.execute(
        "CREATE TABLE pub_build_test.data_freshness AS SELECT 'inst'::text AS source_instance, "
        "'hr'::text AS domain, date '2026-10-31' AS latest_snapshot_date, "
        "null::timestamptz AS published_at, null::text AS pipeline_run_id, "
        "null::text AS source_mode"
    )
    conn.execute(
        "CREATE VIEW pub_build_test.kpi_view AS SELECT value FROM pub_build_test.kpi_sample"
    )


def _bi(settings):
    return connect(replace(settings.bi_reader(), dbname=settings.analytics_test_db))


def test_publish_swaps_atomically_and_bi_reader_sees_only_published(conn):
    settings = load_settings()
    _build(conn, 1)
    result = publish_module.publish(
        conn,
        run_id="test-run-1",
        source_mode="synthetic",
        build_schema="pub_build_test",
        bi_reader=settings.bi_reader_user,
    )
    assert result["relations"] == 3 and result["data_as_of"] == {"inst/hr": "2026-10-31"}
    with _bi(settings) as bi:
        assert bi.execute("select value from marts.kpi_view").fetchone()[0] == 1
        stamp = bi.execute(
            "select pipeline_run_id, source_mode from marts.data_freshness"
        ).fetchone()
        assert stamp == ("test-run-1", "synthetic")
    schemas = {r[0] for r in conn.execute("select nspname from pg_namespace")}
    assert "pub_build_test" not in schemas and "marts_previous" not in schemas
    logged = conn.execute(
        "select pipeline_run_id from raw.publication order by publication_id desc limit 1"
    ).fetchone()[0]
    assert logged == "test-run-1"


def test_failed_publication_leaves_published_marts_untouched(conn):
    settings = load_settings()
    _build(conn, 1)
    publish_module.publish(
        conn,
        run_id="good",
        source_mode="synthetic",
        build_schema="pub_build_test",
        bi_reader=settings.bi_reader_user,
    )
    with pytest.raises(RuntimeError, match="does not exist"):  # e.g. tests failed, no build schema
        publish_module.publish(
            conn,
            run_id="bad",
            source_mode="synthetic",
            build_schema="pub_build_test",
            bi_reader=settings.bi_reader_user,
        )
    with _bi(settings) as bi:
        assert (
            bi.execute("select pipeline_run_id from marts.data_freshness").fetchone()[0] == "good"
        )


def test_bi_reader_cannot_read_an_unpublished_build_schema(conn):
    _build(conn, 2)
    with _bi(load_settings()) as bi, pytest.raises(psycopg.errors.InsufficientPrivilege):
        bi.execute("select * from pub_build_test.kpi_sample")


def test_new_tables_in_published_marts_stay_readable(conn):
    settings = load_settings()
    _build(conn, 3)
    publish_module.publish(
        conn,
        run_id="r",
        source_mode="synthetic",
        build_schema="pub_build_test",
        bi_reader=settings.bi_reader_user,
    )
    conn.execute("CREATE TABLE marts.later_table AS SELECT 1 AS x")  # e.g. a manual dev build
    try:
        with _bi(settings) as bi:
            assert bi.execute("select x from marts.later_table").fetchone()[0] == 1
    finally:
        conn.execute("DROP TABLE marts.later_table")


def _superset_reader(settings):
    import os

    user = os.environ.get("DRUKSMART_SUPERSET_READER_USER", "")
    password = os.environ.get("DRUKSMART_SUPERSET_READER_PASSWORD", "")
    if not user or not password or password == "CHANGE_ME":
        pytest.skip("Superset reader not configured in .env")
    return user, connect(
        replace(
            settings.bi_reader(), dbname=settings.analytics_test_db, user=user, password=password
        )
    )


def test_superset_reader_gets_only_the_approved_relations(conn):
    settings = load_settings()
    user, reader = _superset_reader(settings)
    _build(conn, 4)
    result = publish_module.publish(
        conn,
        run_id="r",
        source_mode="synthetic",
        build_schema="pub_build_test",
        bi_reader=settings.bi_reader_user,
        superset_reader=user,
        superset_relations=["kpi_view", "data_freshness"],
    )
    assert result["superset_datasets"] == ["kpi_view", "data_freshness"]
    with reader:
        assert reader.execute("select value from marts.kpi_view").fetchone()[0] == 4
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("select * from marts.kpi_sample")  # published, but not approved


def test_publication_fails_when_an_approved_dataset_is_missing(conn):
    settings = load_settings()
    user, reader = _superset_reader(settings)
    reader.close()
    _build(conn, 5)
    with pytest.raises(RuntimeError, match="approved Superset datasets missing"):
        publish_module.publish(
            conn,
            run_id="r",
            source_mode="synthetic",
            build_schema="pub_build_test",
            bi_reader=settings.bi_reader_user,
            superset_reader=user,
            superset_relations=["kpi_view", "kpi_that_dbt_dropped"],
        )
    schemas = {r[0] for r in conn.execute("select nspname from pg_namespace")}
    assert "pub_build_test" in schemas, "a failed publication must leave the build unpublished"


def test_approved_dataset_list_is_valid():
    relations = publish_module.approved_relations()
    assert relations and len(relations) == len(set(relations))
    assert not any(r.startswith(("stg_", "int_", "dim_")) for r in relations)
