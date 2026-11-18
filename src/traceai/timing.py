"""Response-ready timing for buffered HTTP routes, independent of client clocks."""
from time import perf_counter_ns


class ApplicationTiming:
    """Measure ASGI entry through response-start, including serialization.

    This includes auth, routing/threadpool/pool waits and PostgreSQL I/O. It
    excludes pre-ASGI queuing, network/TLS, and response-body transfer. Streaming
    responses measure headers only; they must not be used for this benchmark.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        started_at = perf_counter_ns()

        async def timed_send(message):
            if message['type'] == 'http.response.start':
                elapsed = perf_counter_ns() - started_at
                # Exact integer formatting: do not round a duration above 1 s down
                # to the acceptance threshold. Six decimal milliseconds = 1 ns.
                value = f'traceai_app;dur={elapsed // 1_000_000}.{elapsed % 1_000_000:06d}'.encode('ascii')
                message = {**message, 'headers': [*message.get('headers', []), (b'server-timing', value)]}
            await send(message)

        await self.app(scope, receive, timed_send)
