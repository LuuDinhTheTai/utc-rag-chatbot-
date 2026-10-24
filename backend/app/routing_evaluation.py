"""Evaluate routing without embeddings, chat writes or admission answer generation."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings
from .question_router import VERSION, RouterRateLimited, quick_route, resolve_scope, route_question


class RoutingCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    split: Literal['development', 'acceptance']
    question: str = Field(min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=8)
    latest_context: dict | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm'] | None = None
    expected_intent: Literal['greeting', 'social', 'capabilities', 'admissions', 'out_of_scope', 'unclear']
    expected_action: Literal['reply', 'retrieve', 'clarify']
    expected_year: int | None = None
    expected_campus: Literal['hanoi', 'hcm'] | None = None


class RoutingDataset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    cases: list[RoutingCase] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError('Duplicate case IDs')
        return self


def load_dataset(path: Path):
    return RoutingDataset.model_validate_json(path.read_text(encoding='utf-8-sig'))


def evaluate(dataset, *, live=False, split=None):
    rows = []
    quota_exhausted = False
    for case in dataset.cases:
        if split and case.split != split:
            continue
        started = time.monotonic()
        row = {'id': case.id, 'expected_intent': case.expected_intent, 'expected_action': case.expected_action,
               'intent': None, 'action': None, 'passed': None, 'error': None, 'scope_passed': None}
        if quota_exhausted:
            row.update(skipped_reason='provider_rate_limit', latency_ms=0)
            rows.append(row)
            continue
        try:
            route = route_question(case.question, case.history, {'year': case.year, 'campus': case.campus}, case.latest_context) if live else quick_route(case.question)
            if route is not None:
                action = route.action
                year = campus = None
                if action != 'reply':
                    try:
                        year, campus = resolve_scope(case.question, route, case.year, case.campus, case.latest_context)
                    except ValueError:
                        action = 'clarify'
                scope_ok = ((case.expected_year is None or year == case.expected_year)
                            and (case.expected_campus is None or campus == case.expected_campus))
                row.update(intent=route.intent, action=action, year=year, campus=campus,
                           scope_passed=scope_ok if case.expected_year is not None or case.expected_campus else None,
                           passed=route.intent == case.expected_intent and action == case.expected_action and scope_ok)
        except RouterRateLimited as exc:
            row.update(error=type(exc).__name__, passed=False)
            quota_exhausted = True
        except Exception as exc:
            row.update(error=type(exc).__name__, passed=False)
        row['latency_ms'] = round((time.monotonic() - started) * 1000)
        rows.append(row)
    evaluated = [r for r in rows if r['passed'] is not None]
    matrix = Counter((r['expected_intent'], r['intent'] or 'error') for r in evaluated)
    labels = sorted({r['expected_intent'] for r in evaluated})
    scores = []
    for label in labels:
        tp = matrix[label, label]
        fp = sum(n for (actual, predicted), n in matrix.items() if predicted == label and actual != label)
        fn = sum(n for (actual, predicted), n in matrix.items() if actual == label and predicted != label)
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    admissions = [r for r in evaluated if r['expected_intent'] == 'admissions']
    scope = [r for r in evaluated if r['scope_passed'] is not None]
    latencies = sorted(r['latency_ms'] for r in evaluated)
    ratio = lambda n, d: round(n / d, 4) if d else None
    return {
        'version': 1, 'router_version': VERSION, 'mode': 'live' if live else 'rules_only',
        'complete': live and len(evaluated) == len(rows) and not any(r['error'] for r in rows),
        'model': settings().gemini_model if live else None,
        'dataset_sha256': hashlib.sha256(dataset.model_dump_json().encode()).hexdigest(),
        'summary': {'cases': len(rows), 'evaluated': len(evaluated), 'skipped': len(rows) - len(evaluated),
                    'errors': sum(bool(r['error']) for r in rows),
                    'pass_rate': ratio(sum(r['passed'] is True for r in evaluated), len(evaluated)),
                    'macro_f1': ratio(sum(scores), len(scores)),
                    'admissions_recall': ratio(sum(r['intent'] == 'admissions' for r in admissions), len(admissions)),
                    'scope_accuracy': ratio(sum(r['scope_passed'] for r in scope), len(scope)),
                    'p50_ms': latencies[max(0, math.ceil(len(latencies) * .5) - 1)] if latencies else None,
                    'p95_ms': latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None},
        'confusion': [{'expected': a, 'predicted': p, 'count': n} for (a, p), n in sorted(matrix.items())],
        'results': rows,
    }
