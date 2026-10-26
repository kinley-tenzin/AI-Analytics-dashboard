"""Create a local .env from .env.example with freshly generated random passwords.

Usage (from the repository root):
    python infrastructure/scripts/create_local_env.py                # new .env
    python infrastructure/scripts/create_local_env.py --add-missing  # append new keys only

Never overwrites existing values. Passwords are written only to .env and are never printed.
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "CHANGE_ME"


def resolve(line: str, generated: list[str]) -> str:
    key, sep, value = line.partition("=")
    if sep and not line.lstrip().startswith("#") and value.strip() == PLACEHOLDER:
        generated.append(key)
        if key.strip().endswith("FERNET_KEY"):
            # Airflow needs a Fernet key: 32 random bytes, url-safe base64.
            return f"{key}={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}"
        if key.strip().endswith(("SECRET_KEY", "TOKEN_SECRET")):
            # Signing keys (Django, Superset, guest tokens): 64 characters (Django wants >= 50).
            return f"{key}={secrets.token_urlsafe(48)}"
        # URL-safe characters only, so values are safe in Compose files and connection strings.
        return f"{key}={secrets.token_urlsafe(24)}"
    return line


def main(argv: list[str]) -> int:
    example = REPO_ROOT / ".env.example"
    target = REPO_ROOT / ".env"
    generated: list[str] = []

    if "--add-missing" in argv:
        if not target.exists():
            print(f"{target} does not exist; run without --add-missing first.")
            return 1
        existing = {
            line.partition("=")[0].strip()
            for line in target.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        added = [
            resolve(line, generated)
            for line in example.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
            and line.partition("=")[0].strip() not in existing
        ]  # fmt: skip
        if added:
            with target.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n# Added from .env.example\n" + "\n".join(added) + "\n")
        print(f"Added {len(added)} setting(s): {', '.join(a.partition('=')[0] for a in added)}")
    else:
        if target.exists():
            print(f"{target} already exists; not overwriting. Use --add-missing for new keys.")
            return 1
        lines = [resolve(line, generated) for line in example.read_text("utf-8").splitlines()]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"Created {target}")

    if generated:
        print("Generated random values for: " + ", ".join(generated))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
