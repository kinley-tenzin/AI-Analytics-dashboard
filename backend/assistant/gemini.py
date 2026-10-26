"""Google Gemini as a CONSTRAINED interpreter and phraser (function calling, REST API via httpx).

What Gemini receives:
  * the user's question text and the reference (latest data) date;
  * the registry's public function descriptions, with allowed group-by and filter values
    (organisational labels such as department names; no KPI values, no people);
  * for phrasing only: the AGGREGATED result of the executed KPI function (KpiResult.for_llm).
What Gemini never receives: SQL, table names, raw/ERP records, employee keys or names, the user's
roles or scope, credentials. It cannot execute anything: it must call exactly one of the declared
tools (mode ANY), and the backend then validates, authorises and runs the proposal itself.
Its phrased answer is accepted only if every number in it appears in the result (verify_numbers).
"""

from __future__ import annotations

import json
import re

import httpx
from kpi import registry
from kpi.registry import DIMENSIONS

from .interpretation import UNSUPPORTED_REASONS, Context, Interpretation

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CLARIFY = "request_clarification"
DECLINE = "decline"

SYSTEM_INSTRUCTION = """You route questions about a company's HR and Accounts KPIs to tools.
Rules:
- Always call exactly ONE tool. Never answer in text.
- Use a KPI tool only when the question asks for that KPI; copy filter values exactly from the
  allowed lists; omit parameters the user did not ask for (defaults are applied by the system).
- Dates are YYYY-MM-DD. The latest available data date is {reference_date}; interpret "this
  month", "last month", "yesterday" relative to it.
- If the question is ambiguous (e.g. "outstanding balance" without saying receivables or
  payables), call request_clarification with 2-4 concrete rephrasings.
- Call decline for: individual people/customers/suppliers or their names; salaries, pay, bank,
  identity or contact details; requests to change data; SQL; forecasts; other business areas
  (sales revenue, inventory, payroll, budgets); or anything that is not a KPI question.
- Do not judge whether the user is allowed to see a KPI; the system checks permissions."""

PHRASE_INSTRUCTION = """Write a short, clear business answer (1-3 sentences) to the user's question
using ONLY the JSON result provided. Rules: use only numbers that appear in the JSON (you may add
thousands separators); never compute new totals, percentages or differences; state the as-of date
or period and the currency for amounts; mention applied filters; do not add advice or
speculation; plain text, no markdown tables."""


class GeminiError(RuntimeError):
    pass


def tool_name(function: str) -> str:
    return function.replace(".", "_")


def _function_declaration(f, context: Context) -> dict:
    props: dict = {}
    if f.time == "snapshot":
        props["as_of"] = {
            "type": "STRING",
            "description": "Snapshot date YYYY-MM-DD. Omit for the latest available date.",
        }
    else:
        props["period_start"] = {"type": "STRING", "description": "First day YYYY-MM-DD."}
        props["period_end"] = {"type": "STRING", "description": "Last day YYYY-MM-DD."}
    if f.group_by:
        props["group_by"] = {
            "type": "STRING",
            "enum": list(f.group_by),
            "description": "Split the result by this dimension (only if asked).",
        }
    for dim in f.filters:
        d = DIMENSIONS[dim]
        values = list(d.choices) or list(context.labels.get(dim, []))
        spec = {"type": "STRING", "description": f"Filter: exact {d.label.lower()} name."}
        if values:
            spec["enum"] = values
        props[dim] = spec
    if len(f.measures) > 1:
        props["focus"] = {
            "type": "STRING",
            "enum": [m.name for m in f.measures],
            "description": "Which measure the question is mainly about.",
        }
    return {
        "name": tool_name(f.name),
        "description": f"{f.title}. {f.description}",
        "parameters": {"type": "OBJECT", "properties": props},
    }


