import json
from pathlib import Path

from fastapi.testclient import TestClient

from support_automation.webapp.app import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_index_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "Support Automation Portal" in response.text


def test_samples_endpoint_includes_hero_ticket():
    response = client.get("/api/samples")
    assert response.status_code == 200
    ticket_ids = [t["ticket_id"] for t in response.json()]
    assert "TICK-MERIDIAN-001" in ticket_ids


def test_classify_generates_ticket_id_when_omitted():
    response = client.post(
        "/api/tickets/classify",
        json={"description": "Something is broken", "customer_id": "C-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ticket"]["ticket_id"].startswith("TICK-")


def test_classify_hero_ticket_matches_cli_pipeline():
    hero = json.loads((_REPO_ROOT / "data" / "hero_ticket.json").read_text())
    payload = {k: v for k, v in hero.items() if k != "metadata"}

    response = client.post("/api/tickets/classify", json=payload)
    assert response.status_code == 200
    body = response.json()

    assert body["routing"]["queue"] == "identity-integrations"
    assert body["severity"]["recommended_severity"] == "P2"
    assert any(
        s["type"] == "scope_mismatch" and s["value"] == "gmail.compose"
        for s in body["enrichment"]["signals"]
    )
    rejected_actions = [r["action"] for r in body["recommendation"]["actions_rejected"]]
    assert "page_infrastructure" in rejected_actions
