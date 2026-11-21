# Test Plan v2.3.5

## Static

From the package root or an extracted ZIP directory, run:

```text
python static-validation-v235.py
```

The validator checks both workflow JSON files, connections, every Code node's JavaScript syntax, shared-state response/context contracts, job and tenant fields, mapping order, incident/draft/approval dependencies, and the error-handler mapping. It also runs `test-context-preservation-v235.py` and `test-critical-workflow-fixes-v235.py`. These execute actual Code node verifiers and check that invalid requests cannot create jobs, duplicates keep their rejection path, and ServiceNow/HubSpot write statuses and context are handled correctly.

## Live matrix

- Execution mapping persistence success/failure
- Deliberate n8n execution failure
- Error Trigger execution ID lookup
- Shared job creation and concurrent duplicate requests
- Tenant cross-access
- Gateway true/false/missing
- Approval, rejection, expiration
- ServiceNow success with HubSpot success/failure/skipped
- Status 403/404/500 JSON

All live items remain unexecuted until a configured sandbox is available. Static success does not establish integration or production readiness.
