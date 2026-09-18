CLAUDE.md

Support Automation MCP Demo

Project Purpose

Build a small but credible support-engineering automation system that demonstrates how an engineering-led support organization can automate:

Ticket generation

Ticket validation

Ticket enrichment

Severity assessment

Ticket routing

Recommended support actions

Escalation into operational systems

The project should expose its core capabilities as MCP tools and integrate with Arcade.

This is NOT intended to become a complete helpdesk product.

The purpose is to demonstrate that the owner can move from:

support strategy
→ automation design
→ implementation
→ MCP tools
→ policy
→ operational execution

The finished demo should be understandable in approximately 10 minutes.

Core Demo Story

A support ticket arrives from an enterprise customer.

Example:

Approximately one third of our users can no longer send Gmail through our AI agent.
Our AI team believes Arcade is losing tokens.

Additional context:

Google toolkit upgraded Monday

Okta signing certificate rotated Thursday

Salesforce has been returning HTTP 429 responses

Customer connected Google accounts approximately one month ago

Relevant logs:

required_scopes=[gmail.send,gmail.compose]
granted_scopes=[gmail.readonly,gmail.send]

The system should automatically:

Validate whether the ticket contains enough information

Extract relevant technical signals

Separate facts from customer hypotheses

Determine likely support domain

Determine severity

Select a destination queue

Recommend next actions

Escalate when appropriate

Produce structured evidence explaining WHY it made those decisions

For this example the system should identify a likely OAuth scope mismatch.

It should NOT incorrectly associate unrelated Salesforce 429s or the Okta certificate rotation with the Gmail issue without evidence.

Design Principles

1. AI is not the policy engine

Use AI where reasoning or extraction helps.

Examples:

summarize an issue

extract symptoms

identify technologies

classify likely problem domains

identify possible hypotheses

Use deterministic code and policy for:

severity thresholds

routing

paging

required fields

authorization

escalation rules

customer-impacting actions

safety boundaries

The architecture should make this separation obvious.

2. Every automation decision must be explainable

Do not return:

{
  "queue": "identity"
}

Return:

{
  "queue": "identity-integrations",
  "confidence": 0.96,
  "reason_codes": [
    "oauth_scope_mismatch",
    "google_provider",
    "partial_user_impact"
  ],
  "evidence": [
    "gmail.compose required but not granted",
    "gmail.send is granted",
    "approximately one third of users affected"
  ]
}

The demo should make it obvious why the system took an action.

3. Prefer small, composable tools

Do not create one enormous tool called:

process_support_ticket()

Build individual MCP tools that can be composed.

Required MCP tools:

generate_ticket

validate_ticket

enrich_ticket

route_ticket

recommend_actions

Optional after the MVP:

simulate_ticket_flow

get_routing_rules

explain_route

Technology

Use:

Python 3.12+

uv

Pydantic

pytest

Ruff

YAML for routing policy

Arcade MCP / arcade_mcp_server

Use the Arcade CLI where appropriate.

Initial Arcade setup may use:

uv tool install arcade-mcp
arcade new support_automation

Do not introduce a database in the MVP.

Do not introduce Docker unless there is a specific need.

Do not introduce Kafka, Redis, Kubernetes, Celery, Temporal, or other infrastructure.

This is a demonstration of support automation logic, not distributed systems architecture.

Proposed Repository Structure

Create approximately this structure:

support-automation/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── config/
│   ├── routing_rules.yaml
│   └── validation_rules.yaml
│
├── data/
│   └── sample_tickets.json
│
├── src/
│   └── support_automation/
│       ├── __init__.py
│       ├── server.py
│       │
│       ├── models/
│       │   ├── ticket.py
│       │   ├── validation.py
│       │   ├── enrichment.py
│       │   └── routing.py
│       │
│       ├── tools/
│       │   ├── generate_ticket.py
│       │   ├── validate_ticket.py
│       │   ├── enrich_ticket.py
│       │   ├── route_ticket.py
│       │   └── recommend_actions.py
│       │
│       ├── services/
│       │   ├── validator.py
│       │   ├── enricher.py
│       │   ├── severity.py
│       │   ├── router.py
│       │   └── recommendations.py
│       │
│       └── cli.py
│
└── tests/
    ├── test_validator.py
    ├── test_router.py
    ├── test_severity.py
    └── test_demo_scenarios.py

