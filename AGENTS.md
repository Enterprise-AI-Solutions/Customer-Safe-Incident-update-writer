# Repository Guidelines

## Project Structure & Module Organization

This repository packages two n8n workflow exports: `customer-safe-incident-update-writer-v2.3.5.json` is the main customer update flow, and `customer-safe-incident-error-handler-v2.3.5.json` handles failures. `shared-state-openapi.yaml` defines the shared-state API contract. The root also contains setup, security, test-plan, test-results, and changelog documentation, plus a demo payload. There is no separate source or assets directory; workflow logic lives in the exported JSON, including embedded Code node JavaScript.

## Build, Test, and Development Commands

No build step is defined. Run checks from the repository root:

- `python static-validation-v235.py` validates workflow JSON, connections, embedded JavaScript syntax, and context/API contracts; it also runs the response-only simulations.
- `python test-context-preservation-v235.py` runs context-preservation simulations; `python test-critical-workflow-fixes-v235.py` runs release regression cases.

Node.js must be installed for embedded JavaScript checks and simulations. For integration work, import the workflows into a configured n8n sandbox and follow `TEST-PLAN.md`; static validation does not verify live services.

## Coding Style & Naming Conventions

Keep workflow exports valid, consistently formatted JSON and preserve readable, descriptive n8n node names. Use the current version suffix (`v2.3.5`) when updating versioned artifacts. Python helpers use four-space indentation, descriptive `snake_case` names, and standard-library modules. Keep embedded JavaScript compatible with the n8n Code node runtime and retain explicit checks for tenant, job, and execution-mapping identifiers. Update the OpenAPI contract and relevant setup/test documentation when changing shared-state behavior.

## Testing Guidelines

Add regression cases to `test-context-preservation-v235.py` for changed response-verification or context-restoration behavior. Keep structural and contract assertions in `static-validation-v235.py`. Run both commands after workflow changes. Live test scenarios are listed in `TEST-PLAN.md`; record their actual outcome in `TEST-RESULTS.md` and do not describe unrun scenarios as passing.

## Commit & Pull Request Guidelines

This checkout has no available Git history, so repository-specific commit conventions cannot be confirmed. Use a short imperative commit subject, such as `Validate shared job response`. Pull requests should describe the workflow or contract change, note affected files and security implications, list validation commands and results, and identify any live scenarios that remain untested. Include representative n8n screenshots only when they clarify a workflow change.

## Security & Configuration

Never commit API tokens or customer incident data. Use the trusted gateway and tenant mapping configuration described in `SETUP.md`; do not trust a caller-supplied tenant header. Treat the local demo mode as single-instance only, not suitable for production or concurrent workers.
