# Sample form builder / Editor de formularios de muestras

## English

As an administrator/director, open **Admin Settings → Lab Configuration · Sample forms**.
Create a type code (for example `DNA`) and English/Spanish names. Add text, number,
date or yes/no fields, bilingual labels, optional units and required flags. Use Move up/down
to order fields. Save the draft, try its preview, then publish the saved version.

In **Samples → Create Sample**, choose/type that code. Its published fields appear and
are validated on the server. Values and a schema snapshot are stored on the sample;
the sample detail page displays them. The REST API exposes `form_values` for updates
under existing sample permissions, while `form_schema` is read-only to API clients.

Published definitions cannot be edited or deleted through the API. Copy to a new draft
to revise them. The published record with the highest revision ID for a code is active.
Archiving that revision blocks new intake for that code; it does not revive older definitions.
Previously created samples keep their fields and values. Existing unconfigured samples
are not retroactively required to fill out new fields. Existing FieldDefinition/FieldValue
records remain separate and unchanged. Configuration actions appear in Events.

This initial editor uses move buttons, not drag-and-drop. It does not yet provide sections,
conditional fields, defaults, calculated fields, numeric bounds, workflows or an extension
system. It does not execute user-supplied code. The preview is an input/layout preview;
actual value validation runs during sample intake. Form values are currently displayed
read-only on the detail page; authorized API updates are supported and audited.

Ordinary ORM creation (including existing imports) also enforces published required fields;
import paths that do not map `form_values` must be extended before using configured types.
Do not use bulk SQL writes to bypass validation. CSV export/migration adapters for these
new values remain future work. Configure a test type before enabling required forms for
an established intake workflow. Existing unconfigured type codes remain supported.

Validation: focused API/model tests using a SQLite schema-sync harness, frontend production
build, new-component lint, and migration drift check. Full PostgreSQL migrations and browser
end-to-end validation are still required before deployment. No live deployment was performed.

## Español

Como administrador/director, abra **Admin Settings → Configuración del laboratorio ·
Formularios de muestras**. Cree un código (por ejemplo `DNA`) y nombres en ambos idiomas.
Agregue campos de texto, número, fecha o sí/no; defina etiquetas, unidades y campos
obligatorios. Ordénelos con Subir/Bajar, guarde el borrador, revise la vista previa y publique.

En **Samples → Create Sample**, seleccione/escriba el código. El servidor valida los datos
y guarda una copia de la definición con cada muestra. Las muestras anteriores conservan
su versión. Para modificar una definición publicada, copie a un borrador nuevo. Archivar
la versión publicada más reciente bloquea nuevas muestras de ese tipo, sin borrar datos
ni reactivar versiones antiguas. Las acciones de configuración quedan en Events.

La versión inicial no incluye arrastrar y soltar, secciones, condiciones, valores por defecto,
cálculos, límites numéricos ni flujos de trabajo. La vista previa muestra los controles;
la validación de valores se realiza al crear la muestra. Los datos se muestran en la página
de detalle y pueden actualizarse mediante la API autorizada. Los campos personalizados
anteriores se conservan por separado. Las importaciones que no admitan `form_values`
deben adaptarse antes de exigir estos campos. Las exportaciones CSV también quedan pendientes.

Las pruebas de PostgreSQL y del navegador siguen pendientes. No se ha desplegado en producción.