Do not obsess over this exact hierarchy if Arcade's generated project structure suggests a cleaner implementation.

Ticket Model

Create a typed Pydantic model.

Suggested fields:

ticket_id
customer_id
customer_name
customer_tier

subject
description

reported_severity
affected_users
total_users

product
provider
environment

error_messages
logs

reproduction_steps

first_seen_at
reported_at

recent_changes

customer_hypothesis

metadata

Not every field must be populated.

Missing information is part of what the validator detects.

Tool 1: generate_ticket

Purpose:

Generate realistic mock support tickets for testing.

Input should allow:

scenario
customer_tier
completeness

Example scenarios:

oauth_scope_mismatch

expired_token

kubernetes_crashloop

kubernetes_oom

api_rate_limit

network_timeout

database_connection_exhaustion

unknown_issue

Example:

{
  "scenario": "oauth_scope_mismatch",
  "customer_tier": "enterprise",
  "completeness": 0.8
}

The generator should intentionally omit fields when completeness is below 1.0.

This allows the validation system to demonstrate useful behavior.

Use deterministic seeded randomness so tests remain reproducible.

Tool 2: validate_ticket

This must primarily be deterministic.

Checks should include:

Identity

ticket ID

customer

product/environment

Impact

affected users

customer tier

business impact

Timing

first failure timestamp

timezone if needed

Evidence

logs

error messages

reproduction details

Technical Context

provider

recent changes

relevant configuration

Return:

{
  "valid": false,
  "completeness_score": 72,
  "missing_fields": [
    "affected_users",
    "first_seen_at"
  ],
  "warnings": [
    {
      "code": "severity_unsupported",
      "message": "Ticket claims P1 but currently describes impact to one user."
    }
  ],
  "ready_for_automation": false
}

Completeness score must be derived from visible rules.

Do not invent a fake AI confidence number for deterministic checks.

Tool 3: enrich_ticket

Enrichment should turn raw ticket information into structured technical context.

Return something similar to:

{
  "domains": [
    "identity",
    "oauth",
    "google"
  ],
  "signals": [
    {
      "type": "scope_mismatch",
      "value": "gmail.compose",
      "evidence": "required_scopes includes gmail.compose but granted_scopes does not"
    }
  ],
  "technologies": [
    "Google",
    "OAuth",
    "Gmail"
  ],
  "customer_hypotheses": [
    "Arcade is losing tokens"
  ],
  "observed_facts": [
    "gmail.compose scope is required",
    "gmail.compose scope was not granted"
  ],
  "possible_causes": [
    {
      "cause": "OAuth scope mismatch",
      "confidence": 0.96
    }
  ]
}

Critical requirement:

Distinguish:

FACT

from:

CUSTOMER CLAIM

from:

SYSTEM HYPOTHESIS

Do not mix them together.

LLM Abstraction

Create an enrichment interface.

For example:

class TicketEnricher(Protocol):
    def enrich(self, ticket: SupportTicket) -> TicketEnrichment:
        ...

Implement:

RuleBasedEnricher

first.

The application must work completely without an external LLM API key.

Optionally support an AI enricher later.

Do not block the MVP on LLM connectivity.

The point is to demonstrate where AI CAN be inserted, not to make the project dependent on it.

Tool 4: route_ticket

Routing MUST be driven by externalized policy.

Use:

config/routing_rules.yaml

Example policy:

rules:

  - id: oauth-google
    priority: 100
    when:
      domain: oauth
      provider: google
    route:
      queue: identity-integrations
      owner: support-engineering

  - id: kubernetes-crash
    priority: 90
    when:
      signal_any:
        - crashloopbackoff
        - oomkilled
    route:
      queue: platform
      owner: platform-support

  - id: api-rate-limit
    priority: 80
    when:
      signal: http_429
    route:
      queue: integrations
      owner: support-engineering

  - id: unknown
    priority: 0
    when:
      always: true
    route:
      queue: general-triage
      owner: support

