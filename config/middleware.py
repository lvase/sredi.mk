import logging
import re
import time
import uuid

logger = logging.getLogger("sredi.request")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,80}$")


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        request.request_id = request_id
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "user_id": request.user.pk if getattr(request, "user", None) and request.user.is_authenticated else None,
            },
        )
        return response
