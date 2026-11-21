# Changelog v2.3.5

## v2.3.5

- Added a request-validity gate so invalid requests return the existing rejection response without creating shared jobs.
- Preserved duplicate and tenant rate-limit responses, including top-level request IDs for caller responses.
- Enabled full HTTP responses on ServiceNow approval and HubSpot note/association writes so downstream nodes can inspect status codes.
- Updated ServiceNow and HubSpot note verifiers to unwrap response bodies while preserving request context.
- Added regression tests for invalid and valid request routing, duplicate handling, write outcomes, and context preservation.
- Updated release documentation and the shared-state OpenAPI package version.

This release implements review findings 1 and 2 only. Other previously identified review items remain outside this release. No live integration or production-readiness claim is made.

## v2.3.4


- Restored request, incident, draft, and approval context after shared-state HTTP transitions.
- Validated shared API job, tenant, status, and execution-mapping response fields.
- Verified job creation before returning HTTP 202; verified execution mapping before incident retrieval.
- Added tenant verification and tenant-scoped failure updates to the error workflow.
- Added portable validation and HTTP response-only context-preservation tests.
- Updated the shared-state OpenAPI response contracts.
- Live integration tests remain unexecuted.
