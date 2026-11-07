# Audit integrity in v0.72.5

One lab operation could generate repeated entries on **Audit Events** through several paths:

| Trigger | Previous behavior | Corrected behavior |
| --- | --- | --- |
| Start, activate, complete, retry or cancel a workflow; assign an analysis | Services stored matching events for the workflow/work item and the sample. The audit feed displayed both. | One canonical `PipelineRun` or `WorkItem` event links to the sample. |
| Change a sample's container | The general update handler logged `UPDATED`; the PATCH handler then logged `CONTAINER_ASSIGNED`. | The locked update writes one event with before/after values, container codes and location. Combined changes use one `UPDATED` entry. |
| Save an already completed or skipped step while another step is active | The work-item save signal processed its final state again and could repeat completion/skip events and overwrite completion time. | Processing the same final outcome again leaves its audit entry and completion time unchanged. |
| Save a work item with the same missing-measurement or QC failure | Synchronization could write the same blocked event again. | Unchanged failures produce no additional event. Changed failure reasons and new QC outcomes remain recorded. |
| Send the same sample status transition concurrently | Both requests could read the previous status and log the same transition. | A transaction locks and reloads the sample; one request succeeds and the other receives the existing validation error for the now-current status. |
| Audit persistence fails during a status transition | The sample's status could remain changed without its event. | The state change and event roll back together. |

## Reading the events

Workflow events use **PipelineRun**, and analysis assignments use **WorkItem**, in the Audit Events entity filter. The event payload retains the sample and work-item/run identifiers. The sample's **History**, assistant history/investigation timelines and scoped reports follow the canonical event through its related sample.

Sample readers verify the actual workflow/work-item ownership in the database. A payload naming another sample does not grant access or attach that event to its history. Reports continue checking current sample/project access, including access revoked after the action.

Existing audit records are retained. Older workflow events without the new sample relation continue using their existing Sample copies in sample history, avoiding an additional historical duplicate there. This release does not delete, rewrite or conceal old rows on Audit Events. Repeating an action for another entity or starting a genuine retry remains a separate auditable operation.

## Regression checks

The regression suite exercises the audit API, summary and JSON export, sample and assistant history, scoped reports, container updates, genuine retries/QC changes, repeated save signals and rollback when audit persistence fails. The concurrency test uses two requests that both read the old sample state before attempting the transition, on PostgreSQL.

```bash
docker compose -f deploy/docker-compose.yml exec -T api \
  pytest -q events/test_audit_integrity.py samples/tests/test_transition_concurrency.py
```

CI also includes the transition race in the required PostgreSQL concurrency checks.

## Updating Docker deployments

After merging, update the checkout and rebuild/recreate **api**, **worker** and **web** from the same commit. API and worker both execute audited services; web includes the version/footer update. Refresh the browser. No database migration or new dependency is required.
