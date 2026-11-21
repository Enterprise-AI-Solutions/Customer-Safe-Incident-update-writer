# Contributing

## Before making a change

- Read `README.md`, `SETUP.md`, `SECURITY-CHECKLIST.md`, and the relevant parts of `shared-state-openapi.yaml`.
- Keep workflow behavior, API schemas, simulations, and documentation aligned.
- Never commit credentials, customer incident data, or live execution payloads.
- Keep versioned filenames and release notes consistent when changing the package version.

## Branches and pull requests

Use `main` for reviewed releases, `develop` for integration when the team needs it, and focused `feature/<name>` or `fix/<name>` branches for changes. See `BRANCHING.md`. Open a pull request for review; do not treat local validation as evidence of live integration success.

Pull requests should describe the workflow or contract behavior changed, list affected files, explain security implications, include local validation results, and identify live scenarios that remain untested. Add screenshots only when they clarify an n8n workflow change.

## Validation

Run from the repository root:

```sh
python static-validation-v235.py
```

This runs the structural and contract checks, embedded JavaScript syntax checks, and the two local simulation suites. GitHub Actions runs the same command on pushes and pull requests to `main` and `develop`. Live n8n and connected-service tests require a configured sandbox and must be reported separately in `TEST-RESULTS.md`.

## Export hygiene

Export workflows from a compatible n8n version, inspect the JSON diff, remove instance-specific secrets and identifiers, and preserve descriptive node names. Do not hand-edit connection structures without running validation. Update the OpenAPI contract and setup notes when shared-state fields or response behavior change.
