"""Run dbt with this project's settings and credentials from the repository .env file.

    python warehouse/run_dbt.py build                 # dev database
    python warehouse/run_dbt.py build --target test   # isolated test database
    python warehouse/run_dbt.py docs generate

Any dbt arguments are passed through; --project-dir and --profiles-dir are added automatically.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

WAREHOUSE = Path(__file__).resolve().parent


def run(args: list[str]) -> int:
    load_dotenv(WAREHOUSE.parent / ".env", override=False)
    os.environ.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    from dbt.cli.main import dbtRunner

    extra = []
    if "--project-dir" not in args:
        extra += ["--project-dir", str(WAREHOUSE)]
    if "--profiles-dir" not in args:
        extra += ["--profiles-dir", str(WAREHOUSE / "profiles")]
    result = dbtRunner().invoke(args + extra)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
