# Setup v2.3.5

## Import

1. Extract the ZIP package to a directory.
2. Import `customer-safe-incident-error-handler-v2.3.5.json`.
3. Import `customer-safe-incident-update-writer-v2.3.5.json`.
4. Set the main workflow Error Workflow to the imported error-handler workflow ID.

Run `python static-validation-v235.py` from the extracted directory before import. It validates both workflow JSON files, node connections, and all Code node JavaScript, then runs the context-preservation and v2.3.5 regression suites.

## Shared-state environment

```text
JOB_STATE_API_URL=https://shared-state.internal
JOB_STATE_API_TOKEN=<secret>
JOB_STATE_TRUSTED_GATEWAY=true
TENANT_CLIENT_MAP_JSON={"client-acme":"tenant-acme"}
```

Use an API gateway to inject `x-authenticated-tenant-id`. Do not accept it from an untrusted caller. The exact string `true` is required. Follow `shared-state-openapi.yaml`; successful create, patch, mapping, and lookup responses must include the documented business identifiers and state.

## Execution mapping

The accepted path creates the job, verifies the returned job and authenticated tenant, marks it accepted/processing, initializes the execution context, persists and verifies the execution-to-job mapping, then retrieves the incident.

## Error workflow

The Error Trigger execution payload supplies the execution ID. The error workflow looks up and verifies the execution mapping, retrieves tenant/job, and marks the mapped job failed using the mapped tenant header. Missing or mismatched mappings notify the operator rather than guessing a job.

## Demo mode

Local static demo is single-instance only. It is not HA-safe and must not be used for production tenants or concurrent workers.
