import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "customer-safe-incident-update-writer-v2.3.5.json"
CONTEXT = {
    "requestId": "request-12345678",
    "jobId": "job-123",
    "tenantId": "tenant-acme",
    "claimedClient": "client-acme",
    "idempotencyKey": "idem-key-12345678",
    "incident": {"sysId": "a" * 32, "number": "INC123456"},
    "draft": {"subject": "Update", "summary": "Investigating."},
    "approval": {"outcome": "approval_received", "approved": True},
}
TEST_ENV = {
    "JOB_STATE_TRUSTED_GATEWAY": "true",
    "TENANT_CLIENT_MAP_JSON": '{"client-acme":"tenant-acme"}',
}


def load_workflow():
    return json.loads(MAIN.read_text(encoding="utf-8"))


def run_code(code, sources, response=None, env=None):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for regression simulations")
    runner = (
        "const fs=require('fs');const p=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "const src=p.sources;const lookup=(name)=>({"
        "first:()=>({json:src[name]}),isExecuted:Object.prototype.hasOwnProperty.call(src,name)});"
        "try{const result=Function('$input','$','$env',p.code)("
        "{first:()=>({json:p.response})},lookup,p.env||{});"
        "process.stdout.write(JSON.stringify({ok:true,result}));}"
        "catch(e){process.stdout.write(JSON.stringify({ok:false,error:String(e.message||e)}));}"
    )
    payload = json.dumps({
        "code": code,
        "sources": sources,
        "response": response or {},
        "env": env or {},
    })
    with tempfile.TemporaryDirectory() as temporary:
        payload_path = Path(temporary) / "payload.json"
        runner_path = Path(temporary) / "runner.js"
        payload_path.write_text(payload, encoding="utf-8")
        runner_path.write_text(runner, encoding="utf-8")
        completed = subprocess.run(
            [node, str(runner_path), str(payload_path)],
            capture_output=True, text=True, check=False,
        )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def outgoing(workflow, name, branch=0):
    return [edge["node"] for edge in workflow["connections"][name]["main"][branch]]


def evaluate_accepted_if(gate, accepted):
    condition = gate["parameters"]["conditions"]["conditions"][0]
    expected = condition["rightValue"]
    is_true = accepted is expected
    return 0 if is_true else 1


class CriticalWorkflowRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow()
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}

    def validate(self, body):
        source = {
            "body": body,
            "headers": {
                "x-client-id": "client-acme",
                "x-authenticated-tenant-id": "tenant-acme",
                "x-request-id": "request-12345678",
                "idempotency-key": "idem-key-12345678",
            },
        }
        code = self.nodes["Validate & Normalize Request"]["parameters"]["jsCode"]
        return run_code(code, {}, source, TEST_ENV)["result"][0]["json"]

    def test_invalid_request_is_rejected_without_job_creation(self):
        request = self.validate({"audience": "customer"})
        self.assertFalse(request["accepted"])
        self.assertEqual(request["statusCode"], 400)
        branch = evaluate_accepted_if(self.nodes["Request Valid?"], request["accepted"])
        self.assertEqual(outgoing(self.workflow, "Request Valid?", branch), [
            "Reject Invalid or Duplicate Request"
        ])
        self.assertNotEqual(outgoing(self.workflow, "Request Valid?", branch), ["Create Shared Job"])
        self.assertEqual(
            outgoing(self.workflow, "Validate & Normalize Request"), ["Request Valid?"]
        )

    def test_valid_request_reaches_shared_job_creation(self):
        request = self.validate({
            "incident_id": "a" * 32,
            "audience": "customer",
        })
        self.assertTrue(request["accepted"])
        branch = evaluate_accepted_if(self.nodes["Request Valid?"], request["accepted"])
        self.assertEqual(outgoing(self.workflow, "Request Valid?", branch), ["Create Shared Job"])

    def test_duplicate_idempotency_response_uses_existing_rejection_path(self):
        verifier = self.nodes["Verify Shared Job Response"]["parameters"]["jsCode"]
        result = run_code(verifier, {
            "Validate & Normalize Request": {
                "requestId": CONTEXT["requestId"],
                "idempotencyKey": CONTEXT["idempotencyKey"],
            }
        }, {"statusCode": 409})["result"][0]["json"]
        self.assertFalse(result["accepted"])
        self.assertEqual(result["statusCode"], 409)
        self.assertEqual(result["requestId"], CONTEXT["requestId"])
        branch = evaluate_accepted_if(self.nodes["Shared Job Accepted?"], result["accepted"])
        self.assertEqual(outgoing(self.workflow, "Shared Job Accepted?", branch), [
            "Reject Invalid or Duplicate Request"
        ])
        response_body = self.nodes["Reject Invalid or Duplicate Request"]["parameters"]["responseBody"]
        self.assertIn("$json.requestId", response_body)

    def test_successful_servicenow_update_is_recognized_and_context_restored(self):
        result = run_code(
            self.nodes["Verify ServiceNow Update"]["parameters"]["jsCode"],
            {"Parse Explicit Slack Decision": CONTEXT},
            {"statusCode": 200, "body": {"result": {"sys_id": CONTEXT["incident"]["sysId"]}}},
        )
        self.assertTrue(result["ok"], result.get("error"))
        value = result["result"][0]["json"]
        self.assertTrue(value["servicenowRecorded"])
        self.assertEqual(value["requestId"], CONTEXT["requestId"])
        self.assertEqual(value["incident"], CONTEXT["incident"])

    def test_failed_servicenow_update_is_handled_as_failure(self):
        result = run_code(
            self.nodes["Verify ServiceNow Update"]["parameters"]["jsCode"],
            {"Parse Explicit Slack Decision": CONTEXT},
            {"statusCode": 503, "body": {"error": "unavailable"}},
        )
        self.assertFalse(result["ok"])
        self.assertIn("SERVICENOW_UPDATE_FAILED: HTTP 503", result["error"])

    def test_successful_hubspot_note_is_recognized_and_context_restored(self):
        result = run_code(
            self.nodes["Verify HubSpot Note"]["parameters"]["jsCode"],
            {"Verify ServiceNow Update": CONTEXT},
            {"statusCode": 201, "body": {"id": "note-789"}},
        )
        self.assertTrue(result["ok"])
        value = result["result"][0]["json"]
        self.assertEqual(value["noteId"], "note-789")
        self.assertEqual(value["requestId"], CONTEXT["requestId"])
        self.assertEqual(value["tenantId"], CONTEXT["tenantId"])

    def test_failed_hubspot_response_is_handled_as_failure(self):
        result = run_code(
            self.nodes["Verify HubSpot Note"]["parameters"]["jsCode"],
            {"Verify ServiceNow Update": CONTEXT},
            {"statusCode": 502, "body": {"message": "upstream failure"}},
        )
        self.assertTrue(result["ok"])
        value = result["result"][0]["json"]
        self.assertFalse(value["hubspotRecorded"])
        self.assertEqual(value["hubspotFailure"], "HTTP 502")
        self.assertEqual(value["requestId"], CONTEXT["requestId"])

    def test_hubspot_association_success_and_failure_use_full_response_status(self):
        code = self.nodes["Verify HubSpot Association"]["parameters"]["jsCode"]
        success = run_code(
            code,
            {"Verify HubSpot Note": {**CONTEXT, "noteId": "note-789"}},
            {"statusCode": 204, "body": ""},
        )
        self.assertTrue(success["ok"])
        self.assertTrue(success["result"][0]["json"]["hubspotRecorded"])

        failure = run_code(
            code,
            {"Verify HubSpot Note": {**CONTEXT, "noteId": "note-789"}},
            {"statusCode": 503, "body": {"message": "unavailable"}},
        )
        self.assertTrue(failure["ok"])
        value = failure["result"][0]["json"]
        self.assertFalse(value["hubspotRecorded"])
        self.assertEqual(value["hubspotFailure"], "HTTP 503")

    def test_write_requests_enable_full_response_for_status_verification(self):
        for name in (
            "Record Approval in ServiceNow",
            "Create HubSpot Note",
            "Associate HubSpot Note to Contact",
        ):
            with self.subTest(node=name):
                self.assertTrue(
                    self.nodes[name]["parameters"]["options"]["response"]["fullResponse"]
                )

    def test_approved_customer_message_is_published_to_servicenow_and_hubspot(self):
        servicenow_body = self.nodes["Record Approval in ServiceNow"]["parameters"]["jsonBody"]
        hubspot_body = self.nodes["Create HubSpot Note"]["parameters"]["jsonBody"]
        self.assertIn("$json.draft.customer_message", servicenow_body)
        self.assertIn("$json.draft.customer_message", hubspot_body)

    def test_hubspot_association_uses_supported_v3_route(self):
        url = self.nodes["Associate HubSpot Note to Contact"]["parameters"]["url"]
        self.assertIn("/crm/v3/objects/notes/", url)
        self.assertIn("/associations/contacts/", url)
        self.assertNotIn("2026-09", url)

    def test_partial_success_transition_uses_partial_status(self):
        body = self.nodes["Update Shared Partial Success"]["parameters"]["jsonBody"]
        verifier = self.nodes["Verify Shared Partial"]["parameters"]["jsCode"]
        self.assertIn("status:'partial_success'", body)
        self.assertIn("String(body.status||'')!==String('partial_success')", verifier)


if __name__ == "__main__":
    unittest.main(verbosity=2)
