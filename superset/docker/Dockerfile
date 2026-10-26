# DrukSmart Superset image: the official release plus the PostgreSQL driver.
# The official image ships NO database drivers (checked in Milestone 6: `import psycopg2` fails),
# so the warehouse and metadata connections need psycopg2-binary. The pin is the version that
# Superset 6.1.0 itself declares for its `postgres` extra (pyproject.toml).
FROM apache/superset:6.1.0

USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache psycopg2-binary==2.9.9
USER superset
