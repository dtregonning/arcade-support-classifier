"""Optional AI fallback for the taxonomy's "system area" tag.

Only ever consulted from tools/enrich_ticket.py, and only when the
deterministic rule engine (services/enricher.py) detected no domain at
all for a ticket -- it never overrides or supplements a rule-based
result, and its output never feeds into routing (routing only ever
reads `domains`, not `system_areas` -- see models/enrichment.py).

Constrained to the closed SystemArea enum via Anthropic's tool-use: the
tool's input_schema declares `area` as a JSON Schema enum of exactly
SystemArea's values, and the call forces that tool via `tool_choice`.
The model cannot return a value outside that set -- the API itself
rejects the underlying sampling outside the schema, not just a prompt
asking nicely -- which is what keeps this from growing into an
unbounded pile of one-off tags over time.

Degrades to a no-op (returns None) without ANTHROPIC_API_KEY, and on any
SDK/network error -- exactly like Arcade execution degrades without
ARCADE_API_KEY. This must never become a hard dependency of enrichment;
CLAUDE.md is explicit that the system works with zero external API keys.
"""

from __future__ import annotations

import os

from support_automation.models.enrichment import SystemArea

_MODEL = "claude-haiku-4-5"
_TOOL_NAME = "classify_system_area"
_CLASSIFIABLE_AREAS = [a.value for a in SystemArea if a != SystemArea.UNKNOWN]

_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": (
        "Classify a support ticket's evidence text into exactly one system area."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "enum": _CLASSIFIABLE_AREAS,
                "description": "The single best-fitting system area for this ticket's evidence.",
            }
        },
        "required": ["area"],
    },
}


def classify_area(evidence: str) -> SystemArea | None:
    """Returns a SystemArea if classification succeeds, else None -- the
    caller (tools/enrich_ticket.py) treats None exactly like "no API key
    configured" and leaves the ticket tagged SystemArea.UNKNOWN. Never
    raises."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not evidence.strip():
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=64,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Classify this support ticket's evidence into the single "
                        f"best-fitting system area:\n\n{evidence[:4000]}"
                    ),
                }
            ],
        )
    except Exception:
        return None

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            try:
                return SystemArea(block.input.get("area"))
            except ValueError:
                return None
    return None
