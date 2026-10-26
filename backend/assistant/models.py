from django.conf import settings
from django.db import models


class QuestionLog(models.Model):
    """Audit trail of assistant questions: who asked what, how it was interpreted, the outcome.

    Stores the KPI function and validated parameters, never the result values.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    asked_at = models.DateTimeField(auto_now_add=True)
    question = models.TextField()
    interpreter = models.CharField(max_length=80)
    status = models.CharField(max_length=30)
    function = models.CharField(max_length=80, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    phrasing = models.CharField(max_length=40, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-asked_at"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["asked_at"])]

    def __str__(self) -> str:
        return f"{self.asked_at:%Y-%m-%d %H:%M} {self.user} {self.status} {self.function}"
