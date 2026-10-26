from django.db import models


class PortalDashboard(models.Model):
    """A Superset dashboard shown in the website, and to which module (hr / accounts) it belongs.

    OFFICIAL dashboards are the governed templates created by superset/scripts/bootstrap.py.
    CUSTOM dashboards are made by Dashboard Creators in Superset's native editor and registered
    here by an administrator (Task 10.7). The module decides who may see it; the backend checks
    on every guest token that the dashboard only uses datasets of that module.
    """

    OFFICIAL = "official"
    CUSTOM = "custom"
    KINDS = [(OFFICIAL, "Official template"), (CUSTOM, "Customer dashboard")]
    DOMAINS = [("hr", "HR"), ("accounts", "Accounts")]

    key = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    domain = models.CharField(max_length=16, choices=DOMAINS)
    kind = models.CharField(max_length=16, choices=KINDS, default=CUSTOM)
    # Superset dashboard slug or numeric id.
    superset_ref = models.CharField(max_length=64, unique=True)
    visible = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "position", "title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.domain}, {self.kind})"
