"""SQLite-backed per-IP fixed-window API rate limiting."""
import hashlib
import math
import time

from fastapi.responses import JSONResponse

from .config import settings
from .localdb import connect


def limits_for(request):
    config = settings()
    path = request.url.path
    limits = [('global', config.rate_limit_global)]
    if path in {'/admin/login', '/auth/login', '/auth/register', '/auth/password'}:
        limits.append(('login', config.rate_limit_login))
    elif path == '/chat':
        limits.append(('chat', config.rate_limit_chat))
    elif path.startswith('/admin/') and request.method in {'POST', 'PATCH', 'PUT', 'DELETE'}:
        limits.append(('admin_write', config.rate_limit_admin_write))
    return [(name, limit) for name, limit in limits if limit > 0]


async def rate_limit_middleware(request, call_next):
    if request.method == 'OPTIONS' or request.url.path in {'/docs', '/redoc', '/openapi.json'}:
        return await call_next(request)
    client = request.client.host if request.client else 'unknown'
    window = int(time.time() // 60) * 60
    keys = limits_for(request)
    counters = []
    # The transaction serializes updates across workers and avoids lost counts.
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for name, limit in keys:
            key = hashlib.sha256(f'{name}:{client}'.encode()).hexdigest()
            conn.execute(
                'INSERT INTO api_rate_limits(key,window_start,count) VALUES(?,?,1) '
                'ON CONFLICT(key,window_start) DO UPDATE SET count=count+1',
                (key, window),
            )
            count = conn.execute(
                'SELECT count FROM api_rate_limits WHERE key=? AND window_start=?',
                (key, window),
            ).fetchone()['count']
            counters.append((name, limit, count))
        # Periodic cleanup avoids a write on every request beyond the counters.
        if window % 600 == 0 and counters and counters[0][2] == 1:
            conn.execute('DELETE FROM api_rate_limits WHERE window_start < ?', (window - 600,))
    remaining_seconds = max(1, math.ceil(window + 60 - time.time()))
    exceeded = next(((name, limit, count) for name, limit, count in counters if count > limit), None)
    if exceeded:
        return JSONResponse(
            {'detail': 'Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau.'},
            status_code=429,
            headers={
                'Retry-After': str(remaining_seconds),
                'X-RateLimit-Limit': str(exceeded[1]),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': str(window + 60),
            },
        )
    response = await call_next(request)
    if counters:
        limiting = min(counters, key=lambda item: (item[1] - item[2]) / item[1])
        response.headers['X-RateLimit-Limit'] = str(limiting[1])
        response.headers['X-RateLimit-Remaining'] = str(max(0, limiting[1] - limiting[2]))
        response.headers['X-RateLimit-Reset'] = str(window + 60)
    return response
