# Lab configuration / Configuración del laboratorio

Open **Settings → Configure your lab without code**. This hub links the existing
editors and adds an audited sample-status policy. Configuration does not grant
extra permissions: users still need the appropriate administrator, project or
notebook access for each operation.

| Configure | Where | Effect |
| --- | --- | --- |
| Sample fields | Sample fields and forms, below Settings | Build/preview/publish versioned forms; existing samples keep their schema snapshot. |
| Required analysis results and pipelines | Workflow Designer | Configure required fields, procedures and dependencies. |
| Experiment templates | Notebook | Configure ordered steps, fields, responsible people and completion criteria. Existing experiment snapshots remain unchanged. |
| Account roles and invitations | Users | Administrators manage roles and account setup. |
| Project membership | Projects | Authorized project managers manage the team. |
| Notebook access | Notebook sharing | Owners/admins manage readers, editors, commenters, reviewers and lockers. |
| Print templates | Labels / Reports | Configure output using the existing preview/template editors. |
| Manual sample lifecycle | Sample status transitions, in Settings | Administrators enable/disable supported transitions with a reason. |

## Change manual sample transitions

1. Open Settings and review **Sample status transitions**.
2. Uncheck a supported transition your lab does not use, for example
   `RECEIVED → CANCELLED`. Every non-final status must keep at least one destination.
3. Enter a reason of at least 10 characters and select **Save status policy**.
4. Future manual changes—including bulk updates and changes to existing samples—
   use the saved policy. No sample is moved to another status by saving settings.
5. To restore defaults, select **Use default transitions**, review the choices,
   enter a reason and save. This button alone does not change server configuration.

Status codes remain fixed; arbitrary new status codes, backward transitions and
QC-skipping shortcuts are not supported. This policy restricts supported manual
transitions only. Pipeline automation and custody operations such as disposal
retain their existing specialized rules. It does not change QC approval criteria,
result validation, roles, or data visibility. General Settings reset does not reset
the sample-status policy.

If another administrator saves first, your save is rejected with HTTP 409 and
your local edits remain visible. Use **Reload policy**, confirm discarding local
edits, then reapply the intended changes. Every successful save records the actor,
reason and before/after policy in Audit Events (`SAMPLE_STATUS_POLICY_UPDATED`).

## Español

Abre **Ajustes → Configura tu laboratorio sin código**. Desde ahí puedes acceder
a formularios de muestras, campos de análisis, pipelines, plantillas de experimentos,
roles de cuentas, miembros de proyectos y permisos de bitácoras. Cada editor
mantiene sus controles de permisos. No es necesario editar código.

En **Transiciones de estado de muestras**, desmarca una transición admitida,
escribe un motivo de al menos 10 caracteres y guarda. Cada estado no final debe
conservar una salida. La política se aplica a futuros cambios manuales, incluidos
los masivos y los de muestras existentes; guardar no cambia el estado actual de
ninguna muestra. Las acciones automáticas de pipelines y custodia conservan sus
reglas propias. No se permiten códigos nuevos, retrocesos ni saltos de QC.

Para restaurar la política, selecciona **Usar transiciones predeterminadas**, revisa
las opciones, escribe un motivo y guarda. Si otra persona modificó la política,
tus cambios no se sobrescriben automáticamente: recarga y vuelve a aplicarlos.
Cada guardado registra usuario, motivo y valores anteriores/nuevos en auditoría.

## Upgrade

Run migrations before starting the new application version:

```sh
docker compose -f deploy/docker-compose.yml run --rm api python manage.py migrate
```

Migration `settings_app.0007_samplestatuspolicy` adds the policy table. Until a
policy is saved, the existing default lifecycle remains in effect. The policy
endpoint is `/api/v1/sample-status-policy/` (authenticated GET, administrator PATCH).
