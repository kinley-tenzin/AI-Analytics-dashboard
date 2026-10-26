# DrukSmart Airflow image: official Airflow 3.3.2 (Python 3.12) + a SEPARATE virtual environment
# for the pipeline code and dbt (/opt/druksmart-venv), so pipeline and Airflow dependencies never
# conflict. Pipeline source code is NOT baked in: it is mounted read-only at /opt/druksmart.
#
# Packages are installed OFFLINE from orchestration/docker/wheels/ (pre-downloaded Linux wheels,
# see docs/orchestration/ORCHESTRATION.md), which keeps builds reproducible on slow networks.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN mkdir -p /opt/druksmart-venv && chown airflow: /opt/druksmart-venv
USER airflow

COPY orchestration/docker/requirements-pipeline.txt /tmp/requirements-pipeline.txt
COPY orchestration/docker/wheels/ /tmp/wheels/
RUN python -m venv /opt/druksmart-venv \
    && /opt/druksmart-venv/bin/pip install --no-cache-dir --no-index \
       --find-links /tmp/wheels -r /tmp/requirements-pipeline.txt \
    && /opt/druksmart-venv/bin/dbt --version

ENV DRUKSMART_PYTHON=/opt/druksmart-venv/bin/python \
    DRUKSMART_REPO=/opt/druksmart \
    PYTHONDONTWRITEBYTECODE=1 \
    DBT_TARGET_PATH=/tmp/dbt-target \
    DBT_LOG_PATH=/tmp/dbt-logs \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false