The routing engine should evaluate rules by priority.

Return:

{
  "queue": "identity-integrations",
  "owner": "support-engineering",
  "matched_rule": "oauth-google",
  "routing_confidence": 0.96,
  "reason_codes": [
    "google_provider",
    "oauth_scope_mismatch"
  ],
  "requires_human_review": false
}

Severity Engine

Do NOT blindly trust customer-selected severity.

Calculate an internal severity recommendation.

Example logic:

P1

Typical requirements:

production unavailable OR

widespread mission-critical failure

no reasonable workaround

significant customer/business impact

P2

Typical requirements:

degraded production functionality

subset of users impacted

important workflow impaired

workaround may exist

P3

isolated problem

limited impact

non-critical functionality

P4

informational

enhancement

documentation

Return both:

reported_severity
recommended_severity

If they differ, explain why.

Never silently overwrite the customer's reported severity.

Tool 5: recommend_actions

Based on:

validation result

enrichment

severity

route

return recommended actions.

Example:

{
  "actions": [
    {
      "action": "request_google_reauthorization",
      "risk": "low",
      "execution": "human_approval"
    },
    {
      "action": "create_linear_issue",
      "risk": "low",
      "execution": "automatic"
    },
    {
      "action": "notify_support_channel",
      "risk": "low",
      "execution": "automatic"
    }
  ],
  "actions_rejected": [
    {
      "action": "page_infrastructure",
      "reason": "No infrastructure evidence currently supports paging."
    }
  ]
}

This rejected-actions concept is important.

Show not only what automation WOULD do, but also what it deliberately refuses to do.

Automation Policy

Define three execution classes:

AUTO
APPROVAL_REQUIRED
HUMAN_ONLY

Examples:

AUTO

ticket tagging

classification

enrichment

routing

adding internal notes

creating low-risk internal issues

APPROVAL_REQUIRED

sending customer communications

changing customer configuration

reauthorization requests

paging teams for ambiguous incidents

HUMAN_ONLY

destructive operations

irreversible actions

security-sensitive changes

uncertain high-impact actions

Do not let an LLM bypass these controls.

Arcade Architecture

The desired architecture is:

                        ┌──────────────────────┐
                        │  Claude / MCP Client │
                        └───────────┬──────────┘
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │  Arcade MCP Gateway  │
                        └───────────┬──────────┘
                                    │
             ┌──────────────────────┼─────────────────────┐
             │                      │                     │
             ▼                      ▼                     ▼
    Support Automation MCP        Slack                Linear
       Custom Server          Arcade Toolkit       Arcade Toolkit

Our custom server owns:

validation

enrichment

routing

severity

support policy

Arcade-provided integrations own execution into external systems.

Do NOT write custom OAuth implementations for Slack or Linear.

Do NOT put Slack/Linear API tokens into our MCP server.

Use Arcade's integrations when available.

Important Architectural Boundary

The custom support MCP server should NOT recursively invoke itself through the Arcade Gateway.

The MCP client/agent should orchestrate tools.

Example:

Claude receives ticket

→ support.validate_ticket

→ support.enrich_ticket

→ support.route_ticket

→ support.recommend_actions

IF recommended action=create_linear_issue
→ Arcade Linear tool

IF recommended action=notify_support_channel
→ Arcade Slack tool

This separation is intentional.

Arcade Integration

After the custom tools work locally:

Run the custom MCP server locally.

Verify all MCP tools are discoverable.

Configure an Arcade MCP Gateway.

Add the custom MCP server to Arcade when practical.

Add Slack and/or Linear tools.

Connect Claude Code or another MCP client to the Gateway.

Run the demo through the combined tool surface.

Current Arcade CLI-style local commands may include:

arcade login

uv run server.py stdio

or:

uv run server.py http

