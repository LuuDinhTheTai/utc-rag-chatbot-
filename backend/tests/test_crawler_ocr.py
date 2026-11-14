from types import SimpleNamespace

from app import rag, utc_crawler
from app.config import settings


def test_ocr_uses_dedicated_model(monkeypatch):
    import langchain_google_genai
    calls = []
    monkeypatch.setattr(langchain_google_genai, 'ChatGoogleGenerativeAI',
                        lambda **kwargs: calls.append(kwargs) or object())
    monkeypatch.setattr(rag, 'invoke_gemini', lambda *args: SimpleNamespace(
        content='Nội dung thông báo được đọc đầy đủ từ ảnh nguồn.'))
    monkeypatch.setenv('GEMINI_MODEL', 'unavailable-chat-model')
    monkeypatch.setenv('OCR_MODEL', 'working-ocr-model')
    settings.cache_clear()
    assert 'thông báo' in utc_crawler.ocr_resource(b'image', 'image/jpeg')
    assert calls[0]['model'] == 'working-ocr-model'


def test_ocr_errors_are_actionable_without_provider_secrets():
    error = type('GoogleModelNotFoundError', (Exception,), {})('secret provider response')
    message = utc_crawler.ocr_error_message(error)
    assert 'OCR_MODEL' in message
    assert 'secret' not in message
    assert 'secret' not in utc_crawler.ocr_error_message(ValueError('secret'))
