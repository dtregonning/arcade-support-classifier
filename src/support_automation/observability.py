"""Structured JSON logging for each automation step.

Not a telemetry platform — just one JSON line per tool invocation on a
dedicated logger, so the demo can show a real audit trail without adding
infrastructure.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("support_automation")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@contextmanager
def log_step(
    *,
    ticket_id: str,
    tool: str,
    matched_rule: str | None = None,
    confidence: float | None = None,
    human_review_required: bool | None = None,
) -> Iterator[dict[str, Any]]:
    """Context manager that emits one structured JSON log line for a tool
    invocation, including its duration. Yields a mutable dict the caller can
    fill in (e.g. matched_rule) before the block exits."""
    record: dict[str, Any] = {
        "ticket_id": ticket_id,
        "tool": tool,
        "matched_rule": matched_rule,
        "confidence": confidence,
        "human_review_required": human_review_required,
    }
    start = time.perf_counter()
    result = "ok"
    try:
        yield record
    except Exception:
        result = "error"
        raise
    finally:
        record["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
        record["result"] = result
        logger.info(json.dumps(record))
