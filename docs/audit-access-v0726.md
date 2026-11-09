# Project and object access on Audit Events

Previously the audit feed protected other users' assistant actions, but ordinary sample, result, workflow and project events were returned without checking their project. This also exposed private entries through direct event URLs, search and summary counts.

In v0.72.6, **Audit Events** evaluates access in the backend before pagination or filtering. The same queryset serves list, detail and summary requests, including both `/api/events/` and `/api/v1/events/` routes.

## Access rules

| Reader or record | Behavior |
| --- | --- |
| Application admin or Django superuser | Retains the full stored audit log, including historical, deleted and unrecognized targets. |
| Technician or viewer | Sees events only when the actual target is currently readable through its object/project policy. Being the event's actor does not grant access. |
| Samples, work items, results and pipeline runs | Uses existing sample access, including linked projects and technicians' own unassigned samples. |
| Projects, sequences, batches and job records | Requires current project access; supported unassigned job/sequence ownership follows the technician owner rule. Database-source migration jobs remain admin-only. |
| Notebooks, experiments, templates and registry records | Keeps private, explicit collaborator, team and institution visibility rules. Disabled optional modules do not expose their events to non-admin readers. |
| SOPs | Non-admin readers require an approved, current, effective document and its project/group access. |
| Assistant actions and subscriptions | Requires native ownership/recipient access; assistant-action payloads retain their actor/admin privacy boundary. |
| Shared inventory locations/items and supported global configuration | Can be read when the corresponding current record is readable and its payload contains no inaccessible project context. |
| Deleted, administrative, unsupported or unresolvable targets | Admin-only because current access cannot be established safely. A project ID in the payload cannot grant access. |
| CSV and JSON exports | Remain admin-only. |

Membership or explicit-sharing revocation takes effect on the next request. A denied direct event URL returns **404**, and inaccessible events contribute no counts, action names or entity types to summaries. Search/actor/action filters cannot widen the authorized set.

User/settings administration, print-template, migration-profile and generated-report-artifact audit entries remain admin-only because they do not yet have a safe audit scope in this policy. Generating and downloading an otherwise authorized report keeps its existing behavior.

## Historical and related data

Legacy numeric IDs, public UUIDs, model class names and shared snake_case entity names remain supported. Access uses the actual database object; payload project/sample IDs cannot override it.

Common audit snapshots can contain a former project or a private linked target. Explicit project references in the event and its before/after/details snapshots must be currently accessible. Common entity and linked-target references are also checked through their own object policies. Therefore an event may be hidden even when its current sample is visible, if its payload contains another project's private context. Linked-project sample access does not grant access to unrelated private project snapshots.

Stored audit records are neither deleted nor rewritten. Administrators retain their complete history. This change scopes Audit Events; it does not change business-record mutation permissions or grant export privileges.

## Verification and deployment

The API regressions cover multiple entity types and roles, detail/search/summary/pagination, revoked membership/sharing, unassigned and linked samples, private notebooks/registry records/SOPs, forged metadata, historical snapshots, common links, disabled modules, unknown/deleted targets and admin-only exports. Query-count checks ensure access is evaluated without fetching each audit row's target separately.

```bash
docker compose -f deploy/docker-compose.yml exec -T api pytest -q events/test_access.py
```

Rebuild/recreate **api** and **web** from the updated checkout, then refresh the browser. The footer version is **0.72.6**. No database migration or new dependency is required.
