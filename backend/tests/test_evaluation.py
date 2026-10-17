import json

import pytest
from pydantic import ValidationError

from app import evaluation
from app.config import settings
from app.localdb import Database


SOURCE_A = 'https://tuyensinh.utc.edu.vn/source-a'
SOURCE_B = 'https://tuyensinh.utc.edu.vn/source-b'


@pytest.fixture
def rag_store(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-only-key')
    settings.cache_clear()
    database = Database()
    for url, vector in ((SOURCE_A, [1.0, 0.0]), (SOURCE_B, [0.0, 1.0])):
        document = database.table('documents').insert({
            'title': url.rsplit('/', 1)[-1], 'source_url': url,
            'admission_year': 2026, 'campus': 'hanoi', 'category': 'tuyen-sinh',
            'checksum': url, 'raw_text': 'Admission details for 2026',
            'status': 'ready', 'chunk_count': 1,
        }).execute().data[0]
        database.table('document_chunks').insert({
            'document_id': document['id'], 'chunk_index': 0,
            'content': 'Admission details for 2026', 'embedding': vector,
        }).execute()
    yield tmp_path
    settings.cache_clear()


def dataset():
    return evaluation.EvaluationDataset.model_validate({
        'version': 1,
        'cases': [
            {'id': 'hit', 'question': 'good question', 'year': 2026,
             'campus': 'hanoi', 'expect_supported': True,
             'expected_source_urls': [SOURCE_A],
             'expected_answer': 'Admissions answer for 2026.',
             'required_answer_phrases': ['2026']},
            {'id': 'miss', 'question': 'good but wrong source', 'year': 2026,
             'campus': 'hanoi', 'expect_supported': True,
             'expected_source_urls': [SOURCE_B],
             'required_answer_phrases': ['2026']},
            {'id': 'refusal', 'question': 'unknown question', 'year': 2026,
             'campus': 'hanoi', 'expect_supported': False},
        ],
    })


def test_evaluation_reports_retrieval_and_answer_quality(rag_store, monkeypatch):
    class FakeEmbeddings:
        def embed_query(self, question):
            return [0.0, 0.0] if 'unknown' in question else [1.0, 0.0]

    monkeypatch.setattr(evaluation, 'embeddings', lambda: FakeEmbeddings())
    monkeypatch.setattr(evaluation, 'generate',
                        lambda question, matches: ('Admissions 2026 [1]', [matches[0]], True))
    report = evaluation.evaluate(dataset())
    summary = report['summary']
    assert summary['cases'] == 3
    assert summary['retrieval_hit_at_6'] == 0.5
    assert summary['mean_reciprocal_rank'] == 0.5
    assert summary['support_accuracy'] == 1.0
    assert summary['citation_hit_rate'] == 0.5
    assert summary['phrase_pass_rate'] == 1.0
    assert summary['pass_rate'] == 0.6667
    assert [row['passed'] for row in report['results']] == [True, False, True]
    assert report['results'][0]['retrieved'][0]['source_url'] == SOURCE_A
    assert report['results'][0]['expected_answer'] == 'Admissions answer for 2026.'
    assert 'content' not in report['results'][0]['retrieved'][0]
    assert 'test-only-key' not in json.dumps(report)

    path = rag_store / 'reports' / 'run.json'
    evaluation.write_report(report, path)
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['summary'] == summary
    assert evaluation.compare_reports(report, saved)['pass_rate'] == 0


def test_retrieval_only_skips_generation(rag_store, monkeypatch):
    class FakeEmbeddings:
        def embed_query(self, question):
            return [0.0, 0.0] if 'unknown' in question else [1.0, 0.0]

    monkeypatch.setattr(evaluation, 'embeddings', lambda: FakeEmbeddings())
    monkeypatch.setattr(evaluation, 'generate',
                        lambda *_: pytest.fail('Answer generation must not run.'))
    report = evaluation.evaluate(dataset(), retrieval_only=True)
    assert report['summary']['retrieval_hit_at_6'] == 0.5
    assert report['summary']['pass_rate'] == 0.5
    assert report['summary']['support_accuracy'] is None
    assert report['results'][2]['passed'] is None


def test_dataset_and_baseline_validation():
    with pytest.raises(ValidationError):
        evaluation.EvaluationDataset.model_validate({
            'version': 1,
            'cases': [{'id': 'a', 'question': 'Valid question', 'year': 2026,
                       'campus': 'hanoi', 'expect_supported': True}],
        })
    with pytest.raises(ValidationError):
        evaluation.EvaluationDataset.model_validate({
            'version': 1,
            'cases': [
                {'id': 'same', 'question': 'One question', 'year': 2026,
                 'campus': 'hanoi', 'expect_supported': False},
                {'id': 'same', 'question': 'Other question', 'year': 2026,
                 'campus': 'hanoi', 'expect_supported': False},
            ],
        })
    with pytest.raises(ValueError, match='different evaluation dataset'):
        evaluation.compare_reports(
            {'dataset_sha256': 'a', 'mode': 'full', 'config': {'embedding_model': 'x'},
             'summary': {}},
            {'dataset_sha256': 'b', 'mode': 'full', 'config': {'embedding_model': 'x'},
             'summary': {}},
        )

