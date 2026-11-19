"""
Assignment 11 — Audit log.

Records every interaction for forensics. Never blocks by itself —
other layers catch attacks; this layer makes them reviewable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from agents.security_boundary import contains_secret
from guardrails.output_guardrails import content_filter


def default_audit_log_path() -> str:
    """Always resolve to <repo>/outputs/… (safe when cwd is src/)."""
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / "outputs" / "audit_log.json")


def sanitize_audit_text(text: str) -> str:
    """Apply the output policy before retaining text in artifacts."""
    filtered = content_filter(text)["redacted"]
    if contains_secret(filtered):
        return "[REDACTED]"
    return filtered


@dataclass(frozen=True)
class _PendingRequest:
    text: str
    timestamp: str
    started_at: float


class AuditLogPlugin:
    """Framework-agnostic audit logger (wire into ADK callbacks or your pipeline)."""

    def __init__(self):
        self.name = "audit_log"
        self.logs: list[dict] = []
        self._open: dict[tuple[str, str | None], _PendingRequest] = {}

    def record_input(self, *, user_id: str, text: str, request_id: str | None = None):
        """Keep sanitized input and timing until the matching response arrives."""
        started_at = monotonic()
        timestamp = utc_now_iso()
        self._open[user_id, request_id] = _PendingRequest(
            sanitize_audit_text(text), timestamp, started_at
        )

    def record_output(
        self,
        *,
        user_id: str,
        text: str,
        blocked: bool = False,
        layer: str | None = None,
        request_id: str | None = None,
    ):
        """Append the outcome using the same user and request identifiers."""
        pending = self._open.pop((user_id, request_id), None)
        latency_ms = round((monotonic() - pending.started_at) * 1000, 3) if pending else None
        self.logs.append({
            "request_id": request_id,
            "user_id": user_id,
            "timestamp": pending.timestamp if pending else utc_now_iso(),
            "input": pending.text if pending else None,
            "output": sanitize_audit_text(text),
            "blocked": blocked,
            "layer": layer,
            "latency_ms": latency_ms,
        })

    def export_json(self, filepath: str | Path | None = None):
        """Write logs to disk (JSON array) under repo-root ``outputs/`` by default."""
        path = Path(filepath or default_audit_log_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.logs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
