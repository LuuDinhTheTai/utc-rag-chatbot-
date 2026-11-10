"""Run from backend so .env and DATA_DIR match the API."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utc_crawler import crawl
from app.config import settings


def bounded(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description='Crawl UTC admissions respecting robots.txt; stage by default.')
    parser.add_argument('--max-pages', type=bounded(1, 20), default=2)
    parser.add_argument('--max-articles', type=bounded(1, 300), default=20)
    parser.add_argument('--max-requests', type=bounded(2, 500), default=100)
    parser.add_argument('--year', type=bounded(2000, 2100), help='Only publish this admission year')
    parser.add_argument('--publish', action='store_true', help='Embed and publish unambiguous text/PDF articles')
    parser.add_argument('--ocr', action='store_true', help='Use Gemini OCR for images/scanned PDFs; results require review')
    parser.add_argument('--recheck-existing', action='store_true', help='Revisit previously collected URLs to check updates or retry OCR')
    parser.add_argument('--output', type=Path, help='JSON run report')
    args = parser.parse_args()
    if (args.publish or args.ocr) and not settings().google_api_key:
        parser.error('--publish/--ocr requires GOOGLE_API_KEY')
    report = crawl(max_pages=args.max_pages, max_articles=args.max_articles,
                   max_requests=args.max_requests, do_publish=args.publish, year=args.year, ocr=args.ocr, recheck_existing=args.recheck_existing)
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
