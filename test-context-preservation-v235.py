import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "customer-safe-incident-update-writer-v2.3.5.json"
ERROR = ROOT / "customer-safe-incident-error-handler-v2.3.5.json"
CONTEXT = {
    "requestId": "request-12345678",
    "jobId": "job-123",
    "tenantId": "tenant-acme",
    "claimedClient": "client-acme",
    "incidentId": "0123456789abcdef0123456789abcdef",
    "incidentNumber": "INC123456",
    "hubspotId": "4567",
    "executionId": "98765",
    "incident": {
        "sysId": "0123456789abcdef0123456789abcdef",
        "number": "INC123456",
        "shortDescription": "Service disruption",
        "description": "Intermittent issue",
        "impact": "2",
        "urgency": "2",
        "state": "In Progress",
    },
    "draft": {"subject": "Service update", "customer_message": "We are investigating."},
    "approval": {
        "outcome": "approval_received",
        "approved": True,
        "respondedAt": "2026-11-19T00:00:00Z",
        "responderId": "U123",
    },
}


def load_nodes(path):
    workflow = json.loads(path.read_text(encoding="utf-8"))
    return {node["name"]: node for node in workflow["nodes"]}


def run_code(code, sources, response):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for the response-only simulation")
    runner = (
        "const fs=require('fs');const p=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "const src=p.sources;const lookup=(name)=>({"
        "first:()=>({json:src[name]}),isExecuted:Object.prototype.hasOwnProperty.call(src,name)});"
        "const result=Function('$input','$','$env',p.code)("
        "{first:()=>({json:p.response})},lookup,{});"
        "process.stdout.write(JSON.stringify(result));"
    )
    payload = json.dumps(
        {"code": code, "sources": sources, "response": response},
        ensure_ascii=False,
    )
    with tempfile.TemporaryDirectory() as temporary:
        payload_path = Path(temporary) / "payload.json"
        runner_path = Path(temporary) / "runner.js"
        payload_path.write_text(payload, encoding="utf-8")
        runner_path.write_text(runner, encoding="utf-8")
        completed = subprocess.run(
            [node, str(runner_path), str(payload_path)],
            capture_output=True,
            text=True,
        )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


class SharedStateContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_nodes = load_nodes(MAIN)
        cls.error_nodes = load_nodes(ERROR)

    def verify_main(self, verifier, source_name, status, expected_status=None):
        original = dict(CONTEXT)
        original["incident"] = dict(CONTEXT["incident"])
        original["draft"] = dict(CONTEXT["draft"])
        original["approval"] = dict(CONTEXT["approval"])
        sources = {source_name: original}
        if verifier == "Verify Shared Success":
            sources = {"Verify HubSpot Association": original}
        elif verifier in ("Verify Shared Failure", "Verify Shared Failed"):
            sources = {
                "Initialize Audit Context": original,
                "Validate ServiceNow Response": original,
                "Parse Explicit Slack Decision": original,
            }
        response_body = {
            "success": True,
            "jobId": CONTEXT["jobId"],
            "tenantId": CONTEXT["tenantId"],
            "status": expected_status or status,
        }
        response = {"statusCode": 200, "body": response_body}
        result = run_code(
            self.main_nodes[verifier]["parameters"]["jsCode"], sources, response
        )[0]["json"]
        for key in (
            "requestId",
            "jobId",
            "tenantId",
            "claimedClient",
            "incidentId",
            "incidentNumber",
            "hubspotId",
            "executionId",
            "incident",
            "draft",
            "approval",
        ):
            self.assertEqual(result.get(key), original[key], f"{verifier} lost {key}")

    def test_create_response_only_restores_validated_request(self):
        request = {key: value for key, value in CONTEXT.items() if key != "jobId"}
        response = {
            "statusCode": 201,
            "body": {
                "jobId": CONTEXT["jobId"],
                "tenantId": CONTEXT["tenantId"],
                "requestId": CONTEXT["requestId"],
                "status": "accepted",
            },
        }
        result = run_code(
            self.main_nodes["Verify Shared Job Response"]["parameters"]["jsCode"],
            {"Validate & Normalize Request": request},
            response,
        )[0]["json"]
        self.assertEqual(result["jobId"], CONTEXT["jobId"])
        self.assertEqual(result["tenantId"], CONTEXT["tenantId"])
        for key in ("requestId", "claimedClient", "incidentId", "incidentNumber", "hubspotId"):
            self.assertEqual(result[key], request[key])

    def test_state_http_responses_without_request_context_preserve_context(self):
        cases = (
            ("Verify Shared Accepted", "Verify Shared Job Response", "accepted"),
            ("Verify Shared Processing", "Initialize Audit Context", "processing"),
            ("Verify Shared Awaiting", "Set Awaiting Approval", "awaiting_approval"),
            ("Verify Shared Approval", "Parse Explicit Slack Decision", "approval_received"),
            ("Verify Shared Success", "Verify HubSpot Association", "approved"),
            ("Verify Shared Partial", "Verify HubSpot Note", "approved"),
            ("Verify Shared Failure", "Initialize Audit Context", "failed"),
            ("Verify Shared Rejected", "Parse Explicit Slack Decision", "rejected"),
            ("Verify Shared Expired", "Parse Explicit Slack Decision", "expired"),
            ("Verify Shared Failed", "Initialize Audit Context", "failed"),
            ("Verify Shared Partial Transition", "Verify HubSpot Note", "partial_success"),
        )
        for verifier, source, status in cases:
            with self.subTest(verifier=verifier):
                self.verify_main(verifier, source, status)

    def test_mapping_response_only_preserves_context_and_checks_execution(self):
        response = {
            "statusCode": 201,
            "body": {
                "success": True,
                "executionId": CONTEXT["executionId"],
                "jobId": CONTEXT["jobId"],
                "tenantId": CONTEXT["tenantId"],
            },
        }
        result = run_code(
            self.main_nodes["Verify Execution Mapping Response"]["parameters"]["jsCode"],
            {"Initialize Audit Context": CONTEXT},
            response,
        )[0]["json"]
        self.assertTrue(result["mappingPersisted"])
        for key in CONTEXT:
            self.assertEqual(result[key], CONTEXT[key])

    def test_error_mapping_uses_response_only_fields_and_keeps_tenant(self):
        response = {
            "statusCode": 200,
            "body": {
                "executionId": CONTEXT["executionId"],
                "jobId": CONTEXT["jobId"],
                "tenantId": CONTEXT["tenantId"],
            },
        }
        result = run_code(
            self.error_nodes["Verify Error Mapping and Job Update"]["parameters"]["jsCode"],
            {"Sanitize Error Details": {"executionId": CONTEXT["executionId"]}},
            response,
        )[0]["json"]
        self.assertTrue(result["mappingFound"])
        self.assertEqual(result["jobId"], CONTEXT["jobId"])
        self.assertEqual(result["tenantId"], CONTEXT["tenantId"])

    def test_error_patch_response_is_checked_against_mapping(self):
        response = {
            "statusCode": 200,
            "body": {
                "success": True,
                "jobId": CONTEXT["jobId"],
                "tenantId": CONTEXT["tenantId"],
                "status": "failed",
            },
        }
        result = run_code(
            self.error_nodes["Verify Mark Failed Response"]["parameters"]["jsCode"],
            {
                "Verify Error Mapping and Job Update": {
                    "mappingFound": True,
                    "executionId": CONTEXT["executionId"],
                    "jobId": CONTEXT["jobId"],
                    "tenantId": CONTEXT["tenantId"],
                }
            },
            response,
        )[0]["json"]
        self.assertEqual(result["tenantId"], CONTEXT["tenantId"])
        self.assertEqual(result["jobId"], CONTEXT["jobId"])
        self.assertFalse(result["operatorNotice"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
