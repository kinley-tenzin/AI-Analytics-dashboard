"""Publish validated marts: atomically swap the tested build schema into `marts`.

    python warehouse/publish.py publish --run-id <airflow run id> [--build-schema marts_build]
    python warehouse/publish.py status          # what is published now, and how fresh
    python warehouse/publish.py grant-consumers # re-apply consumer grants on the current marts

The orchestrated pipeline builds and tests marts in a hidden schema (marts_build). Only when
every test passed does it run `publish`, which in ONE transaction:
  1. grants the BI reader USAGE/SELECT on the build schema (same rights `marts` has), and each
     CONSUMER account SELECT on its APPROVED datasets only (see CONSUMERS: Superset and the Django
     KPI service),
  2. renames marts -> marts_previous and marts_build -> marts,
  3. drops marts_previous,
  4. stamps marts.data_freshness and logs the publication in raw.publication.
If anything fails, the transaction rolls back and the previously published marts stay visible.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, for druksmart_common

import psycopg  # noqa: E402
import yaml  # noqa: E402
from psycopg import sql  # noqa: E402

from druksmart_common.config import ConfigError, load_settings  # noqa: E402
from druksmart_common.db import connect  # noqa: E402

PUBLISHED = "marts"
PREVIOUS = "marts_previous"
REPO = Path(__file__).resolve().parents[1]
APPROVED_DATASETS = REPO / "superset" / "approved_datasets.yml"

# Consumer label -> (environment variable naming its DB account, approved-dataset list).
CONSUMERS = {
    "Superset": ("DRUKSMART_SUPERSET_READER_USER", APPROVED_DATASETS),
    "KPI service": ("DRUKSMART_KPI_READER_USER", REPO / "backend" / "approved_datasets.yml"),
}


def approved_relations(path: Path = APPROVED_DATASETS) -> list[str]:
    """Relations a consumer may read (default: superset/approved_datasets.yml)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != PUBLISHED:
        raise ValueError(f"{path.name}: schema must be {PUBLISHED!r}")
    return [d["relation"] for d in doc["datasets"]]


def configured_consumers() -> list[tuple[str, str | None, list[str]]]:
    """(label, DB role or None, approved relations) for every consumer."""
    return [
        (label, os.environ.get(env, "").strip() or None, approved_relations(path))
        for label, (env, path) in CONSUMERS.items()
    ]


def grant_reader(
    conn: psycopg.Connection,
    schema: str,
    role: str | None,
    relations: list[str],
    consumer: str = "Superset",
) -> list[str]:
    """Grant `role` USAGE on `schema` and SELECT on exactly `relations` (nothing else).

    Returns the granted relations. Does nothing when the role is not configured or does not exist
    yet (older .env files). Fails if an approved relation is missing, so dashboards never point at
    a dataset that publication silently dropped.
    """
    if not role:
        return []
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    if exists is None:
        return []
    present = {
        r[0]
        for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'v')",
            (schema,),
        ).fetchall()
    }
    missing = sorted(set(relations) - present)
    if missing:
        raise RuntimeError(f"approved {consumer} datasets missing from {schema!r}: {missing}")
    ident = sql.Identifier(role)
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), ident))
    for rel in relations:
        conn.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(schema, rel), ident))
    return list(relations)


grant_superset_reader = grant_reader  # name used by Milestone 6 callers and tests


def _schema_exists(conn: psycopg.Connection, name: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (name,)).fetchone()
        is not None
    )


