"""SANDBOX ONLY. Run the Odoo loader inside the local Odoo sandbox.

    python infrastructure/sandboxes/scale/load_odoo_run.py --phases partners,employees,leaves,moves,payments
    python infrastructure/sandboxes/scale/load_odoo_run.py --phases moves --batch 50

The plan (plan.py) is copied into the container; the loader (load_odoo.py) is piped into
`odoo shell`, exactly like the sandbox seed. Nothing is sent anywhere else.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "infrastructure" / "sandboxes"))
from sandbox import ODOO_DB, compose  # noqa: E402

PLAN = REPO / "tests" / "fixtures" / "synthetic_medium" / "erp_plan" / "odoo.json"
ALL = "partners,employees,leaves,moves,payments"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phases", default=ALL)
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    if not PLAN.exists():
        raise SystemExit("build the plan first: python infrastructure/sandboxes/scale/plan.py")
    container = compose("odoo", "ps", "-q", "odoo", capture=True).stdout.decode().strip()
    if not container:
        raise SystemExit("the Odoo sandbox is not running: python infrastructure/sandboxes/sandbox.py up odoo")
    subprocess.run(["docker", "cp", str(PLAN), f"{container}:/tmp/scale_plan.json"], check=True)
    script = (f"PHASES = {args.phases.split(',')!r}\nBATCH = {args.batch}\n").encode() + (
        REPO / "infrastructure/sandboxes/scale/load_odoo.py"
    ).read_bytes()
    shell = (
        f'odoo shell -d {ODOO_DB} --db_host "$HOST" --db_user "$USER" '
        '--db_password "$PASSWORD" --no-http --log-level=warn'
    )
    run = compose("odoo", "exec", "-T", "odoo", "bash", "-c", shell, stdin=script, capture=True)
    out = run.stdout.decode(errors="replace")
    print(out[-6000:])
    if "LOAD COMPLETE" not in out:
        print((run.stderr.decode(errors="replace"))[-3000:])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
