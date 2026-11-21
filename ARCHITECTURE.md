# Architecture — Customer-Safe Incident Update Writer (v2.3.5)

## Overview

The **Customer-Safe Incident Update Writer** is an enterprise-grade automated workflow package designed for n8n. It ingests internal incident records (e.g. from ServiceNow), normalizes context, engages Anthropic Claude to synthesize customer-safe, grounded updates, enforces mandatory human-in-the-loop authorization via Slack interactive approvals, and commits verified updates back to ServiceNow and optional customer engagement systems (HubSpot).

All lifecycle transitions, execution-to-job bindings, and audit trails are managed via a tenant-isolated, OpenAPI-specified **Shared-State API**.

```mermaid
flowchart TD
    subgraph External["External Actors & Gateways"]
        Client["Monitoring / API Gateway\n(Authenticated Caller)"]
        Approver["Incident Commander / Lead\n(Slack Interactive Approval)"]
    end

    subgraph Orchestration["n8n Workflow Engine"]
        MainWF["Main Workflow v2.3.5\n(66 Nodes Pipeline)"]
        ErrorWF["Error Handler Workflow v2.3.5\n(8 Nodes Fail-Closed)"]
    end

    subgraph LLM["AI Synthesis"]
        Claude["Anthropic Claude 3.5 Sonnet\n(Grounded Customer-Safe Drafting)"]
    end

    subgraph State["State & Persistence"]
        SharedAPI["Shared-State API\n(Tenant-Scoped Job Lifecycle & Mapping)"]
    end

    subgraph SystemsOfRecord["Enterprise Systems of Record"]
        SNOW["ServiceNow Incident Management\n(Incident Data & Customer Work Notes)"]
        HubSpot["HubSpot CRM (Optional)\n(Contact Association & Engagements)"]
    end

    Client -->|1. POST Incident Request| MainWF
    MainWF -->|2. Validate & Gate| SharedAPI
    MainWF -->|3. Fetch Incident & Comments| SNOW
    MainWF -->|4. Enrich Contact| HubSpot
    MainWF -->|5. Draft Grounded Update| Claude
    Claude -->|6. Validated Draft| MainWF
    MainWF -->|7. Interactive Approval| Approver
    Approver -->|8. Approve / Reject| MainWF
    MainWF -->|9. Post Approved Notes| SNOW
    MainWF -->|10. Create Timeline Note| HubSpot
    MainWF -->|11. Complete Job State| SharedAPI

    MainWF -.->|On Node Failure / Timeout| ErrorWF
    ErrorWF -->|Resolve Execution ID| SharedAPI
    ErrorWF -->|Mark Job Failed & Escalate| Approver
```

---

## Workflow Components

The repository delivers two production-ready workflow exports and a central OpenAPI contract:

1. **Main Workflow (`customer-safe-incident-update-writer-v2.3.5.json` — 66 Nodes)**:
   - Validates incoming payload format, tenant authenticity, and idempotency keys.
   - Enforces the **Request Validity Gate** (`Request Valid?`), safely rejecting invalid or malformed requests with standard rejection payloads without spawning unmapped jobs.
   - Interacts with the **Shared-State API** to provision a tenant-scoped job record and synchronously persists the n8n execution-to-job mapping.
   - Resolves ServiceNow incidents by SysID or Incident Number, retrieving recent work notes and customer-visible comments.
   - Merges verified HubSpot customer context when a contact identifier is supplied.
   - Prompts Claude with strict guidelines to prevent technical data leaks, internal jargon, or unsubstantiated root-cause claims.
   - Publishes an approval request card to Slack with actionable buttons (`Approve`, `Reject`, `Request Changes`).
   - On approval, updates ServiceNow incident work notes with verification checks on HTTP status codes and response bodies (`fullResponse: true`), optionally adds a HubSpot engagement note, and transitions the shared job status to `completed` or `partial_success`.

2. **Error Handler Workflow (`customer-safe-incident-error-handler-v2.3.5.json` — 8 Nodes)**:
   - Activated automatically via the n8n `Workflow Error Trigger` whenever an unhandled failure occurs in the main execution.
   - Uses the native execution ID (`$execution.id`) to query the persistent execution-to-job mapping table in the Shared-State API.
   - Verifies the authenticated tenant matches the stored mapping to prevent cross-tenant data contamination.
   - Transitions the mapped shared job to `failed` with sanitized error details, suppressing internal stack traces and secrets.
   - Sends a controlled alert to the operations Slack channel with execution diagnostics.

3. **Shared-State API Contract (`shared-state-openapi.yaml`)**:
   - Defines strict schemas for tenant isolation (`x-authenticated-tenant-id`), job creation, status queries, execution mapping, and phase transitions.

---

## Detailed Pipeline Execution Sequence