def tool_declarations(context: Context) -> list[dict]:
    declarations = [_function_declaration(f, context) for f in registry.FUNCTIONS.values()]
    declarations.append(
        {
            "name": CLARIFY,
            "description": "Ask the user to clarify an ambiguous KPI question.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "message": {"type": "STRING"},
                    "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["message", "options"],
            },
        }
    )
    declarations.append(
        {
            "name": DECLINE,
            "description": "Decline a question the KPI assistant must not or cannot answer.",
            "parameters": {
                "type": "OBJECT",
                "properties": {"reason": {"type": "STRING", "enum": list(UNSUPPORTED_REASONS)}},
                "required": ["reason"],
            },
        }
    )
    return declarations


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: float = 20, transport=None):
        if not api_key:
            raise GeminiError("GEMINI_API_KEY is not configured")
        self.model = model
        self._http = httpx.Client(
            base_url=API_BASE,
            timeout=timeout,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            transport=transport,
        )

    def generate(self, payload: dict) -> dict:
        try:
            resp = self._http.post(f"/models/{self.model}:generateContent", json=payload)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Gemini request failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            raise GeminiError(f"Gemini HTTP {resp.status_code}: {detail[:200]}")
        return resp.json()

    @staticmethod
    def parts(response: dict) -> list[dict]:
        candidates = response.get("candidates") or []
        if not candidates:
            reason = (response.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise GeminiError(f"Gemini returned no answer ({reason})")
        return (candidates[0].get("content") or {}).get("parts") or []


class GeminiInterpreter:
    def __init__(self, client: GeminiClient):
        self.client = client
        self.name = f"gemini:{client.model}"

    def interpret(self, question: str, context: Context) -> Interpretation:
        reference = context.reference_date.isoformat() if context.reference_date else "unknown"
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_INSTRUCTION.format(reference_date=reference)}]
            },
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "tools": [{"functionDeclarations": tool_declarations(context)}],
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
            "generationConfig": {"temperature": 0},
        }
        parts = GeminiClient.parts(self.client.generate(payload))
        call = next((p["functionCall"] for p in parts if "functionCall" in p), None)
        if call is None:
            raise GeminiError("Gemini did not call a tool")
        return self._to_interpretation(call.get("name", ""), call.get("args") or {})

    def _to_interpretation(self, name: str, args: dict) -> Interpretation:
        if name == CLARIFY:
            options = [str(o) for o in args.get("options") or []][:4]
            return Interpretation(
                "clarify", self.name, message=str(args.get("message", ""))[:300], options=options
            )
        if name == DECLINE:
            reason = args.get("reason")
            reason = reason if reason in UNSUPPORTED_REASONS else "not_kpi"
            return Interpretation("unsupported", self.name, reason=reason)
        f = next((f for f in registry.FUNCTIONS.values() if tool_name(f.name) == name), None)
        if f is None:
            return Interpretation(
                "unsupported", self.name, reason="not_kpi", notes=[f"model proposed {name!r}"]
            )
        params: dict = {}
        for key in ("as_of", "period_start", "period_end", "group_by"):
            if isinstance(args.get(key), str) and args[key].strip():
                params[key] = args[key].strip()
        filters = {d: str(args[d]) for d in f.filters if isinstance(args.get(d), (str, int))}
        if filters:
            params["filters"] = filters
        focus = args.get("focus") if args.get("focus") in [m.name for m in f.measures] else None
        return Interpretation("kpi", self.name, f.name, params, focus=focus)

    def phrase(self, question: str, result_for_llm: dict) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": PHRASE_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"Question: {question}\n\nResult JSON:\n"
                            + json.dumps(result_for_llm, ensure_ascii=False)
                        }
                    ],
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 300},
        }
        parts = GeminiClient.parts(self.client.generate(payload))
        text = " ".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise GeminiError("Gemini returned an empty phrasing")
        return text


# "166,700.00", "166700", "2" (thousands separators only in groups of three; no trailing comma)
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _normalise(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def verify_numbers(text: str, result_for_llm: dict) -> list[str]:
    """Numbers in `text` that do NOT occur in the result (empty list = all supported)."""
    allowed = {_normalise(t) for t in NUMBER.findall(json.dumps(result_for_llm))}
    return [t for t in NUMBER.findall(text) if _normalise(t) not in allowed]
