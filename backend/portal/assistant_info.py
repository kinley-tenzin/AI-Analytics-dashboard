"""What the Ask AI page needs to know before the first question (Task 10.6).

Suggested questions are the registry's own examples for the caller's modules, so every
suggestion is answerable by an approved KPI function the user may run. The provider tells the
page honestly whether a language model or the deterministic rules interpreter answers.
"""

from __future__ import annotations

from access.scope import scope_for
from assistant.pipeline import _config, provider_status
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from kpi import registry
from kpi.http import api_login_required


@require_GET
@api_login_required
def assistant_info(request):
    scope = scope_for(request.user)
    suggestions = [
        {"domain": f.domain, "kpi": f.title, "question": example}
        for f in registry.functions_for(scope.domains)
        for example in f.examples
    ]
    return JsonResponse(
        {
            "status": "ok",
            "provider": provider_status(),
            "max_question_length": _config()["MAX_QUESTION_LENGTH"],
            "suggestions": suggestions,
        }
    )
