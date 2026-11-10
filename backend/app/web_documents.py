"""Read a manually selected UTC page and its images/PDF attachments."""
import io
import time
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .rag import MAX_BYTES, extract, valid_url

MAX_ASSETS = 20
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def fetch_web_document(url, *, ocr=False):
    # Import at call time: the crawler also imports the regular RAG extractors.
    from .utc_crawler import ocr_resource

    warnings, resources = [], []
    total_bytes = 0
    started = time.monotonic()

    def check_time():
        if time.monotonic() - started > 420:
            raise ValueError('Đã hết thời gian đọc trang. Hãy thêm từng ảnh/PDF bằng URL trực tiếp.')

    def download(client, target):
        nonlocal total_bytes
        for _ in range(4):
            check_time()
            valid_url(target)
            with client.stream('GET', target) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = urljoin(target, response.headers['location'])
                    continue
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_bytes():
                    data.extend(part)
                    total_bytes += len(part)
                    if len(data) > MAX_BYTES or total_bytes > MAX_TOTAL_BYTES:
                        raise ValueError('Tài nguyên vượt quá 10 MB hoặc tổng dữ liệu vượt quá 50 MB.')
                return target, response.headers.get('content-type', '').split(';')[0].strip().lower(), bytes(data)
        raise ValueError('URL chuyển hướng quá nhiều lần.')

    def read_media(data, mime):
        check_time()
        if mime == 'application/pdf':
            if not data.startswith(b'%PDF-'):
                raise ValueError('Nội dung không phải PDF hợp lệ.')
            try:
                reader = PdfReader(io.BytesIO(data))
            except PdfReadError as exc:
                raise ValueError('Không đọc được PDF. Kiểm tra tệp nguồn.') from exc
            if len(reader.pages) > 300:
                raise ValueError('PDF tối đa 300 trang.')
            pages = [page.extract_text() or '' for page in reader.pages]
            if any(len(page.strip()) < 30 for page in pages):
                if not ocr:
                    raise ValueError('PDF có trang scan. Bật “Đọc cả ảnh và PDF scan (OCR)”.')
                if len(pages) > 30:
                    raise ValueError('PDF dùng OCR tối đa 30 trang.')
                return ocr_resource(data, mime), True
            return extract(data, 'source.pdf'), False
        if mime in {'image/jpeg', 'image/png', 'image/webp'}:
            if not ocr:
                raise ValueError('Bật “Đọc cả ảnh và PDF scan (OCR)” để đọc ảnh.')
            return ocr_resource(data, mime), True
        raise ValueError('Chỉ hỗ trợ HTML, PDF và ảnh JPEG, PNG, WebP từ web.')

    with httpx.Client(timeout=25, follow_redirects=False) as client:
        final, mime, data = download(client, url.strip())
        if mime != 'text/html':
            text, used_ocr = read_media(data, mime)
            return {'text': text, 'ocr_used': used_ocr, 'warnings': warnings,
                    'resources': [{'url': final, 'ocr': used_ocr}]}

        soup = BeautifulSoup(data, 'html.parser')
        body = (soup.select_one('.node-tin-tuyen-sinh.node-full .field-name-body')
                or soup.find('article') or soup.find('main') or soup.body or soup)
        for tag in body.select('script, style, nav, footer, header, iframe, form, .node-teaser'):
            tag.decompose()
        assets = []
        for tag in body.select('img[src], a[href]'):
            raw = tag.get('src') if tag.name == 'img' else tag.get('href')
            if tag.name != 'img' and not urlsplit(raw).path.lower().endswith('.pdf'):
                continue
            target = urldefrag(urljoin(final, raw))[0]
            if target not in assets:
                assets.append(target)
        if len(assets) > MAX_ASSETS:
            raise ValueError('Trang có quá 20 ảnh/tệp PDF. Hãy thêm từng tài liệu bằng URL trực tiếp.')
        texts = [body.get_text('\n', strip=True)]
        used_ocr = False
        for target in assets:
            # Skip images when OCR was not requested; PDFs with text still work.
            if not ocr and not urlsplit(target).path.lower().endswith('.pdf'):
                warnings.append(f'Chưa đọc ảnh (OCR chưa bật): {target}')
                continue
            try:
                asset_url, asset_mime, asset_data = download(client, target)
                asset_text, asset_ocr = read_media(asset_data, asset_mime)
                texts.append(asset_text)
                resources.append({'url': asset_url, 'ocr': asset_ocr})
                used_ocr = used_ocr or asset_ocr
            except (ValueError, httpx.HTTPError):
                warnings.append(f'Không đọc được ảnh/tệp đính kèm: {target}. Kiểm tra nguồn trước khi lưu.')
        text = '\n\n'.join(part for part in texts if part.strip()).strip()
        if len(text) < 30:
            raise ValueError('Không đủ văn bản từ trang và ảnh/PDF đính kèm. Hãy bật OCR hoặc kiểm tra URL nguồn.')
        if len(text) > 2_000_000:
            raise ValueError('Nội dung trích xuất vượt quá 2.000.000 ký tự.')
        return {'text': text, 'ocr_used': used_ocr, 'warnings': warnings, 'resources': resources}
