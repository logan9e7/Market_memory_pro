"""Privacy-conscious structured HTTP access logging with request correlation.

Do not include query strings, bodies, cookies, authorization headers or trade text.
"""
import json
import logging
import sys
import time
import uuid

access_logger = logging.getLogger("market_memory.access")
access_logger.setLevel(logging.INFO)
access_logger.propagate = False
if not access_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)


def install_observability(app):
    @app.middleware("http")
    async def observe(request, call_next):
        request_id = uuid.uuid4().hex  # Never trust unvalidated client request IDs.
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        error_type = None
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            error_type = type(exc).__name__  # Avoid potentially secret exception strings.
            raise
        finally:
            route = request.scope.get("route")
            # Templated route avoids printing user-supplied path fragments.
            template = getattr(route, "path", "<unmatched>")
            access_logger.info(json.dumps({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "route": template,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                **({"error_type": error_type} if error_type else {}),
            }, separators=(",", ":")))
