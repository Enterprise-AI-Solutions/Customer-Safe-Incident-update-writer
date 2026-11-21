# Security Checklist v2.3.5

- [ ] Shared-state HTTP response handlers restore original context and verify business fields.
- [ ] Every shared job PATCH has a job ID and trusted tenant ID and sends the tenant header.
- [ ] Created job ID and tenant ID match the validated request before returning HTTP 202.
- [ ] Execution ID, job ID, and tenant ID mapping is persisted and verified before incident retrieval.
- [ ] Error mapping execution, job, and tenant fields are verified before the failure PATCH.
- [ ] Tenant is supplied by a trusted gateway and client mapping is enforced.
- [ ] Job-status reads verify requested job ID and authenticated tenant; responses are no-store.
- [ ] Incident context is validated before Claude drafting.
- [ ] Draft, incident, and approval data are present before the ServiceNow update.
- [ ] Approval is not marked successful until the ServiceNow update is verified.
- [ ] HubSpot failure preserves ServiceNow success; missing contact reports HubSpot skipped.
- [ ] Static demo mode is isolated and not used in production.
- [ ] Execution and error data retention remain minimized.
