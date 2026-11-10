"""Compare document content without layout-only whitespace differences."""
import hashlib
import re
import unicodedata
from collections import Counter
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from .document_scope import document_years


def source_key(url):
    """Match URL aliases without discarding query parameters identifying a page."""
    from .rag import valid_url
    if not url:
        return None
    try:
        valid_url(url.strip())
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    host = parsed.hostname.removeprefix('www.')
    path = unquote(parsed.path or '/')
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}]
    route = dict(query).get('q', '').lstrip('/')
    if host == 'tuyensinh.utc.edu.vn' and path == '/' and route.startswith('tin-tuyen-sinh/'):
        path = '/' + route
        query = [(key, value) for key, value in query if key != 'q']
    return urlunsplit(('https', host, quote(path.rstrip('/') or '/', safe='/()'), urlencode(sorted(query)), ''))


def matching_sources(database, source_url):
    key = source_key(source_url)
    if not key:
        return []
    rows = database.table('documents').select('id,title,status,source_url,admission_year,campus').execute().data
    return [dict(row, reason='source_url') for row in rows if source_key(row['source_url']) == key]


def normalized_text(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def document_checksum(text, year, campus):
    return hashlib.sha256(f'{year}:{campus}:{normalized_text(text)}'.encode()).hexdigest()


def covers_duplicate_year(row, year):
    # The storage year remains part of the document identity even when the title
    # describes historical years. Retrieval coverage must not hide a saved copy.
    return year == row['admission_year'] or year in document_years(row['title'], row['admission_year'])


def content_fingerprint(text):
    # Keep accents and numeric values: a new cutoff/fee is a different document.
    text = unicodedata.normalize('NFKC', text).casefold()
    numbers = tuple(re.findall(r'\d+(?:[.,:/-]\d+)*', text))
    tokens = re.findall(r'[^\W_]+', text, flags=re.UNICODE)
    shingles = Counter(hash(tuple(tokens[i:i + 5])) for i in range(len(tokens) - 4))
    return tokens, numbers, shingles


def content_similarity(left, right):
    a, a_numbers, a_shingles = left
    b, b_numbers, b_shingles = right
    if a_numbers != b_numbers or not a or not b:
        return None
    if a == b:
        return 1.0  # Case, punctuation and PDF line wrapping only.
    # Short/template text is not enough evidence for automatic rejection.
    if min(len(a), len(b)) < 60 or min(len(a_shingles), len(b_shingles)) < 20:
        return None
    if min(len(a), len(b)) / max(len(a), len(b)) < .85:
        return None
    overlap = sum((a_shingles & b_shingles).values())
    similarity = 2 * overlap / (sum(a_shingles.values()) + sum(b_shingles.values()))
    return similarity if similarity >= .92 else None


def find_duplicate(database, text, year, campus, source_url=''):
    # A crawler and a manual import can extract different text from the same page.
    for row in matching_sources(database, source_url):
        if covers_duplicate_year(row, year) and row['campus'] == campus:
            return row
    checksum = document_checksum(text, year, campus)
    rows = database.table('documents').select('id,title,status').eq('checksum', checksum).execute().data
    if rows:
        return {key: rows[0][key] for key in ('id', 'title', 'status')} | {'reason': 'content'}
    # Old documents and crawler imports retain their original checksums.
    rows = (database.table('documents').select('id,title,status,raw_text,admission_year')
            .eq('campus', campus).execute().data)
    return find_content_duplicate(rows, text, year)


def find_content_duplicate(rows, text, year):
    """Shared content rules for manual imports and crawler transactions."""
    content = normalized_text(text)
    fingerprint = content_fingerprint(text)
    best = None
    for row in rows:
        if not covers_duplicate_year(row, year):
            continue
        if normalized_text(row['raw_text']) == content:
            return {key: row[key] for key in ('id', 'title', 'status')} | {'reason': 'content'}
        similarity = content_similarity(fingerprint, content_fingerprint(row['raw_text']))
        if similarity is not None and (best is None or similarity > best['similarity']):
            best = {key: row[key] for key in ('id', 'title', 'status')} | {
                'reason': 'content' if similarity == 1 else 'near_content', 'similarity': round(similarity, 4),
            }
    return best
