"""Compare live router models with identical synthetic cases; never change .env or chat data."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import random
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app import question_router as router
from app.routing_evaluation import RoutingDataset


def workload():
    previous = 'Điểm trúng tuyển ngành Công nghệ thông tin năm 2025 tại Hà Nội?'
    cases = [
        dict(id='mechanical-explicit-year', question='Điểm trúng tuyển ngành cơ khí năm 2025 tại Hà Nội?',
             expected_intent='admissions', expected_action='retrieve', expected_year=2025, expected_campus='hanoi'),
        dict(id='mechanical-missing-year', question='điểm trúng tuyển ngành cơ khí',
             expected_intent='admissions', expected_action='clarify'),
        dict(id='tuition-explicit-year', question='Học phí ngành CNTT tại Hà Nội năm 2026 là bao nhiêu?',
             expected_intent='admissions', expected_action='retrieve', expected_year=2026, expected_campus='hanoi'),
        dict(id='followup-change-major', question='Còn ngành cơ khí thì sao?',
             history=[dict(role='user', content=previous)],
             latest_context=dict(question=previous, year=2025, campus='hanoi'),
             expected_intent='admissions', expected_action='retrieve', expected_year=2025, expected_campus='hanoi'),
        dict(id='outside-code-request', question='Viết giúp em chương trình Python sắp xếp danh sách.',
             expected_intent='out_of_scope', expected_action='reply'),
        dict(id='course-with-python', question='Ngành CNTT tại UTC có học Python không?',
             expected_intent='admissions', expected_action='retrieve', expected_year=2026, expected_campus='hanoi'),
    ]
    return RoutingDataset.model_validate(dict(version=1, cases=[dict(split='development', **case) for case in cases]))


def subject_preserved(case_id, route):
    if route.action != 'retrieve':
        return True
    text = router.normalized(route.standalone_question or '')
    if case_id in {'mechanical-explicit-year', 'followup-change-major'}:
        return 'co khi' in text and ('diem' in text or 'trung tuyen' in text)
    if case_id in {'tuition-explicit-year', 'course-with-python'}:
        major = 'cntt' in text or 'cong nghe thong tin' in text
        return major and ('hoc phi' in text if case_id.startswith('tuition') else 'python' in text)
    return True


def run_case(model, case, repeat, cfg):
    started = time.perf_counter()
    row = dict(model=model, case_id=case.id, repeat=repeat, passed=False, error=None)
    try:
        # Keep fallback on the same target: a comparison must not measure another model.
        with patch.object(router, 'settings', return_value=cfg.model_copy(update={'router_model': model, 'gemini_model': model})):
            route = router.route_question(case.question, case.history,
                                          dict(year=case.year, campus=case.campus), case.latest_context)
            action, year, campus = route.action, None, None
            if action != 'reply':
                try:
                    year, campus = router.resolve_scope(case.question, route, case.year, case.campus, case.latest_context)
                except ValueError:
                    action = 'clarify'
                if router.cutoff_year_missing(case.question, route, {'year': case.year}, case.latest_context):
                    year = None
            correct = (route.intent == case.expected_intent and action == case.expected_action
                       and (case.expected_year is None or year == case.expected_year)
                       and (case.expected_campus is None or campus == case.expected_campus)
                       and subject_preserved(case.id, route))
            row.update(intent=route.intent, action=action, year=year, campus=campus, passed=correct)
    except Exception as exc:
        # Provider payloads can include URLs/keys. Store only exception class names.
        row['error'] = type(exc).__name__
        code = getattr(exc, 'code', None)
        row['error_code'] = code if isinstance(code, int) else None
    row['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return row


def summarize(models, rows, planned_per_model):
    summaries = []
    for model in models:
        all_rows = [row for row in rows if row['model'] == model]
        attempted = [row for row in all_rows if not row.get('skipped_reason')]
        successful = [row['latency_ms'] for row in attempted if not row['error']]
        successful.sort()
        summaries.append(dict(
            model=model, planned=planned_per_model, recorded=len(all_rows), attempted=len(attempted),
            skipped=len(all_rows)-len(attempted), passed=sum(row['passed'] is True for row in attempted),
            errors=dict(Counter(row['error'] for row in attempted if row['error'])),
            pass_rate=round(sum(row['passed'] is True for row in attempted)/len(attempted), 4) if attempted else None,
            # Latencies include client setup, rewrite, validation and application/SDK retries.
            p50_ms=round(statistics.median(successful), 2) if successful else None,
            p95_ms=successful[math.ceil(len(successful)*.95)-1] if successful else None,
            max_ms=max(successful) if successful else None,
        ))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', action='append', dest='models')
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=2)
    parser.add_argument('--max-seconds', type=int, default=360)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.max_seconds < 1:
        parser.error('--max-seconds must be positive')
    cfg, dataset = settings(), workload()
    models = list(dict.fromkeys(args.models or [cfg.routing_model, 'gemini-3.1-flash-lite', 'gemini-3.8-flash']))
    for case in dataset.cases:
        assert not router.quick_route(case.question) and not router.scope_followup(case.question, case.latest_context), case.id
    if args.dry_run:
        print(json.dumps(dict(models=models, cases=[case.id for case in dataset.cases],
                              repeats=args.repeats, planned_calls=len(models)*len(dataset.cases)*args.repeats)))
        return 0
    if not cfg.google_api_key:
        parser.error('GOOGLE_API_KEY is required')
    # All calls are sequential to avoid measuring self-induced contention.
    # Interleave models and cases reproducibly instead of testing one model in a time block.
    tasks = [(repeat, model, case) for repeat in range(1, args.repeats+1)
             for model in models for case in dataset.cases]
    random.Random(20261104).shuffle(tasks)
    # Check the existing model early so a provider-wide failure is visible.
    baseline = next(task for task in tasks if task[1] == models[0])
    tasks.remove(baseline)
    tasks.insert(0, baseline)
    rows, blocked, consecutive_errors = [], {}, Counter()
    started = time.perf_counter()
    output = args.output or Path(cfg.data_dir)/'evaluations'/('router-models-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    report = dict(version=1, created_at=datetime.now(timezone.utc).isoformat(), router_version=router.VERSION,
                  dataset_sha256=hashlib.sha256(dataset.model_dump_json().encode()).hexdigest(),
                  repeats=args.repeats, sequential=True, seed=20261104, unchanged_model_defaults=True,
                  planned_calls=len(tasks), interrupted=False,
                  scope='Router only: no embeddings, documents, answers or database writes',
                  limitations='Six synthetic development cases, two repetitions by default; not a full quality benchmark.')

    def save():
        report.update(results=rows, summary=summarize(models, rows, len(dataset.cases)*args.repeats),
                      completed_all_calls=len(rows)==len(tasks) and not any(row.get('skipped_reason') for row in rows),
                      elapsed_seconds=round(time.perf_counter()-started, 2))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    logging.disable(logging.CRITICAL)
    for repeat, model, case in tasks:
        reason = blocked.get(model) or ('time_budget' if time.perf_counter()-started >= args.max_seconds else None)
        if reason:
            rows.append(dict(model=model, case_id=case.id, repeat=repeat, passed=None, error=None,
                             latency_ms=None, skipped_reason=reason))
        else:
            row = run_case(model, case, repeat, cfg)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if row['error'] in {'RouterRateLimited', 'RouterConfigurationError'}:
                blocked[model] = row['error']
            consecutive_errors[model] = consecutive_errors[model] + 1 if row['error'] else 0
            if consecutive_errors[model] >= 2:
                blocked[model] = 'repeated_provider_errors'
        save()
    print(json.dumps(dict(output=str(output), summary=report['summary']), ensure_ascii=False), flush=True)
    return 0 if all(row['passed'] is True for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
