import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Small structured formatter that never serializes request bodies or query strings."""

    def format(self, record):
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "request_id",
            "method",
            "path",
            "status",
            "duration_ms",
            "user_id",
            "action",
            "actor_id",
            "municipality_id",
            "object_type",
            "object_id",
            "issue_id",
            "issue_attachment_id",
            "receipt_delivery_id",
            "original_size_bytes",
            "stored_size_bytes",
            "reduction_ratio",
            "processed_width",
            "processed_height",
            "processing_version",
            "storage_state",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