Claude client configuration may be performed using:

arcade configure claude

If connecting Claude Code directly to an Arcade Gateway:

claude mcp add arcade --transport http "<ARCADE_GATEWAY_URL>"

Do not hardcode gateway URLs.

Sample Tickets

Create at least 10 sample tickets.

Required scenarios:

Gmail OAuth scope mismatch

Expired OAuth token

Kubernetes CrashLoopBackOff

Kubernetes OOMKilled

Salesforce/API HTTP 429

Database connection pool exhaustion

Generic HTTP 500 spike

Network timeout

Bad customer configuration

Insufficient-information ticket

At least two tickets should intentionally contain misleading customer hypotheses.

Example:

Customer says:

"Your servers are down."

Evidence actually shows:

HTTP 401
invalid_scope

Automation should privilege evidence over the unsupported hypothesis.

Hero Demo Scenario

Create:

data/hero_ticket.json

Scenario:

Enterprise customer Acme.

Approximately one third of users cannot send Gmail messages.

Customer hypothesis:

Arcade is losing tokens.

Recent changes:

Okta signing certificate rotated Thursday

Salesforce HTTP 429s observed

Google toolkit upgraded v3.1 → v3.4 Monday

Logs:

tool=Gmail.SendEmail
status=authorization_required
required_scopes=[gmail.send,gmail.compose]
granted_scopes=[gmail.readonly,gmail.send]

Expected result:

Validation:
PASS with minor warnings

Recommended severity:
P2

Domain:
Identity / OAuth / Google

Most likely cause:
OAuth scope mismatch

Evidence:
gmail.compose required but not granted

Route:
identity-integrations

Recommendations:
- investigate whether toolkit upgrade changed required scopes
- request/recommend reauthorization where appropriate
- create internal investigation ticket
- notify support engineering

Do NOT:
- blame Okta certificate rotation
- blame Salesforce HTTP 429
- claim Arcade lost tokens
- page infrastructure

This scenario must have an automated test.

CLI Demo

Create a simple CLI so the project can be demonstrated without an MCP client.

Example:

uv run support-demo data/hero_ticket.json

Output should be easy to read.

Suggested format:

SUPPORT AUTOMATION DEMO

Ticket
------
Acme Financial
Gmail.SendEmail failures
Impact: ~33% users

VALIDATION
----------
Completeness: 94%
Automation Ready: YES

SIGNALS
-------
OAuth scope mismatch
Missing: gmail.compose

SEVERITY
--------
Customer: P1
Recommended: P2

ROUTING
-------
Queue: identity-integrations
Owner: support-engineering

RECOMMENDED ACTIONS
-------------------
✓ Create investigation
✓ Notify support engineering
△ Request customer reauthorization

REJECTED ACTIONS
----------------
✗ Page infrastructure
  No infrastructure evidence

✗ Attribute Salesforce 429s
  No evidence connecting the events

This CLI is important because the demo should not fail if a third-party integration is unavailable.

Observability

Every processing step should produce structured logging.

Include:

ticket_id
tool
duration_ms
result
matched_rule
confidence
human_review_required

Do not build a telemetry platform.

Structured JSON logging is enough.

Tests

Testing is a first-class requirement.

At minimum test:

Validation

missing fields detected

completeness score behaves consistently

unsupported severity warning generated

Routing

Google OAuth issues route correctly

Kubernetes issues route correctly

429 issues route correctly

unknown issues fall back to triage

Safety

low confidence requires human review

customer claims do not become facts

unrelated recent changes do not become root causes

Hero scenario

The Acme ticket MUST:

detect gmail.compose mismatch

classify OAuth

recommend P2

route to identity-integrations

reject infrastructure paging

Tests must be deterministic.

README

Create a polished but concise README.

It should explain:

Problem

Support teams receive incomplete, noisy tickets containing facts, guesses and irrelevant recent events.

Solution

A composable MCP-based support automation layer that validates, enriches and routes tickets according to deterministic policy while using AI only where appropriate.

Architecture

Include the ASCII architecture diagram.

