from pathlib import Path


def test_local_api_dashboard_threat_model_documents_security_boundaries():
    doc = Path("docs/security/local-api-dashboard-threat-model.md")

    text = doc.read_text(encoding="utf-8")

    required_phrases = [
        "localhost-only",
        "disabled by default",
        "read-only route allowlist",
        "GET /health",
        "GET /doctor",
        "GET /agents",
        "non-GET methods are blocked",
        "CORS",
        "path redaction",
        "error envelope",
        "log redaction",
        "no write operations",
        "no secrets",
        "Dashboard UI is not implemented",
        "HTTP server is not implemented",
        "Runtime Auto-Load remains alpha",
        "target agents do not natively consume LoadPlan",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_local_api_dashboard_threat_model_has_actionable_acceptance_criteria():
    doc = Path("docs/security/local-api-dashboard-threat-model.md")

    text = doc.read_text(encoding="utf-8")

    acceptance_items = [
        "Bind address must default to 127.0.0.1",
        "Remote bind requires an explicit authenticated design review",
        "Only GET /health, GET /doctor, and GET /agents are allowed initially",
        "Every response must use agentmesh.local-api-response/v1",
        "Dashboard must consume the same read-only contract handler",
        "No endpoint may call apply, sync apply, install, delete, or mutate registry state",
    ]
    for item in acceptance_items:
        assert item in text
