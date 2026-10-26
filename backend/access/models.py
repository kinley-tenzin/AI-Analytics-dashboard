from django.conf import settings
from django.db import models


class BranchScope(models.Model):
    """Restricts a Branch Manager to the listed warehouse branches (marts.dim_branch.branch_key).

    The backend's counterpart of Superset's row-level security rule: every KPI query of a user
    with the Branch Manager role is limited to these keys, whatever filters the user asks for.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="branch_scopes"
    )
    branch_key = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "branch_key"], name="unique_user_branch")
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.branch_key}"


class LoginFailure(models.Model):
    """One failed sign-in attempt, used to throttle password guessing (access/throttle.py).

    Stored in the database (not a per-process cache) so every gunicorn worker sees the same
    count. No password or other credential is stored; rows older than the window are pruned.
    """

    username = models.CharField(max_length=150, db_index=True)  # normalised (lower case)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self) -> str:
        return f"{self.username} at {self.created_at:%Y-%m-%d %H:%M:%S}"
