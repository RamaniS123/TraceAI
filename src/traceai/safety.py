"""Fixed error responses and diagnostics without request or exception contents."""
import logging

from starlette.responses import JSONResponse

from traceai.errors import APIError

logger = logging.getLogger('traceai.safety')


class SafeAccessLog(logging.Filter):
    """Uvicorn's default request target includes user-supplied paths and queries."""

    def filter(self, record):
        # Keep status diagnostics without copying a credential placed in a URL.
        args = record.args
        status = args[4] if isinstance(args, tuple) and len(args) == 5 else None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        # Uvicorn's AccessFormatter requires the original five fields. Use a
        # constant safe target/method while retaining the status and protocol.
        record.msg = '%s - "%s %s HTTP/%s" %d'
        record.args = ('client', 'HTTP', '/[redacted]', '1.1', status if isinstance(status, int) else 500)
        return True


def configure_safe_access_logging():
    access = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, SafeAccessLog) for item in access.filters):
        access.addFilter(SafeAccessLog())


class SafeErrorBoundary:
    """Handle unexpected failures before Starlette/Uvicorn logs their contents.

    Routes return buffered responses. If a future streaming response fails after
    headers are sent, re-raise a fixed exception rather than pretending it completed.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        started = False

        async def safe_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            logger.error('Request failed: INTERNAL_ERROR.')
            if started:
                raise RuntimeError('Response could not be completed.') from None
            path = scope.get('path', '')
            if path.startswith('/tester/test/'):
                body = {'message': 'The tester could not complete the request.', 'source': 'tester'}
            elif path.startswith('/test/'):
                body = {'message': 'The system could not complete the request.', 'source': 'system'}
            else:
                body = APIError(500, 'INTERNAL_ERROR', 'Request could not be completed.').body()
            await JSONResponse(body, status_code=500)(scope, receive, send)
