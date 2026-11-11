# v0.77.0: Form feedback and action guidance

## Forms

The following forms now retain controlled input on failure, highlight invalid fields, describe expected input and focus the first error after submission:

- Sample registration, dynamic sample measurements and measurement-change reasons.
- Sample status/type changes, work creation and attachment uploads.
- User creation with invitation/manual-password modes, and project creation.
- Location/container creation and scan-based inventory transactions.
- Notebook/experiment creation and notebook workflow dialogs.
- Pipeline step measurement forms.

A summary links to the affected controls. Native required, email, URL, length, numeric range and increment checks run before sending a request. The server remains the authority for uniqueness, scientific validation, passwords, permissions and state transitions. Numeric zero and explicit boolean false count as provided values. Unknown field errors remain in the summary rather than disappearing. Non-field errors appear in the form summary. Separate forms keep separate error state; a late response does not steal focus from another form where the user is working.

Each converted form disables its fields while submitting and guards repeated submit events. Failure does not clear the user's values. Only a confirmed save runs the existing success/reset behavior. General network failures advise checking whether the record was saved before retrying. There is no new automatic mutation retry. Existing authenticated-session refresh behavior is unchanged.

The shared API helpers now expose `ApiError.status`, `fieldErrors` and `generalErrors`. Nested DRF errors map to control paths such as `form_values.concentration` or `values.temperature`. Legacy forms also receive a readable message instead of serialized HTTP/JSON text. Raw-response helpers used for previews, confirmation receipts and conflict handling keep their current contracts. HTML/traceback bodies from server errors are not reflected into the UI. Error messages are rendered as text, never HTML.

This release covers the forms listed above; other module-specific editors retain their existing validation interfaces. It does not add persistent storage for passwords or registration form drafts.

## Unavailable actions

Information disclosures explain disabled notebook Save, Complete, Approve, Request changes, Lock, Clone and Use template controls, and bulk sample apply/archive prerequisites. They work with keyboard and touch, and do not rely on hover. Read-only samples/work and role-restricted sample/inventory/work pages show the reason and a relevant next step.

Notebook guidance uses the server's current notebook write/review/lock permissions, immutable record state and unfinished workflow steps. Explicit notebook editor access remains sufficient even without a global editing role. A project membership alone does not necessarily grant notebook editing. Reviewing a recovery copy remains required before editing a recovered experiment.

The API adds these **read-only** serializer fields:

| Resource | Field | Matches |
| --- | --- | --- |
| Sample | `modification_access` | Existing `can_modify` decision |
| Work item | `update_access` | Existing `can_update` decision |

Example response fragment for a visible but uneditable sample:

```json
{
  "can_modify": false,
  "modification_access": {
    "allowed": false,
    "reason_code": "EDIT_ROLE_REQUIRED",
    "reason": "Editing samples requires a technician or administrator role.",
    "next_step": "Request the appropriate role or ask an administrator.",
    "href": "/access-requests"
  }
}
```

Other reason codes distinguish primary-project membership from ownership of a sample without a primary project, and public sample readability from permission to change its work. Explanations do not disclose inaccessible project names. Allowed actions return `allowed: true` with empty guidance. Links are limited to existing profile, project and access-request pages. Notebook access requests go to the owner, not the role request workflow.

All reads and mutations continue using existing server authorization. Submitting fabricated capability metadata cannot grant access. Explanations do not write audit events, change memberships, create revisions or retry operations. Role/membership changes are reflected on the next request; stale pages may still encounter a server rejection and can review access from the error summary.

## Deployment and verification

Version source and generated footer: **0.77.0**. No database migration or new dependency. Rebuild/recreate API, worker and web from the same revision; keep the existing assistant monitor. Both READMEs retain only the latest three release sections: 0.77.0, 0.76.0 and 0.75.0. Older guides remain available in `docs/`.

Regression coverage includes PostgreSQL authorization parity, forged metadata, inaccessible records, permission changes, bounded list-query counts and no audit writes from guidance; frontend parsing/native constraints and notebook-state decisions; and browser checks for exact error focus, nested measurement errors, retained values, independent forms, password/email errors, permission/network/server failures, duplicate-submit prevention, notebook dialogs, keyboard disclosures and Spanish guidance.
