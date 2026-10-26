"""The assistant's question API, used by the website's Ask AI page (frontend AskAiPage.tsx)."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from kpi.http import api_login_required, error, json_body

from .pipeline import Assistant


@require_POST
@api_login_required
def ask(request):
    try:
        question = json_body(request).get("question", "")
    except ValueError as exc:
        return error(400, "invalid_request", str(exc))
    if not isinstance(question, str):
        return error(400, "invalid_request", "question must be text")
    return JsonResponse(Assistant().ask(question, request.user).to_dict())
