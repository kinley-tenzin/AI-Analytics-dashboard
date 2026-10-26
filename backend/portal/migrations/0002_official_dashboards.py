"""Register the two OFFICIAL dashboards created by superset/scripts/bootstrap.py.

Keys and slugs must match superset/definitions/dashboards.py (tested in
tests/unit/test_platform_consistency.py). Existing rows are left unchanged (an administrator
may have hidden one).
"""

from django.db import migrations

OFFICIAL = [
    {
        "key": "hr",
        "title": "HR Overview",
        "description": "Headcount, departments, employment status and approved leave.",
        "domain": "hr",
        "superset_ref": "druksmart-hr",
        "position": 10,
    },
    {
        "key": "accounts",
        "title": "Accounts Overview",
        "description": "Receivables, payables, overdue balances and ageing.",
        "domain": "accounts",
        "superset_ref": "druksmart-accounts",
        "position": 10,
    },
]


def add_official(apps, schema_editor):
    PortalDashboard = apps.get_model("portal", "PortalDashboard")
    for spec in OFFICIAL:
        PortalDashboard.objects.get_or_create(
            key=spec["key"], defaults={**spec, "kind": "official", "visible": True}
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0001_portal_dashboard")]

    operations = [migrations.RunPython(add_official, migrations.RunPython.noop)]