```mermaid
sequenceDiagram
    autonumber
    participant GW as API Gateway / Client
    participant WF as n8n Main Workflow
    participant SS as Shared-State API
    participant SN as ServiceNow
    participant AI as Claude (Anthropic)
    participant SL as Slack (Approver)
    participant HS as HubSpot (Optional)

    GW->>WF: POST /webhook/incident-update
    WF->>WF: Validate & Normalize Request
    alt Invalid Request or Duplicate Key
        WF-->>GW: HTTP 400/409 (Rejection Payload)
    else Request Valid
        WF->>SS: POST /jobs (Create Shared Job)
        SS-->>WF: 201 Created (jobId, tenantId)
        WF->>SS: POST /mappings (Persist Execution Mapping)
        SS-->>WF: 200 OK (Mapped)
        WF-->>GW: HTTP 202 Accepted (jobId, trackingUrl)
        
        Note over WF,SN: Fetch Grounding Context
        WF->>SN: GET /table/incident (Fetch Incident)
        SN-->>WF: 200 OK (Incident Details)
        WF->>SN: GET /table/sys_journal_field (Fetch Comments)
        SN-->>WF: 200 OK (Comments)
        
        opt HubSpot Contact Provided
            WF->>HS: GET /crm/v3/objects/contacts (Fetch Contact)
            HS-->>WF: 200 OK (Contact Context)
        end
        
        Note over WF,AI: LLM Synthesis
        WF->>AI: POST /v1/messages (System prompt + Context)
        AI-->>WF: 200 OK (Customer-Safe Draft)
        WF->>WF: Parse & Validate JSON Draft
        
        Note over WF,SL: Human-in-the-Loop Approval
        WF->>SS: PATCH /jobs/{id} (State: awaiting_approval)
        WF->>SL: Send Interactive Approval Card
        SL-->>WF: Approver Click (Approve / Reject)
        
        alt Decision: Approved
            WF->>SN: POST /table/incident/{id} (Record Work Notes)
            SN-->>WF: 200 OK (fullResponse verified)
            opt HubSpot Verified
                WF->>HS: POST /crm/v3/objects/notes (Create Note)
                HS-->>WF: 201 Created (Verified)
                WF->>HS: PUT /associations (Associate to Contact)
                HS-->>WF: 200 OK (Verified)
            end
            WF->>SS: PATCH /jobs/{id} (State: completed)
            WF->>SL: Post Success Notice
        else Decision: Rejected
            WF->>SS: PATCH /jobs/{id} (State: rejected)
            WF->>SL: Post Rejection Notice
        end
    end
```

---

## Shared-State Job Lifecycle State Machine

The Shared-State API manages jobs through a deterministic finite-state machine. Transitions must follow the permitted paths documented in `shared-state-openapi.yaml`:

```mermaid
stateDiagram-v2
    [*] --> accepted: Client Request Validated
    accepted --> processing: Execution Mapping Persisted
    processing --> awaiting_approval: Draft Generated by Claude
    
    awaiting_approval --> approved: Slack Approver Accepts
    awaiting_approval --> rejected: Slack Approver Rejects
    awaiting_approval --> expired: Approval Timeout Exceeded
    
    approved --> completed: ServiceNow & HubSpot Updated
    approved --> partial_success: ServiceNow Updated, HubSpot Failed
    approved --> failed: ServiceNow Write Failed
    
    processing --> failed: Context Retrieval / Claude Error
    rejected --> [*]
    expired --> [*]
    completed --> [*]
    partial_success --> [*]
    failed --> [*]
```

---

## Trust Boundaries & Hardening in v2.3.5

### 1. Request Validity Gate
In v2.3.5, incoming requests pass through `Validate & Normalize Request` directly to `Request Valid?`.
- Valid requests proceed to `Create Shared Job`.
- Invalid payloads (missing incident IDs, malformed JSON, unauthenticated tenant tokens) are immediately routed to `Reject Invalid or Duplicate Request` without invoking the Shared-State API or creating orphan records.

### 2. Tenant Context & Isolation
All Shared-State API requests require the `x-authenticated-tenant-id` header. The tenant ID is extracted from gateway verification and checked on every downstream response. If an API call returns a mismatched tenant ID, the workflow throws an authorization exception immediately.

### 3. Response Wrapping & Context Preservation (`fullResponse: true`)
n8n HTTP Request nodes configured with `response.fullResponse: true` expose both the HTTP `statusCode` and the payload inside `response.body`. Downstream verifier Code nodes:
- Unwrap `response.body || response` to validate business responses.
- Explicitly restore upstream context (such as `incidentId`, `jobId`, `draftText`, `approverId`) to avoid data drop-off during HTTP transitions.

### 4. Fail-Closed Error Mapping
If any node encounters an unhandled runtime error:
1. `Workflow Error Trigger` receives the failure metadata.
2. `Lookup Execution Mapping and Mark Failed` queries the Shared-State API using only `$execution.id`.
3. If an execution mapping is found and the tenant ID matches, `Mark Mapped Job Failed` updates the job.
4. If no mapping exists (e.g. failure occurred prior to mapping creation), the error handler notifies the operator without guessing an incident or job ID.

---

## Validation and Compliance

The repository includes a static analysis and regression testing engine (`static-validation-v235.py`) ensuring:
- All JSON schema exports are valid and uncorrupted.
- All 66 main workflow connections and 8 error workflow connections link existing nodes.
- All embedded JavaScript in Code nodes compiles without syntax errors via `node --check`.
- Shared-state API calls adhere to OpenAPI specifications.
- Regression test suites (`test-context-preservation-v235.py` and `test-critical-workflow-fixes-v235.py`) pass without errors.
