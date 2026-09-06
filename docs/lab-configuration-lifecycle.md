# Lab configuration: sample lifecycle improvements

This extends the first form builder with:

- Dropdowns with unique options, numeric minimum/maximum, and conditional fields.
- A condition can reference an earlier unconditional yes/no or dropdown field. Hidden
  fields must be empty and are cleared when the controlling value changes in the UI.
  Required validation applies only while visible. The backend enforces the same rules.
- Publication comparison showing added/removed/changed field keys and the number of
  existing samples whose snapshots remain unchanged. The UI sends a review token to
  reject changes made between review and publication. This does not certify compatibility
  with instrument integrations or workflow requirements; administrators must review those.
- Saved template JSON download and upload as a new server-validated draft. Import never
  publishes automatically or replaces existing templates.
- Sample detail editing with a reason of at least ten characters, original-value comparison,
  a locked database update, existing permissions, and before/after audit history.
- Selected-sample CSV export includes `form_values`, `form_schema`, and `form_version`.
- New configured-sample CSV intake in Samples, supporting up to 500 rows / 1 MB per batch.
  Required headers: `sample_id,sample_type,form_values`. Values are JSON inside correctly
  quoted CSV cells. Select the destination project explicitly; that project applies to all rows.
  Preview validates the whole batch and creates nothing. Confirmation revalidates the batch
  and its schema token, then creates everything in a transaction. Existing sample IDs are
  rejected; this endpoint is not an update or restoration operation. A provided form_version
  must match the active form. Exported form_schema is informational, never trusted as input.
  Existing instrument/result import workflows are separate and unchanged.

## Example CSV

```csv
sample_id,sample_type,form_values
DNA-101,DNA,"{""concentration"":12.5}"
```

Create and publish the DNA form with a numeric `concentration` field before importing.
For a restore or historical-version migration use a separate, reviewed migration process;
this import intentionally requires the currently published form for new intake.

## Verification and scope

Focused tests cover typed constraints, conditional required values, stale edit detection,
reasons/audit, export data fidelity, preview tokens, no partial imports, replay rejection,
publication comparison and stale reviews. The local test harness synchronizes SQLite tables
without migrations because existing repository migrations require PostgreSQL. PostgreSQL
migrations/full CI and interactive browser checks remain deployment gates. Frontend build,
component lint and migration drift checks are also run locally.

Future work: conditional sections, defaults, multi-select controls, computed fields,
configuration across other modules, workflow/rules editors, and packaged laboratory setups.

## Español

El editor ahora admite listas desplegables, límites numéricos y campos condicionales.
Una condición usa un campo anterior de sí/no o lista sin condición. Los campos ocultos
se vacían y no son obligatorios. El servidor aplica estas reglas.

Antes de publicar, revise los campos agregados, eliminados o modificados. Las muestras
existentes conservan su versión. Puede exportar una plantilla JSON e importarla como
borrador nuevo, sin publicación automática. Revise las integraciones y los flujos antes
de activar requisitos nuevos.

En el detalle de la muestra, **Editar campos de la muestra** permite corregir valores
con motivo de al menos diez caracteres y registro de auditoría. Las ediciones desactualizadas
se rechazan. Las exportaciones incluyen valores, esquema y versión.

**Importar muestras configuradas** acepta CSV de muestras nuevas (máximo 500 filas / 1 MB)
con columnas `sample_id,sample_type,form_values`. Los valores son JSON entre comillas CSV.
Seleccione el proyecto para todas las filas, valide la vista previa y confirme. No modifica
muestras existentes ni restaura versiones históricas. El lote se crea completo o no se crea.
Los cambios de configuración requieren repetir la vista previa. Las importaciones de
instrumentos permanecen separadas.

Faltan validación completa con PostgreSQL y pruebas interactivas en navegador antes del
despliegue. Los editores de flujos/reglas y la extensión a otros módulos quedan pendientes.
