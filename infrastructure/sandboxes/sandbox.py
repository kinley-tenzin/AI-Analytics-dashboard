"""Manage the LOCAL Odoo / ERPNext sandboxes (synthetic data only).

    python infrastructure/sandboxes/sandbox.py up odoo     # start (initialises once)
    python infrastructure/sandboxes/sandbox.py seed odoo   # data + read-only user + key -> .env
    python infrastructure/sandboxes/sandbox.py status
    python infrastructure/sandboxes/sandbox.py stop odoo   # stop, keep data
    python infrastructure/sandboxes/sandbox.py destroy odoo --yes   # DELETE containers + volumes

Every compose call uses an explicit project name (-p), so a sandbox can never join or
remove the platform's own `druksmart` project. Secrets go to .env and are never printed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
SANDBOXES = {
    "odoo": ("druksmart-odoo-sandbox", REPO_ROOT / "infrastructure/sandboxes/odoo/compose.yaml"),
    "erpnext": (
        "druksmart-erpnext-sandbox",
        REPO_ROOT / "infrastructure/sandboxes/erpnext/compose.yaml",
    ),
}
ODOO_DB = "druksmart_sandbox"


def compose(name: str, *args: str, capture: bool = False, stdin: bytes | None = None):
    project, file = SANDBOXES[name]
    env = {k: v for k, v in os.environ.items() if k != "COMPOSE_PROJECT_NAME"}
    cmd = ["docker", "compose", "-p", project, "--env-file", str(ENV_FILE), "-f", str(file), *args]
    return subprocess.run(cmd, env=env, input=stdin, capture_output=capture, check=False)


def set_env_value(key: str, value: str) -> None:
    """Replace KEY=... in .env (append if absent) without echoing the value."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def odoo_initialised() -> bool:
    result = compose(
        "odoo",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "odoo",
        "-d",
        "postgres",
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname = '{ODOO_DB}'",
        capture=True,
    )
    return result.stdout.strip() == b"1"


def up(name: str) -> int:
    if name == "odoo":
        if compose("odoo", "up", "-d", "--wait", "db").returncode:
            return 1
        if not odoo_initialised():
            print("Initialising Odoo database (HR, Time Off, Invoicing; no demo data)...")
            init = compose(
                "odoo",
                "run",
                "--rm",
                "--no-deps",
                "odoo",
                "odoo",
                "-d",
                ODOO_DB,
                "-i",
                "hr,hr_holidays,account",
                "--stop-after-init",
                "--without-demo=all",
            )
            if init.returncode:
                return 1
    return compose(name, "up", "-d").returncode


def seed(name: str) -> int:
    if name != "odoo":
        script = REPO_ROOT / "infrastructure/sandboxes/erpnext/seed/seed_erpnext.py"
        return subprocess.run([sys.executable, str(script)], check=False).returncode
    admin_password = dotenv_values(ENV_FILE).get("ODOO_SANDBOX_ADMIN_PASSWORD") or ""
    if not admin_password:
        print("ODOO_SANDBOX_ADMIN_PASSWORD missing in .env (run create_local_env.py --add-missing)")
        return 2
    # The password is prepended to the script on stdin: never on a command line or in output.
    script = (
        f"ADMIN_PASSWORD = {admin_password!r}\n".encode()
        + (REPO_ROOT / "infrastructure/sandboxes/odoo/seed/seed_odoo.py").read_bytes()
    )
    # `exec` bypasses the image entrypoint, so pass the DB connection from the container env.
    shell = (
        f'odoo shell -d {ODOO_DB} --db_host "$HOST" --db_user "$USER" '
        '--db_password "$PASSWORD" --no-http --log-level=warn'
    )
    run = compose("odoo", "exec", "-T", "odoo", "bash", "-c", shell, stdin=script, capture=True)
    output = run.stdout.decode(errors="replace")
    if "SEED COMPLETE" not in output:
        errors = output + run.stderr.decode(errors="replace")
        lines = errors.splitlines()
        # Show where in the seed script it failed, then the final error message.
        for i, line in enumerate(lines):
            if 'File "<' in line:  # frames from the piped script (<stdin>/<string>/<console>)
                print(line.strip(), "|", lines[i + 1].strip() if i + 1 < len(lines) else "")
        print("\n".join(lines[-3:]))
        return 1
    print(output[-2000:])
    key = compose(
        "odoo", "exec", "-T", "odoo", "cat", "/var/lib/odoo/.druksmart_bot_key", capture=True
    )
    if key.returncode or not key.stdout.strip():
        print("could not read the generated API key")
        return 1
    set_env_value("ODOO_API_KEY", key.stdout.decode().strip())
    compose("odoo", "exec", "-T", "odoo", "rm", "-f", "/var/lib/odoo/.druksmart_bot_key")
    print("ODOO_API_KEY written to .env (not displayed).")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"up", "seed", "status", "stop", "destroy"}:
        print(__doc__)
        return 2
    action, names = argv[0], [a for a in argv[1:] if a in SANDBOXES] or list(SANDBOXES)
    for name in names:
        if action == "up":
            code = up(name)
        elif action == "seed":
            code = seed(name)
        elif action == "status":
            code = compose(name, "ps").returncode
        elif action == "stop":
            code = compose(name, "stop").returncode
        else:
            if "--yes" not in argv:
                print(f"destroy deletes ALL {name} sandbox data; re-run with --yes to confirm")
                return 2
            code = compose(name, "down", "-v").returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
