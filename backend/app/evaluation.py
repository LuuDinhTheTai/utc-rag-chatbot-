"""Repeatable RAG evaluation against the application's current retrieval pipeline.

This module reads application data but never writes chat sessions or feedback.
The live mode calls Gemini for query embeddings and, unless retrieval_only is
set, answer generation. Reports intentionally omit API credentials and chunks.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings
from .localdb import Database
from .rag import NO_ANSWER, embeddings, filters, generate, match_chunks


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    question: str = Field(min_length=2, max_length=2000)
    year: int = Field(ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm']
    expect_supported: bool
    expected_source_urls: list[str] = Field(default_factory=list, max_length=20)
    expected_answer: str | None = Field(default=None, min_length=1, max_length=5000)
    required_answer_phrases: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def validate_expectations(self):
        if self.expect_supported and not self.expected_source_urls:
            raise ValueError('Supported cases need at least one expected source URL.')
        if not self.expect_supported and (self.expected_source_urls or self.required_answer_phrases or self.expected_answer):
            raise ValueError('Unsupported cases cannot require sources or answer phrases.')
        if any(not value or len(value) > 2000 for value in self.expected_source_urls):
            raise ValueError('Source URLs must contain 1-2000 characters.')
        if any(not value or len(value) > 500 for value in self.required_answer_phrases):
            raise ValueError('Required phrases must contain 1-500 characters.')
        if len(set(self.expected_source_urls)) != len(self.expected_source_urls):
            raise ValueError('Expected source URLs must be unique.')
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra='forbid')

    version: Literal[1]
    cases: list[EvaluationCase] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError('Evaluation case IDs must be unique.')
        return self


def load_dataset(path: Path) -> EvaluationDataset:
    return EvaluationDataset.model_validate_json(path.read_text(encoding='utf-8-sig'))


def dataset_hash(dataset: EvaluationDataset) -> str:
    canonical = json.dumps(dataset.model_dump(mode='json'), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def normalized(value: str) -> str:
    return ' '.join(value.casefold().split())


def evaluate_case(case: EvaluationCase, embedding_model, database: Database,
                  retrieval_only: bool) -> dict:
    """Run the same year/campus filter, embedding, threshold and top-k as /chat."""
    year, campus = filters(case.question, case.year, case.campus)
    matches = match_chunks(case.question, year, campus, database, embedding_model)

    expected = set(case.expected_source_urls)
    first_rank = next((index for index, row in enumerate(matches, 1)
                       if row['source_url'] in expected), None)
    retrieved = [
        {
            'document_id': row['document_id'],
            'source_url': row['source_url'],
            'title': row['title'],
            'similarity': round(row['similarity'], 4),
        }
        for row in matches
    ]
    result = {
        'id': case.id,
        'question': case.question,
        'filter_year': year,
        'filter_campus': campus,
        'expect_supported': case.expect_supported,
        'expected_source_urls': case.expected_source_urls,
        'expected_answer': case.expected_answer,
        'required_answer_phrases': case.required_answer_phrases,
        'retrieved': retrieved,
        'retrieval_hit': first_rank is not None if case.expect_supported else None,
        'reciprocal_rank': 1 / first_rank if first_rank else 0.0 if case.expect_supported else None,
        'error': None,
    }
    if retrieval_only:
        result['passed'] = result['retrieval_hit']
        return result

    answer, citations, supported = generate(case.question, matches) if matches else (NO_ANSWER, [], False)
    cited_urls = [source['source_url'] for source in citations]
    phrase_checks = {phrase: normalized(phrase) in normalized(answer)
                     for phrase in case.required_answer_phrases}
    citation_hit = bool(expected.intersection(cited_urls)) if case.expect_supported else None
    support_match = supported == case.expect_supported
    result.update({
        'answer': answer,
        'supported': supported,
        'support_match': support_match,
        'cited_source_urls': cited_urls,
        'citation_hit': citation_hit,
        'required_phrase_checks': phrase_checks,
        'passed': (
            support_match
            and (not case.expect_supported or (
                result['retrieval_hit'] and citation_hit and all(phrase_checks.values())
            ))
        ),
    })
    return result


def summarize(results: list[dict], retrieval_only: bool) -> dict:
    positive = [row for row in results if row['expect_supported']]
    evaluated = [row for row in results if row['passed'] is not None]
    answered = [row for row in results if 'support_match' in row]
    cited = [row for row in answered if row['expect_supported']]
    phrases = [row for row in results if row.get('required_answer_phrases')]
    ratio = lambda numerator, denominator: round(numerator / denominator, 4) if denominator else None
    return {
        'cases': len(results),
        'positive_cases': len(positive),
        'errors': sum(bool(row['error']) for row in results),
        'retrieval_hit_at_6': ratio(sum(row['retrieval_hit'] is True for row in positive), len(positive)),
        'mean_reciprocal_rank': ratio(sum(row['reciprocal_rank'] or 0 for row in positive), len(positive)),
        'support_accuracy': None if retrieval_only else ratio(
            sum(row['support_match'] for row in answered), len(results)),
        'citation_hit_rate': None if retrieval_only else ratio(
            sum(row['citation_hit'] is True for row in cited), len(positive)),
        'phrase_pass_rate': None if retrieval_only else ratio(
            sum(all(row.get('required_phrase_checks', {}).get(phrase, False)
                    for phrase in row['required_answer_phrases']) for row in phrases), len(phrases)),
        'pass_rate': ratio(sum(row['passed'] is True for row in evaluated), len(results))
                     if not retrieval_only else ratio(
                         sum(row['passed'] is True for row in evaluated), len(positive)),
    }


def evaluate(dataset: EvaluationDataset, *, retrieval_only: bool = False) -> dict:
    cfg = settings()
    if not cfg.google_api_key:
        raise ValueError('GOOGLE_API_KEY is required to embed evaluation questions.')
    model = embeddings()
    database = Database()
    results = []
    for case in dataset.cases:
        try:
            results.append(evaluate_case(case, model, database, retrieval_only))
        except Exception as exc:
            # Continue without storing provider error text, which may contain secrets.
            results.append({
                'id': case.id,
                'question': case.question,
                'expect_supported': case.expect_supported,
                'expected_answer': case.expected_answer,
                'required_answer_phrases': case.required_answer_phrases,
                'error': type(exc).__name__,
                'retrieval_hit': False if case.expect_supported else None,
                'reciprocal_rank': 0.0 if case.expect_supported else None,
                'passed': False,
            })
    return {
        'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'dataset_sha256': dataset_hash(dataset),
        'mode': 'retrieval' if retrieval_only else 'full',
        'config': {
            'gemini_model': cfg.gemini_model if not retrieval_only else None,
            'embedding_model': cfg.embedding_model,
            'similarity_threshold': cfg.similarity_threshold,
            'match_count': 6,
        },
        'summary': summarize(results, retrieval_only),
        'results': results,
    }


def compare_reports(report: dict, baseline: dict) -> dict:
    if report['dataset_sha256'] != baseline.get('dataset_sha256'):
        raise ValueError('Baseline uses a different evaluation dataset.')
    if report['mode'] != baseline.get('mode'):
        raise ValueError('Baseline uses a different evaluation mode.')
    if report['config']['embedding_model'] != baseline.get('config', {}).get('embedding_model'):
        raise ValueError('Baseline uses a different embedding model.')
    changes = {}
    for key, value in report['summary'].items():
        before = baseline.get('summary', {}).get(key)
        if isinstance(value, float) and isinstance(before, (float, int)):
            changes[key] = round(value - before, 4)
    return changes


def default_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    return Path(settings().data_dir).resolve() / 'evaluations' / f'run-{timestamp}.json'


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

