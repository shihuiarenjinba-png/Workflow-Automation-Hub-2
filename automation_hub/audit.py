from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import audit_log_path

SENSITIVE_KEY_PARTS = (
    "access_token", "refresh_token", "id_token", "token", "secret", "password",
    "authorization", "api_key", "apikey", "credential",
)
REDACTED = "[REDACTED]"
SENSITIVE_TEXT_PATTERN = re.compile(
    r'''(?i)(["']?(?:access_token|refresh_token|id_token|client_secret|api_key|password)["']?\s*[:=]\s*["']?)([^"'\s,}&]+)'''
)
BEARER_PATTERN = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+\-/]+=*")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_text(value: str) -> str:
    value = BEARER_PATTERN.sub(rf"\1{REDACTED}", value)
    return SENSITIVE_TEXT_PATTERN.sub(rf"\1{REDACTED}", value)


def _redact(value: Any, key: str = "") -> Any:
    if key and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


class AuditLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or audit_log_path()

    def write(self, event: str, **fields: Any) -> None:
        row = _redact({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise OSError("short audit-log write")
        finally:
            os.close(fd)
