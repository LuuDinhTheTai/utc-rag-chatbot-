"""Defaults to offline rule checks. --live explicitly enables Gemini classification."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.routing_evaluation import evaluate, load_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--live', action='store_true', help='Call Gemini; no embeddings or chat history writes')
    parser.add_argument('--split', choices=['development', 'acceptance'])
    parser.add_argument('--case', action='append', dest='case_ids', help='Run selected case ID; repeat to select several')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        dataset = load_dataset(args.dataset)
        if args.case_ids:
            if set(args.case_ids) - {case.id for case in dataset.cases}:
                parser.error('Unknown case ID')
            dataset.cases = [case for case in dataset.cases if case.id in args.case_ids]
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    report = evaluate(dataset, live=args.live, split=args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    return 2 if report['summary']['errors'] else 1 if any(r['passed'] is False for r in report['results']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
