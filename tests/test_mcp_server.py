"""Verifies MCP tool discovery and invocation for support_automation.server.

Calls tools through arcade_core.executor.ToolExecutor -- the same path
Arcade's MCP runtime uses -- rather than calling the underlying Python
functions directly, so this exercises the actual wire-format boundary
(schema generation, dict-flattened nested inputs, output serialization).
"""

import json
from pathlib import Path

import pytest
from arcade_core.executor import ToolExecutor
from arcade_core.schema import ToolContext

from support_automation.server import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_TOOLS = {
    "GenerateTicket",
    "ValidateTicket",
    "EnrichTicket",
    "RouteTicket",
    "RecommendActions",
}


def _tool(name: str):
    for materialized in app._catalog:
        if materialized.definition.name == name:
            return materialized
    raise AssertionError(f"tool not registered: {name}")


async def _call(name: str, **kwargs) -> dict:
    materialized = _tool(name)
    result = await ToolExecutor.run(
        materialized.tool,
        materialized.definition,
        materialized.input_model,
        materialized.output_model,
        ToolContext(),
        **kwargs,
    )
    dumped = result.model_dump(mode="json", exclude_none=True)
    assert "error" not in dumped, dumped.get("error")
    return dumped["value"]


def test_all_five_tools_are_discoverable():
    registered = {mt.definition.name for mt in app._catalog}
    assert _EXPECTED_TOOLS <= registered


@pytest.mark.asyncio
async def test_generate_ticket_round_trip():
    ticket = await _call("GenerateTicket", scenario="oauth_scope_mismatch")
    assert ticket["ticket_id"].startswith("TICK-")
    assert ticket["first_seen_at"]  # ISO string, not a datetime object


@pytest.mark.asyncio
async def test_hero_scenario_end_to_end_through_mcp_tools():
    hero = json.loads((_REPO_ROOT / "data" / "hero_ticket.json").read_text())
    ticket = {k: v for k, v in hero.items() if k != "metadata"}

    validation = await _call("ValidateTicket", ticket=ticket)
    assert validation["ready_for_automation"] is True

    enrichment = await _call("EnrichTicket", ticket=ticket)
    assert "oauth" in enrichment["domains"]
    assert "google" in enrichment["domains"]

    routing = await _call("RouteTicket", ticket=ticket, enrichment=enrichment)
    assert routing["queue"] == "identity-integrations"

    recommendation = await _call(
        "RecommendActions",
        ticket=ticket,
        validation=validation,
        enrichment=enrichment,
        routing=routing,
    )
    assert recommendation["severity"]["reported_severity"] == "P1"
    assert recommendation["severity"]["recommended_severity"] == "P2"
    rejected = [a["action"] for a in recommendation["actions_rejected"]]
    assert "page_infrastructure" in rejected