Demo

Show:

uv sync
uv run pytest
uv run support-demo data/hero_ticket.json

MCP

Explain how to launch the MCP server.

Arcade

Explain how Arcade can expose the custom support tools alongside operational tools such as Slack and Linear.

Safety Model

Explain:

AI reasons.
Policy decides.
Humans retain control of high-risk actions.

Engineering Quality

Code should be:

typed

readable

modular

documented where needed

easily explainable during an interview

Avoid clever abstractions.

Prefer explicit code over framework magic.

Use Pydantic models at important boundaries.

Use enums instead of uncontrolled strings where appropriate.

Run:

uv run pytest
uv run ruff check .

before considering any phase complete.

Git Hygiene

Create logical commits.

Suggested commits:

feat: scaffold support automation MCP server

feat: add ticket models and mock generator

feat: implement deterministic ticket validator

feat: add enrichment and evidence extraction

feat: implement policy-driven routing

feat: add severity and action recommendations

feat: add hero support scenario

test: add support automation scenario coverage

docs: add architecture and demo guide

feat: integrate support tools with Arcade gateway

Never commit:

.env

credentials

access tokens

API keys

Scope Control

THIS IS IMPORTANT.

Do not build:

authentication system

user management

database

web frontend

ticket management UI

billing

multi-tenancy

Kubernetes deployment

production infrastructure

complex agent framework

vector database

RAG system

unless explicitly requested later.

This project proves automation capability.

It does not need to become Zendesk.

Implementation Phases

Phase 1 — Core deterministic system

Build:

repository

models

mock ticket generator

validator

enrichment

severity

YAML routing

recommended actions

sample tickets

hero scenario

tests

CLI

Do not integrate external services yet.

At the end of Phase 1:

uv run pytest

must pass.

And:

uv run support-demo data/hero_ticket.json

must produce the full demo.

Phase 2 — MCP

Expose:

generate_ticket
validate_ticket
enrich_ticket
route_ticket
recommend_actions

as MCP tools using Arcade's MCP framework.

Verify tool discovery and invocation locally.

Do not alter business logic to accommodate MCP.

MCP tools should be thin wrappers around tested services.

Phase 3 — Arcade

Connect the support automation server to Arcade.

Add selected operational tools such as:

Slack

Linear

Demonstrate:

ticket
→ validation
→ enrichment
→ routing
→ recommendation
→ Linear issue
→ Slack notification

Do not automatically send customer-facing communication.

Phase 4 — Demo polish

Create:

DEMO.md

containing a 5-10 minute demonstration script.

The script should show:

badly formed ticket

validator catching missing information

hero Gmail ticket

evidence extraction

routing

rejected incorrect hypotheses

recommended automation

Arcade external action

explanation of policy boundaries

Definition of Done

The project is complete when a reviewer can see:

A real MCP server was implemented.

Support tickets can be generated automatically.

Ticket quality is validated in code.

Technical signals are extracted.

Severity is independently assessed.

Routing is controlled by editable policy.

Decisions contain evidence.

Unsupported hypotheses are rejected.

High-risk actions require human intervention.

Arcade can connect support reasoning to operational tools.

Tests prove the important behaviors.

The complete system can be demonstrated in under ten minutes.

Final Product Message

The architecture should communicate this principle:

Automate the repetitive parts of support without automating away judgment.

And technically:

LLMs interpret.
Deterministic policy governs.
MCP exposes capabilities.
Arcade connects those capabilities to real systems.
Humans retain control where risk demands it.

Instructions to Claude Code

When implementing this project:

Read this entire file before coding.

Begin with Phase 1.

Do not expand scope.

Make sensible engineering decisions without asking unnecessary questions.

Run tests frequently.

Fix failures before progressing.

Keep business logic separate from MCP wrappers.

Prefer deterministic implementations where possible.

Keep the project runnable without third-party credentials.

Do not begin Phase 2 until Phase 1 tests and CLI demo work.

At the end of each phase, summarize:

what was implemented

commands to run it

test results

important design decisions

next phase

