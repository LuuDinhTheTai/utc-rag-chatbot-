"""Request-local chat timings. Never record questions, documents or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import json
import logging
import time
from uuid import uuid4

log = logging.getLogger('utc')
STAGES = ('history', 'routing', 'embedding_setup', 'embedding', 'retrieval', 'generation', 'save')


@dataclass
class ChatTrace:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    stages: dict = field(default_factory=lambda: dict.fromkeys(STAGES))
    current_stage: str | None = None
    failed_stage: str | None = None
    retry_count: int = 0
    retry_wait_ms: float = 0


_active_trace: ContextVar[ChatTrace | None] = ContextVar('chat_trace', default=None)


@contextmanager
def measure_stage(name):
    trace = _active_trace.get()
    if trace is None:
        yield
        return
    started = time.perf_counter()
    previous = trace.current_stage
    trace.current_stage = name
    status = 'ok'
    try:
        yield
    except BaseException:
        status = 'error'
        trace.failed_stage = name
        raise
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        trace.stages[name] = (trace.stages.get(name) or 0) + elapsed
        trace.current_stage = previous
        log.info('chat_stage request_id=%s stage=%s duration_ms=%.2f status=%s',
                 trace.request_id, name, elapsed, status)


def record_retry(wait_seconds, status):
    trace = _active_trace.get()
    if trace is not None:
        trace.retry_count += 1
        trace.retry_wait_ms += wait_seconds * 1000
        log.info('chat_retry request_id=%s stage=%s provider_status=%s wait_ms=%.2f',
                 trace.request_id, trace.current_stage, status, wait_seconds * 1000)


def trace_chat(handler):
    """Keep route signatures and isolate concurrent requests via ContextVar."""
    @wraps(handler)
    def wrapped(*args, **kwargs):
        trace = ChatTrace()
        token = _active_trace.set(trace)
        started = time.perf_counter()
        result = None
        status, error_type = 'ok', None
        try:
            result = handler(*args, **kwargs)
            return result
        except BaseException as exc:
            status, error_type = 'error', type(exc).__name__
            raise
        finally:
            total_ms = (time.perf_counter() - started) * 1000
            measured_ms = sum(value for value in trace.stages.values() if value is not None)
            summary = {
                'request_id': trace.request_id,
                'message_id': result.get('id') if isinstance(result, dict) else None,
                'status': status,
                'response_kind': result.get('response_kind') if isinstance(result, dict) else None,
                'error_type': error_type,
                'failed_stage': trace.failed_stage,
                'timings_ms': {name: round(value, 2) if value is not None else None
                               for name, value in trace.stages.items()},
                'total_ms': round(total_ms, 2),
                'other_ms': round(max(0, total_ms - measured_ms), 2),
                # Application retries only; SDK retries remain included in stage time.
                # Retry wait is included in its stage/total, not an extra stage.
                'retry_count': trace.retry_count,
                'retry_wait_ms': round(trace.retry_wait_ms, 2),
            }
            _active_trace.reset(token)
            log.info('chat_timing %s', json.dumps(summary, separators=(',', ':')))
    return wrapped
