"""The bounded question-answering workflow.

    question -> validate -> user scope (backend) -> interpreter proposal (rules or Gemini)
             -> KPI service: allowlist, domain + branch authorisation, parameter validation,
                parameterised query on approved datasets -> verified answer text

Every outcome has an explicit status:
    answered | clarification_needed | unsupported | forbidden | invalid_filter | no_data |
    invalid_request | error
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from access.scope import Scope, scope_for
from django.conf import settings
from django.core.cache import cache
from kpi.service import KpiError, KpiRequest, KpiResult, KpiService

from .compose import compose
from .gemini import GeminiClient, GeminiError, GeminiInterpreter, verify_numbers
from .interpretation import UNSUPPORTED_REASONS, Context, Interpretation
from .models import QuestionLog
from .rules import SUGGESTIONS, RulesInterpreter

log = logging.getLogger("druksmart.assistant")
CONTEXT_CACHE_SECONDS = 300


@dataclass
class Answer:
    status: str
    answer: str
    interpreter: str
    function: str | None = None
    parameters: dict = field(default_factory=dict)
    result: KpiResult | None = None
    options: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    phrasing: str = "template"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "interpreter": self.interpreter,
            "llm_used": self.interpreter.startswith("gemini"),
            "phrasing": self.phrasing,
            "function": self.function,
            "parameters": self.parameters,
            "result": self.result.to_dict() if self.result else None,
            "options": self.options,
            "details": self.details,
            "notes": self.notes,
        }


def _config() -> dict:
    return settings.DRUKSMART_AI


def build_interpreter() -> tuple[object, GeminiInterpreter | None]:
    """(interpreter, gemini) for the configured provider; rules when Gemini is not configured."""
    cfg = _config()
    if cfg["PROVIDER"] == "gemini" and cfg["GEMINI_API_KEY"]:
        client = GeminiClient(
            cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"], cfg["GEMINI_TIMEOUT_SECONDS"]
        )
        gemini = GeminiInterpreter(client)
        return gemini, gemini
    return RulesInterpreter(), None


def provider_status() -> dict:
    cfg = _config()
    if cfg["PROVIDER"] == "gemini" and cfg["GEMINI_API_KEY"]:
        return {"provider": "gemini", "model": cfg["GEMINI_MODEL"], "llm": True}
    note = (
        "DRUKSMART_AI_PROVIDER=gemini but GEMINI_API_KEY is empty"
        if cfg["PROVIDER"] == "gemini"
        else "deterministic rules (no language model)"
    )
    return {"provider": "rules", "model": None, "llm": False, "note": note}


class Assistant:
    def __init__(self, service: KpiService | None = None, interpreter=None, gemini=None):
        self.service = service or KpiService()
        if interpreter is None:
            interpreter, gemini = build_interpreter()
        self.interpreter = interpreter
        self.gemini = gemini
        self.rules = RulesInterpreter()

    def context(self) -> Context:
        cached = cache.get("assistant-context")
        if cached is None:
            cached = Context(self.service.labels(), self.service.latest_data_date())
            cache.set("assistant-context", cached, CONTEXT_CACHE_SECONDS)
        return cached

    def ask(self, question: str, user) -> Answer:
        started = time.monotonic()
        answer = self._ask(question, scope_for(user))
        try:
            QuestionLog.objects.create(
                user=user if getattr(user, "is_authenticated", False) else None,
                question=(question or "")[:2000],
                interpreter=answer.interpreter,
                status=answer.status,
                function=answer.function or "",
                parameters=answer.parameters,
                phrasing=answer.phrasing,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:  # logging must never break answering
            log.exception("could not write the question log")
        return answer

    def _ask(self, question: str, scope: Scope) -> Answer:
        question = (question or "").strip()
        limit = _config()["MAX_QUESTION_LENGTH"]
        if not question:
            return Answer("invalid_request", "Please type a question.", "none")
        if len(question) > limit:
            return Answer(
                "invalid_request", f"Questions are limited to {limit} characters.", "none"
            )
        if not scope.domains:
            return Answer(
                "forbidden",
                "Your account has no DrukSmart role yet. Ask an administrator for access.",
                "none",
            )
        try:
            context = self.context()
        except Exception:
            log.exception("warehouse unavailable while building the assistant context")
            return Answer(
                "error", "The warehouse is not reachable right now. Try again later.", "none"
            )

        notes: list[str] = []
        try:
            interp = self.interpreter.interpret(question, context)
        except GeminiError as exc:
            # Clearly labelled fallback: the answer below did NOT come from the language model.
            log.warning("Gemini unavailable (%s); using the deterministic rules", exc)
            notes.append(f"Gemini was unavailable ({exc}); the deterministic rules were used.")
            interp = self.rules.interpret(question, context)
            interp.interpreter = "rules (fallback)"
        notes.extend(interp.notes)

        if interp.kind == "clarify":
            return Answer(
                "clarification_needed",
                interp.message or "Could you be more specific?",
                interp.interpreter,
                options=interp.options,
                notes=notes,
            )
        if interp.kind == "unsupported":
            reason = interp.reason or "not_kpi"
            return Answer(
                "unsupported",
                UNSUPPORTED_REASONS.get(reason, UNSUPPORTED_REASONS["not_kpi"]),
                interp.interpreter,
                options=interp.options or SUGGESTIONS,
                details={"reason": reason},
                notes=notes,
            )
        return self._execute(question, interp, scope, notes)

    def _execute(self, question: str, interp: Interpretation, scope: Scope, notes) -> Answer:
        request_dict = interp.request_dict()
        try:
            request = KpiRequest.from_dict(request_dict)
            result = self.service.run(request, scope)
        except KpiError as exc:
            message = exc.message
            if exc.status == "forbidden" and "domain" in exc.details:
                message += f" Your access covers: {', '.join(sorted(scope.domains)).upper()}."
            return Answer(
                exc.status,
                message,
                interp.interpreter,
                function=interp.function,
                parameters=interp.parameters,
                details=exc.details,
                notes=notes,
            )
        except Exception:
            log.exception("KPI execution failed for %s", interp.function)
            return Answer(
                "error",
                "The warehouse is not reachable right now. Try again later.",
                interp.interpreter,
                function=interp.function,
                notes=notes,
            )

        text, phrasing = compose(result, interp.focus), "template"
        if self.gemini is not None and _config()["LLM_PHRASING"]:
            text, phrasing = self._llm_phrasing(question, result, text, notes)
        # Never let old or fictional data read like current ERP data.
        for flag, prefix in ((result.stale, "WARNING"), (result.synthetic, "SYNTHETIC")):
            if flag:
                text += " " + next(n for n in result.notes if n.startswith(prefix))
        return Answer(
            "answered",
            text,
            interp.interpreter,
            function=result.function,
            parameters=interp.parameters,
            result=result,
            notes=notes + result.notes,
            phrasing=phrasing,
        )

    def _llm_phrasing(self, question, result: KpiResult, template: str, notes) -> tuple[str, str]:
        payload = result.for_llm()
        try:
            text = self.gemini.phrase(question, payload)
        except GeminiError as exc:
            notes.append(f"LLM phrasing unavailable ({exc}); template answer shown.")
            return template, "template"
        unsupported = verify_numbers(text, payload)
        if unsupported:
            notes.append(
                "The LLM's wording contained numbers not in the data "
                f"({', '.join(unsupported[:5])}); the verified template answer is shown instead."
            )
            return template, "template (LLM text rejected)"
        return text, "llm (numbers verified)"
