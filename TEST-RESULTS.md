# Test Results v2.3.5

## Executed locally

- `python static-validation-v235.py` — PASS (both workflow JSON exports, connection targets, all Code node JavaScript, and both local test suites).
- `python test-context-preservation-v235.py` — PASS (5 tests covering shared-state response-only context restoration and error-handler mapping).
- `python test-critical-workflow-fixes-v235.py` — PASS (12 tests covering invalid/valid request routing, duplicate responses, ServiceNow and HubSpot success/failure responses, customer-message publication, HubSpot routing, partial success, and context preservation).
- OpenAPI YAML parse and v2.3.5 version check — PASS.
- Workflow JSON parse and connection-target checks — PASS for main and error workflows.

No live n8n, shared-state API, Slack, ServiceNow, or HubSpot test was executed. These results do not establish successful live integration or production readiness.
