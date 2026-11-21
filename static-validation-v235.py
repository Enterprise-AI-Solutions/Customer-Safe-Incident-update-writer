from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "customer-safe-incident-update-writer-v2.3.5.json"
ERROR = ROOT / "customer-safe-incident-error-handler-v2.3.5.json"
failures = []


def load_workflow(path):
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"invalid JSON {path.name}: {exc}")
        return {}
    names = {node.get("name") for node in workflow.get("nodes", [])}
    for source, groups in workflow.get("connections", {}).items():
        if source not in names:
            failures.append(f"{path.name}: unknown connection source {source}")
        for branch in groups.get("main", []):
            for edge in branch:
                if edge.get("node") not in names:
                    failures.append(
                        f"{path.name}: unknown connection target {edge.get('node')}"
                    )
    return workflow


main = load_workflow(MAIN)
error = load_workflow(ERROR)
node_executable = shutil.which("node")
if not node_executable:
    failures.append("Node.js is required to validate all Code node syntax")

for path, workflow in ((MAIN, main), (ERROR, error)):
    if not workflow:
        continue
    expected_version = "2.3.5"
    if expected_version not in workflow.get("name", ""):
        failures.append(f"{path.name}: workflow name is not v2.3.5")
    for node in workflow.get("nodes", []):
        code = node.get("parameters", {}).get("jsCode")
        if code and node_executable:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", encoding="utf-8", delete=False
            ) as handle:
                handle.write(code)
                temporary = Path(handle.name)
            try:
                result = subprocess.run(
                    [node_executable, "--check", str(temporary)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode:
                    failures.append(
                        f"{path.name}: JS syntax error at {node['name']}: "
                        f"{result.stderr.strip()}"
                    )
            finally:
                temporary.unlink(missing_ok=True)


def node_map(workflow):
    return {node.get("name"): node for node in workflow.get("nodes", [])}


main_nodes = node_map(main)
error_nodes = node_map(error)

shared_http = {
    name: node
    for name, node in main_nodes.items()
    if node.get("type") == "n8n-nodes-base.httpRequest"
    and "JOB_STATE_API_URL" in str(node.get("parameters", {}).get("url", ""))
}
for name, node in shared_http.items():
    parameters = node.get("parameters", {})
    if (
        parameters.get("method", "").upper() == "PATCH"
        and "/jobs/" in str(parameters.get("url", ""))
    ):
        headers = parameters.get("headerParameters", {}).get("parameters", [])
        if not any(
            item.get("name", "").lower() == "x-authenticated-tenant-id"
            and "$json.tenantId" in item.get("value", "")
            for item in headers
        ):
            failures.append(f"{name}: PATCH/read request lacks tenant header")

expected_successors = {
    "Read Job Status": "Verify Shared Job Status",
    "Persist Execution-to-Job Mapping": "Verify Execution Mapping Response",
    "Create Shared Job": "Verify Shared Job Response",
    "Update Shared Approval State": "Verify Shared Approval",
    "Update Shared Final Success": "Verify Shared Success",
    "Update Shared Partial Success": "Verify Shared Partial",
    "Update Shared Failure": "Verify Shared Failure",
    "Shared Accepted": "Verify Shared Accepted",
    "Shared Processing": "Verify Shared Processing",
    "Shared Awaiting Approval": "Verify Shared Awaiting",
    "Shared Rejected": "Verify Shared Rejected",
    "Shared Expired": "Verify Shared Expired",
    "Shared Failed": "Verify Shared Failed",
    "Shared Partial Success": "Verify Shared Partial Transition",
}
main_connections = main.get("connections", {})

# Request validation must gate the shared-job POST, while preserving the
# existing duplicate response branch after the POST verifier.
validation_successors = [
    edge.get("node")
    for branch in main_connections.get("Validate & Normalize Request", {}).get("main", [])
    for edge in branch
]
if validation_successors != ["Request Valid?"]:
    failures.append("request validation does not route through Request Valid?")
request_gate_successors = main_connections.get("Request Valid?", {}).get("main", [])
if len(request_gate_successors) != 2 or [
    edge.get("node") for edge in request_gate_successors[0]
] != ["Create Shared Job"] or [
    edge.get("node") for edge in request_gate_successors[1]
] != ["Reject Invalid or Duplicate Request"]:
    failures.append("Request Valid? does not gate job creation and invalid rejection")
# Verifiers consume HTTP status codes; n8n HTTP Request v4.2 requires
# fullResponse to expose statusCode and wraps the response payload in body.
for request_name, verifier_name in (
    ("Record Approval in ServiceNow", "Verify ServiceNow Update"),
    ("Create HubSpot Note", "Verify HubSpot Note"),
    ("Associate HubSpot Note to Contact", "Verify HubSpot Association"),
):
    request_parameters = main_nodes.get(request_name, {}).get("parameters", {})
    if request_parameters.get("options", {}).get("response", {}).get("fullResponse") is not True:
        failures.append(f"{request_name}: fullResponse must expose statusCode")
    verifier_code = main_nodes.get(verifier_name, {}).get("parameters", {}).get("jsCode", "")
    if verifier_name != "Verify HubSpot Association" and "response.body||response" not in verifier_code:
        failures.append(f"{verifier_name}: does not support full-response body wrapper")


def reachable(source, target):
    seen = set()
    pending = [source]
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            edge.get("node")
            for branch in main_connections.get(current, {}).get("main", [])
            for edge in branch
        )
    return False


for incident_request in ("Get ServiceNow Incident", "Lookup ServiceNow by Number"):
    if not reachable("Verify Execution Mapping Response", incident_request):
        failures.append(
            f"{incident_request}: incident retrieval is not gated by verified execution mapping"
        )
accepted_incoming = [
    source
    for source, groups in main_connections.items()
    for branch in groups.get("main", [])
    for edge in branch
    if edge.get("node") == "Return Accepted 202"
]
if accepted_incoming != ["Verify Execution Mapping Response"]:
    failures.append("HTTP 202 is not gated exclusively by verified execution mapping")

for request, verifier in expected_successors.items():
    successors = [
        edge.get("node")
        for branch in main_connections.get(request, {}).get("main", [])
        for edge in branch
    ]
    if verifier not in successors:
        failures.append(f"{request}: missing response verifier {verifier}")

other_http_recovery = {
    "Get ServiceNow Incident": ("Validate ServiceNow Response", "Initialize Audit Context"),
    "Get Customer-Facing Comments": ("Validate Customer Comments", "Validate ServiceNow Response"),
    "Get HubSpot Contact": ("Normalize HubSpot Context", "Validate Customer Comments"),
    "Claude — Draft Customer-Safe Update": ("Parse & Validate Claude Draft", "Merge Customer Context"),
    "Record Approval in ServiceNow": ("Verify ServiceNow Update", "Parse Explicit Slack Decision"),
    "Create HubSpot Note": ("Verify HubSpot Note", "Verify ServiceNow Update"),
    "Associate HubSpot Note to Contact": ("Verify HubSpot Association", "Verify HubSpot Note"),
    "Lookup ServiceNow by Number": ("Validate ServiceNow Number Response", "Initialize Audit Context"),
}
covered_http = set(expected_successors) | set(other_http_recovery)
for node in main.get("nodes", []):
    if (
        node.get("type") == "n8n-nodes-base.httpRequest"
        and node.get("name") not in covered_http
    ):
        failures.append(f"{node.get('name')}: no HTTP response/context validation rule")
for request, (verifier, source) in other_http_recovery.items():
    successors = [
        edge.get("node")
        for branch in main_connections.get(request, {}).get("main", [])
        for edge in branch
    ]
    if verifier not in successors:
        failures.append(f"{request}: missing response validator {verifier}")
    code = main_nodes.get(verifier, {}).get("parameters", {}).get("jsCode", "")
    if f"$('{source}')" not in code:
        failures.append(f"{verifier}: does not restore context from {source}")

error_connections = error.get("connections", {})
error_http = {
    node.get("name")
    for node in error.get("nodes", [])
    if node.get("type") == "n8n-nodes-base.httpRequest"
}
if error_http != {
    "Lookup Execution Mapping and Mark Failed",
    "Mark Mapped Job Failed",
}:
    failures.append("error workflow HTTP request inventory changed without validation rules")
for request, verifier in (
    ("Lookup Execution Mapping and Mark Failed", "Verify Error Mapping and Job Update"),
    ("Mark Mapped Job Failed", "Verify Mark Failed Response"),
):
    successors = [
        edge.get("node")
        for branch in error_connections.get(request, {}).get("main", [])
        for edge in branch
    ]
    if verifier not in successors:
        failures.append(f"{request}: missing response verifier {verifier}")

expected_recovery = {
    "Verify Shared Job Response": ("Validate & Normalize Request",),
    "Verify Shared Accepted": ("Verify Shared Job Response",),
    "Verify Shared Processing": ("Initialize Audit Context",),
    "Verify Execution Mapping Response": ("Initialize Audit Context",),
    "Verify Shared Awaiting": ("Set Awaiting Approval",),
    "Verify Shared Approval": ("Parse Explicit Slack Decision",),
    "Verify Shared Success": (
        "Verify HubSpot Association",
        "Finalize — No HubSpot Contact",
    ),
    "Verify Shared Partial": ("Verify HubSpot Note",),
    "Verify Shared Failure": (
        "Initialize Audit Context",
        "Validate ServiceNow Response",
        "Parse Explicit Slack Decision",
    ),
    "Verify Shared Rejected": ("Parse Explicit Slack Decision",),
    "Verify Shared Expired": ("Parse Explicit Slack Decision",),
    "Verify Shared Failed": (
        "Initialize Audit Context",
        "Validate ServiceNow Response",
        "Parse Explicit Slack Decision",
    ),
    "Verify Shared Partial Transition": ("Verify HubSpot Note",),
}
for verifier, sources in expected_recovery.items():
    node = main_nodes.get(verifier)
    if not node:
        failures.append(f"missing context verifier {verifier}")
        continue
    code = node.get("parameters", {}).get("jsCode", "")
    if not all(f"$('{source}')" in code for source in sources):
        failures.append(f"{verifier}: does not restore its expected source context")
    if verifier.startswith("Verify Shared") and verifier != "Verify Shared Job Response":
        for field in ("jobId", "tenantId", "body.success", "body.status"):
            if field not in code:
                failures.append(f"{verifier}: does not validate {field}")
        if "sharedStateVerified:true" not in code:
            failures.append(f"{verifier}: verified context is not marked")

create_code = main_nodes.get("Verify Shared Job Response", {}).get(
    "parameters", {}
).get("jsCode", "")
for field in ("jobId", "tenantId", "body.status", "body.requestId", "statusCode:202"):
    if field not in create_code:
        failures.append(f"job creation verifier: missing check/output {field}")

mapping_code = main_nodes.get("Verify Execution Mapping Response", {}).get(
    "parameters", {}
).get("jsCode", "")
for field in ("executionId", "jobId", "tenantId", "body.success"):
    if field not in mapping_code:
        failures.append(f"execution mapping verifier: missing {field} verification")
for name, node in shared_http.items():
        parameters = node.get("parameters", {})
        if parameters.get("method", "").upper() == "PATCH" and "/jobs/" in str(
            parameters.get("url", "")
        ):
            if "$json.jobId" not in str(parameters.get("url", "")):
                failures.append(f"{name}: PATCH URL does not use a job ID")

claude = main_nodes.get("Claude — Draft Customer-Safe Update", {}).get(
    "parameters", {}
).get("jsonBody", "")
if "$json.incident." not in claude or "$json.customerComments" not in claude:
    failures.append("Claude request is missing validated incident/customer context")
draft_context = main_nodes.get("Merge Customer Context", {}).get(
    "parameters", {}
).get("jsCode", "")
for field in ("incident.sysId", "incident.number", "customerComments", "executionId"):
    if field not in draft_context:
        failures.append(f"draft context guard is missing {field}")
sn_node = main_nodes.get("Record Approval in ServiceNow", {}).get("parameters", {})
sn_update = sn_node.get("jsonBody", "")
if not all(token in sn_update for token in ("$json.approval.", "$json.draft.")) or "$json.incident.sysId" not in sn_node.get("url", ""):
    failures.append("ServiceNow update is missing incident, draft, or approval data")
approval_parser = main_nodes.get("Parse Explicit Slack Decision", {}).get(
    "parameters", {}
).get("jsCode", "")
for field in ("$('Parse & Validate Claude Draft')", "d.incident?.sysId", "d.draft"):
    if field not in approval_parser:
        failures.append(f"approval context guard is missing {field}")

error_mapping = error_nodes.get("Verify Error Mapping and Job Update", {}).get(
    "parameters", {}
).get("jsCode", "")
for field in ("executionId", "mappedExecutionId", "jobId", "tenantId"):
    if field not in error_mapping:
        failures.append(f"error mapping verifier: missing {field} verification")
error_patch = error_nodes.get("Mark Mapped Job Failed", {}).get("parameters", {})
if not any(
    item.get("name", "").lower() == "x-authenticated-tenant-id"
    and "$json.tenantId" in item.get("value", "")
    for item in error_patch.get("headerParameters", {}).get("parameters", [])
):
    failures.append("error job PATCH lacks mapped tenant header")

mapping_request = main_nodes.get("Persist Execution-to-Job Mapping", {}).get(
    "parameters", {}
)
if not any(
    item.get("name", "").lower() == "x-authenticated-tenant-id"
    and "$json.tenantId" in item.get("value", "")
    for item in mapping_request.get("headerParameters", {}).get("parameters", [])
):
    failures.append("execution mapping write lacks authenticated tenant header")

if not failures and node_executable:
    for test_name in (
        "test-context-preservation-v235.py",
        "test-critical-workflow-fixes-v235.py",
    ):
        test = ROOT / test_name
        result = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if result.returncode:
            failures.append(f"{test_name} failed: {result.stdout}{result.stderr}")

print("STATIC_VALIDATION_V235=" + ("PASS" if not failures else "FAIL"))
for failure in failures:
    print("FAIL:", failure)
sys.exit(1 if failures else 0)
