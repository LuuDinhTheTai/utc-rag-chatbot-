"""Run a saved RAG question set from the backend directory."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.evaluation import (compare_reports, dataset_hash, default_report_path,
                            evaluate, load_dataset, write_report)


def score(value):
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError('Expected a number between 0 and 1.')
    return number


def main():
    parser = argparse.ArgumentParser(
        description='Evaluate RAG retrieval and optionally Gemini answers without writing chat history.')
    parser.add_argument('dataset', type=Path, help='Version 1 evaluation JSON file')
    parser.add_argument('--retrieval-only', action='store_true',
                        help='Skip answer generation; query embeddings still call Gemini')
    parser.add_argument('--baseline', type=Path, help='Previous JSON report to compare')
    parser.add_argument('--output', type=Path, help='Report path (default: DATA_DIR/evaluations/run-TIMESTAMP.json)')
    parser.add_argument('--fail-below', type=score, metavar='RATE',
                        help='Exit 1 if pass rate is below RATE (for example 1.0)')
    args = parser.parse_args()

    try:
        dataset = load_dataset(args.dataset)
        baseline = json.loads(args.baseline.read_text(encoding='utf-8-sig')) if args.baseline else None
        if baseline is not None:
            if not isinstance(baseline, dict):
                raise ValueError('Baseline report must be a JSON object.')
            mode = 'retrieval' if args.retrieval_only else 'full'
            if baseline.get('dataset_sha256') != dataset_hash(dataset):
                raise ValueError('Baseline uses a different evaluation dataset.')
            if baseline.get('mode') != mode:
                raise ValueError('Baseline uses a different evaluation mode.')
            if baseline.get('config', {}).get('embedding_model') != settings().embedding_model:
                raise ValueError('Baseline uses a different embedding model.')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    report = evaluate(dataset, retrieval_only=args.retrieval_only)
    if baseline is not None:
        report['baseline_delta'] = compare_reports(report, baseline)
    output = args.output or default_report_path()
    write_report(report, output)

    for row in report['results']:
        state = 'ERROR' if row['error'] else 'SKIP' if row['passed'] is None else 'PASS' if row['passed'] else 'FAIL'
        rank = next((i for i, source in enumerate(row.get('retrieved', []), 1)
                     if source['source_url'] in row.get('expected_source_urls', [])), None)
        print(f"{state:5} {row['id']}  expected_source_rank={rank or '-'}"
              + (f"  error={row['error']}" if row['error'] else ''))
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    if baseline is not None:
        print('Delta from baseline:', json.dumps(report['baseline_delta'], ensure_ascii=False))
    print('Report:', output.resolve())
    if report['summary']['errors']:
        return 2
    if args.fail_below is not None and (report['summary']['pass_rate'] or 0) < args.fail_below:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

