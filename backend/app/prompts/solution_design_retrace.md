---
version: 1
---
(User-message template only; the system prompt is solution_design.md.)
=== USER ===
{{original_user}}

---
TRACEABILITY CHECK FAILED. Your previous design did not address these mandatory TECHNICAL
requirements in requirement_traceability:
{{missing_json}}

Previous design:
{{previous_json}}

Return the complete, updated solution design. requirement_traceability must contain every
req_code listed above. If the company has no evidence for a requirement, still state how it is
addressed and add it to capability_gaps.
