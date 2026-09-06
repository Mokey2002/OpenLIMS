# Workflow step measurement forms

## Configure and use

1. Create a form in Admin Settings → Lab Configuration and publish it. Use a separate
   code such as `EXTRACTION_MEASUREMENTS` when the form is for workflow steps rather than
   sample intake; matching a sample type code also configures that type's intake form.
2. In Workflow Designer, select a published **Measurement form** for each desired step.
   The selection is an exact published revision, not an automatically updated latest version.
3. Save the workflow and start a new run. Each step snapshots the selected schema when
   the run starts, including blocked steps that will activate later.
4. In the sample's workflow table, choose **Record measurements**, fill the fields, and
   provide a reason of at least ten characters. Save before completing the linked work item.

The backend validates required fields, types, dropdown options, ranges and visibility against
the step's snapshot. Existing analysis-result requirements still apply separately; measurements
are not converted into Result records. Existing QC approval and dependency handling remain in
effect. Saving a form does not complete the step or approve QC.

Only users allowed to modify the sample can save values, and only while the step and its work
item are active. The save checks original values to reject stale edits and records before/after,
reason, work item, retry count and form revision in Events. Completed, failed, cancelled and
awaiting-QC steps cannot be edited through this endpoint. A retry clears values for the new
attempt and includes the previous measurements in the retry audit event; it keeps the snapshot.

Changing or archiving a form does not change existing runs. An archived/unpublished form
cannot be attached or used to start a new run. Workflows without a form and existing runs
receive empty snapshots and continue with their existing rules. No data backfill is performed.

API: `POST /api/pipeline-runs/{run}/steps/{step}/form/` with `values`, `before`, `reason`, and
the current `work_item` ID (to reject submissions from a previous retry attempt).
Run responses include read-only `form_schema`, `form_values`, and `form_errors` on each step.
Only complete, valid submissions can be saved in this initial version; partial draft saving,
automatic instrument-to-step mapping and new rules-engine behavior are not included.

## Validation

New form tests and existing pipeline tests run using an isolated SQLite schema-sync harness.
Production frontend build, targeted lint and migration drift checks also run. PostgreSQL
migration/locking validation and browser end-to-end checks remain required before deployment.

## Español

Publique un formulario en Configuración del laboratorio. Para mediciones de un paso use
un código independiente, por ejemplo `EXTRACTION_MEASUREMENTS`, para no configurar por
accidente la recepción de un tipo de muestra del mismo nombre.

En Workflow Designer seleccione el **Formulario de mediciones** de cada paso. Guarde el
flujo e inicie una ejecución nueva. Cada paso conserva una copia de la versión seleccionada.
En la tabla de flujo de la muestra use **Registrar mediciones**, complete los campos y añada
un motivo de al menos diez caracteres. Guarde antes de finalizar el trabajo asociado.

Los valores obligatorios y las validaciones se verifican en el servidor. Se mantienen los
requisitos de resultados, las dependencias y la aprobación de QC. Guardar no finaliza el paso.
Solo pueden editar usuarios autorizados mientras el paso y su trabajo están activos. Las
ediciones desactualizadas se rechazan; los cambios quedan registrados en Events.

Un reintento borra los valores del intento nuevo, conserva los anteriores en la auditoría y
mantiene la versión del formulario. Archivar o cambiar una definición no modifica ejecuciones
existentes. Los borradores y formularios archivados no pueden iniciar ejecuciones nuevas.
No se incluyen guardado parcial, importación automática de mediciones ni reglas adicionales.
Faltan pruebas completas con PostgreSQL y navegador antes de desplegar.
