"""Export / import Superset dashboards as version-controlled assets (Superset's native format).

    python superset/scripts/assets.py export     # dashboards -> superset/assets/dashboards/ (YAML)
    python superset/scripts/assets.py import     # superset/assets/dashboards/ -> Superset

`export` writes every dashboard the admin can see (default templates AND dashboards authors saved
in the UI) together with their charts, datasets and the database connection, as plain YAML so
changes show up in `git diff`. The database password is never exported (Superset masks it).

`import` zips the folder back and uploads it with overwrite=true; the warehouse password is
supplied from .env (DRUKSMART_SUPERSET_READER_PASSWORD). Roles, row-level security and users are
NOT part of Superset's export format: they are restored by `bootstrap.py` from access.yml.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bootstrap import REPO, admin_client, setting  # noqa: E402
from superset_api import rison  # noqa: E402

ASSETS = REPO / "superset" / "assets" / "dashboards"
BUNDLE = "druksmart_assets"


def export_assets(api, target: Path = ASSETS) -> list[str]:
    ids = [d["id"] for d in api.list_all("dashboard")]
    if not ids:
        raise SystemExit("no dashboards to export")
    resp = api.request("GET", "/api/v1/dashboard/export/", params={"q": rison(ids)})
    if resp.status_code != 200:
        raise SystemExit(f"export failed: HTTP {resp.status_code} {resp.text[:300]}")
    if target.exists():
        shutil.rmtree(target)
    written = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            # Strip the timestamped top folder (dashboard_export_YYYYMMDDTHHMMSS/...).
            rel = Path(*Path(name).parts[1:])
            if not rel.parts or rel.name == "metadata.yaml":
                continue  # metadata.yaml only holds the export timestamp; re-created on import
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name).replace(b"\r\n", b"\n"))
            written.append(rel.as_posix())
    return sorted(written)


# Superset's dashboard import overwrites ONLY the dashboard; its charts and datasets are created
# when missing but never overwritten (verified in Milestone 6). A full restore therefore imports
# each asset type with its own endpoint, dependencies first.
IMPORT_PASSES = [
    ("SqlaTable", "dataset", ("databases", "datasets")),
    ("Slice", "chart", ("databases", "datasets", "charts")),
    ("Dashboard", "dashboard", ("databases", "datasets", "charts", "dashboards")),
]


def _bundle(source: Path, kind: str, folders: tuple[str, ...]) -> tuple[bytes, int]:
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{BUNDLE}/metadata.yaml",
            f"version: 1.0.0\ntype: {kind}\ntimestamp: '2026-01-01T00:00:00+00:00'\n",
        )
        for folder in folders:
            for f in sorted((source / folder).rglob("*.yaml")):
                zf.write(f, f"{BUNDLE}/{f.relative_to(source).as_posix()}")
                count += 1
    return buf.getvalue(), count


def import_assets(api, source: Path = ASSETS) -> list[tuple[str, int]]:
    if not any(source.rglob("*.yaml")):
        raise SystemExit(f"nothing to import in {source}")
    passwords = json.dumps(
        {
            f"databases/{p.name}": setting("DRUKSMART_SUPERSET_READER_PASSWORD")
            for p in (source / "databases").glob("*.yaml")
        }
    )
    done = []
    for kind, resource, folders in IMPORT_PASSES:
        content, count = _bundle(source, kind, folders)
        resp = api.request(
            "POST",
            f"/api/v1/{resource}/import/",
            files={"formData": (f"{resource}s.zip", content, "application/zip")},
            data={"overwrite": "true", "passwords": passwords},
        )
        if resp.status_code != 200:
            raise SystemExit(f"{resource} import failed: HTTP {resp.status_code} {resp.text[:500]}")
        done.append((resource, count))
    return done


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["export", "import"])
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env", override=False)
    os.environ.setdefault("SUPERSET_PORT", "8088")
    with admin_client() as api:
        if args.command == "export":
            written = export_assets(api)
            print(f"exported {len(written)} files to {ASSETS.relative_to(REPO)}:")
            for name in written:
                print(f"  {name}")
        else:
            for resource, count in import_assets(api):
                print(f"imported {resource}s (overwrite) from a bundle of {count} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