def publish(
    conn: psycopg.Connection,
    *,
    run_id: str,
    source_mode: str,
    build_schema: str,
    bi_reader: str,
    superset_reader: str | None = None,
    superset_relations: list[str] | None = None,
    consumers: list[tuple[str, str | None, list[str]]] | None = None,
) -> dict:
    """`consumers`: (label, role, relations) granted in the same transaction (see CONSUMERS)."""
    consumers = list(consumers or [])
    if superset_reader is not None or superset_relations:
        consumers.insert(0, ("Superset", superset_reader, superset_relations or []))
    if build_schema == PUBLISHED:
        raise ValueError("build schema must differ from the published schema")
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '30s'")  # do not wait forever on BI queries
        if not _schema_exists(conn, build_schema):
            raise RuntimeError(f"build schema {build_schema!r} does not exist: nothing to publish")
        relations = conn.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'v')",
            (build_schema,),
        ).fetchone()[0]
        if relations == 0:
            raise RuntimeError(f"build schema {build_schema!r} is empty")
        data_as_of = conn.execute(
            sql.SQL(
                "SELECT coalesce(jsonb_object_agg(source_instance || '/' || domain, "
                "latest_snapshot_date), '{{}}') FROM {}.data_freshness"
            ).format(sql.Identifier(build_schema))
        ).fetchone()[0]

        build, published, previous = (
            sql.Identifier(s) for s in (build_schema, PUBLISHED, PREVIOUS)
        )
        reader = sql.Identifier(bi_reader)
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(build, reader))
        conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(build, reader))
        granted = {
            label: grant_reader(conn, build_schema, role, rels, label)
            for label, role, rels in consumers
        }
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(previous))
        if _schema_exists(conn, PUBLISHED):
            conn.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(published, previous))
        conn.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(build, published))
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(previous))
        # Default privileges belong to the schema OBJECT, not its name: re-create them so tables
        # later created directly in `marts` (manual dev builds) stay readable by the BI reader.
        conn.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
                published, reader
            )
        )
        conn.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                published,
                sql.Literal(
                    "Validated, PUBLISHED Kimball marts and KPI datasets (BI/AI read-only)."
                ),
            )
        )
        conn.execute(
            "UPDATE marts.data_freshness SET published_at = now(), pipeline_run_id = %s, "
            "source_mode = %s",
            (run_id, source_mode),
        )
        row = conn.execute(
            "INSERT INTO raw.publication (pipeline_run_id, source_mode, build_schema, relations, "
            "data_as_of) VALUES (%s, %s, %s, %s, %s) RETURNING publication_id, published_at",
            (run_id, source_mode, build_schema, relations, json.dumps(data_as_of)),
        ).fetchone()
    return {
        "publication_id": row[0],
        "published_at": row[1].isoformat(),
        "relations": relations,
        "data_as_of": data_as_of,
        "superset_datasets": granted.get("Superset", []),
        "consumer_datasets": granted,
    }


def status(conn: psycopg.Connection) -> list[tuple]:
    if not _schema_exists(conn, PUBLISHED):
        return []
    return conn.execute(
        "SELECT source_instance, domain, latest_snapshot_date, published_at, pipeline_run_id, "
        "source_mode FROM marts.data_freshness ORDER BY 1, 2"
    ).fetchall()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--run-id", required=True)
    pub.add_argument("--build-schema", default="marts_build")
    sub.add_parser("status")
    sub.add_parser("grant-consumers")
    sub.add_parser("grant-superset", help="alias of grant-consumers")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    with connect(settings.pipeline(), autocommit=True) as conn:
        if args.command == "publish":
            mode = os.environ.get("DRUKSMART_SOURCE_MODE", "configured")
            result = publish(
                conn,
                run_id=args.run_id,
                source_mode=mode,
                build_schema=args.build_schema,
                bi_reader=settings.bi_reader_user,
                consumers=configured_consumers(),
            )
            print(
                f"PUBLISHED {result['relations']} relations as publication "
                f"{result['publication_id']} at {result['published_at']}"
            )
            print(f"data as of: {json.dumps(result['data_as_of'], sort_keys=True)}")
            for label, granted in result["consumer_datasets"].items():
                print(f"{label} datasets granted: {granted or 'none'}")
        elif args.command in ("grant-consumers", "grant-superset"):
            with conn.transaction():
                for label, role, rels in configured_consumers():
                    granted = grant_reader(conn, PUBLISHED, role, rels, label)
                    print(f"{label} datasets granted: {granted or 'none (role not configured)'}")
        else:
            rows = status(conn)
            if not rows:
                print("nothing published yet")
            for r in rows:
                instance, domain, as_of, published, run, mode = r
                print(f"{instance:<24} {domain:<9} data as of {as_of}  published {published}  "
                      f"run {run}  ({mode})")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
