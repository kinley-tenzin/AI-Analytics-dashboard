"""Run the assistant evaluation set and write a report.

    python backend/manage.py evaluate_assistant                       # configured provider
    python backend/manage.py evaluate_assistant --provider rules
    python backend/manage.py evaluate_assistant --provider gemini     # needs GEMINI_API_KEY

Each question is asked through the REAL pipeline (interpreter -> scope -> KPI service -> warehouse)
as the given demo user. Answers are compared with evaluation/questions.yml and with independent
reference values from the fact tables (evaluation/references.py, pipeline role).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from assistant.gemini import GeminiClient, GeminiInterpreter
from assistant.pipeline import Assistant
from assistant.rules import RulesInterpreter
from druksmart_common.config import load_settings
from druksmart_common.db import connect

TOLERANCE = 0.005


def _subset(expected: dict, actual: dict) -> bool:
    for key, value in expected.items():
        if isinstance(value, dict):
            if not isinstance(actual.get(key), dict) or not _subset(value, actual[key]):
                return False
        elif str(actual.get(key, "")).lower() != str(value).lower():
            return False
    return True


def _close(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= TOLERANCE


def _compare(reference: dict, result: dict | None) -> tuple[bool, str]:
    if not result:
        return False, "no result"
    measure = reference["measure"]
    rows = result["rows"]
    if "by" in reference:
        got = {"|".join(str(r[d]) for d in reference["by"]): r.get(measure) for r in rows}
        want = reference["values"]
        ok = set(got) == set(want) and all(_close(got[k], want[k]) for k in want)
        return ok, "" if ok else f"expected {want}, got {got}"
    got = sum(float(r.get(measure) or 0) for r in rows)
    ok = _close(got, reference["value"])
    for extra, value in reference.get("also", {}).items():
        ok = ok and _close(sum(float(r.get(extra) or 0) for r in rows), value)
    return ok, "" if ok else f"expected {reference['value']}, got {got}"


class Command(BaseCommand):
    help = "Evaluate the AI assistant against the evaluation question set."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider", choices=["configured", "rules", "gemini"], default="configured"
        )
        parser.add_argument("--questions", default=None)
        parser.add_argument("--output", default=None, help="write results JSON here")

    def handle(self, *args, provider, questions, output, **options):
        backend_dir = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(backend_dir))
        from evaluation.references import REFERENCES

        cases = yaml.safe_load(
            Path(questions or backend_dir / "evaluation" / "questions.yml").read_text("utf-8")
        )["cases"]
        cfg = settings.DRUKSMART_AI
        if provider == "rules":
            assistant = Assistant(interpreter=RulesInterpreter(), gemini=None)
        elif provider == "gemini":
            if not cfg["GEMINI_API_KEY"]:
                raise CommandError("GEMINI_API_KEY is not set in .env")
            gemini = GeminiInterpreter(
                GeminiClient(
                    cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"], cfg["GEMINI_TIMEOUT_SECONDS"]
                )
            )
            assistant = Assistant(interpreter=gemini, gemini=gemini)
        else:
            assistant = Assistant()
        users = {u.username: u for u in User.objects.filter(username__startswith="demo_")}
        missing = {c["user"] for c in cases} - set(users)
        if missing:
            raise CommandError(f"demo users missing ({sorted(missing)}): run seed_demo_users")

        results = []
        with connect(load_settings().pipeline(), autocommit=True) as facts:
            for case in cases:
                exp = case["expect"]
                answer = assistant.ask(case["question"], users[case["user"]]).to_dict()
                status_ok = answer["status"] == exp["status"]
                function_ok = "function" not in exp or answer["function"] == exp["function"]
                params_ok = "parameters" not in exp or _subset(
                    exp["parameters"], answer["parameters"]
                )
                intent_ok = status_ok and function_ok and params_ok
                value_ok, value_note = None, ""
                if exp.get("reference") and answer["status"] == "answered":
                    value_ok, value_note = _compare(
                        REFERENCES[exp["reference"]](facts), answer["result"]
                    )
                elif exp.get("reference"):
                    value_ok, value_note = False, "not answered"
                violation = exp["status"] == "forbidden" and answer["status"] == "answered"
                results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "user": case["user"],
                        "question": case["question"],
                        "expected_status": exp["status"],
                        "status": answer["status"],
                        "expected_function": exp.get("function"),
                        "function": answer["function"],
                        "parameters": answer["parameters"],
                        "intent_ok": intent_ok,
                        "value_ok": value_ok,
                        "value_note": value_note,
                        "permission_violation": violation,
                        "interpreter": answer["interpreter"],
                        "phrasing": answer["phrasing"],
                        "answer": answer["answer"],
                    }
                )
                mark = "PASS" if intent_ok and value_ok is not False else "FAIL"
                self.stdout.write(
                    f"[{mark}] {case['id']:<4} {answer['status']:<21} {case['question']}"
                )

        summary = self._summary(results)
        report = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "interpreter": results[0]["interpreter"] if results else None,
            "summary": summary,
            "results": results,
        }
        if output:
            Path(output).write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        self.stdout.write(json.dumps(summary, indent=2))

    @staticmethod
    def _summary(results: list[dict]) -> dict:
        by_cat: dict[str, Counter] = defaultdict(Counter)
        for r in results:
            by_cat[r["category"]]["total"] += 1
            by_cat[r["category"]]["intent_ok"] += r["intent_ok"]
        valued = [r for r in results if r["value_ok"] is not None]
        refusals = [
            r for r in results if r["expected_status"] in ("unsupported", "clarification_needed")
        ]
        return {
            "questions": len(results),
            "intent_accuracy": f"{sum(r['intent_ok'] for r in results)}/{len(results)}",
            "numeric_accuracy": f"{sum(bool(r['value_ok']) for r in valued)}/{len(valued)}",
            "unsupported_or_ambiguous_handled": (
                f"{sum(r['status'] == r['expected_status'] for r in refusals)}/{len(refusals)}"
            ),
            "permission_violations": sum(r["permission_violation"] for r in results),
            "by_category": {c: f"{n['intent_ok']}/{n['total']}" for c, n in by_cat.items()},
        }
