# Guided lab onboarding / Primeros pasos

## Administrator / lab manager

1. Configure invitation email using [user invitations](user_invitations.md).
   Use the real HTTPS origin, including the port when needed. An invitation
   submitted to SMTP is not a guarantee of delivery; check bounces separately.
2. Create a user under **Users**, supply their email and select **Send invitation
   email so the user can set a password**. No password is sent by email.
   Manual accounts remain supported and receive an in-app welcome notification.
3. The **Account setup** column shows whether a usable password exists and the
   latest recorded invitation/password-setup event. It survives page reloads.
   Failed invitation attempts notify the administrator in-app and can be retried
   with **Send invitation**. Existing passwords are not replaced by sending a link.
4. Enable the notebook module, share an appropriate notebook with the user and
   grant edit access. An account invitation does not automatically grant access
   to projects or notebooks. Project viewers need explicit notebook edit access
   to create experiments; only grant it when appropriate.
5. In that notebook, create an active experiment template with the lab's actual
   ordered workflow steps, required fields, criteria and responsible people.
   No demonstration workflow is created automatically. Assigned users must still
   have active accounts and notebook edit access when the template is used.

## New user

1. Open the invitation email and set your password before the link expires.
   Sign in. Account creation and successful password setup create in-app notifications.
2. Select **Getting started** in the header or **My Work**. Choose an available
   workflow and read the preview of its steps, required fields and completion criteria.
3. Enter a meaningful experiment title and select **Create my first experiment**.
   This creates a real experiment in the selected notebook, an initial revision,
   and workflow steps copied from the template. Existing template assignees are
   preserved, and you are also assigned to the experiment. No step is completed
   or approved automatically.
4. Select **Open experiment**. Add the relevant sample using Links, save a revision,
   attach supporting files and record your measurements. Assign a responsible
   person with notebook edit access to any unassigned step, recording the reason.
   Complete steps in order
   with the required confirmation. Saving values and completing a step are separate.
5. When every step is complete, complete the experiment using its status controls.
   Authorized review and sign-off remain separate actions.
6. Return to **Getting started** to see saved progress. Use **Refresh** after working
   in another tab; returning focus also refreshes progress. Retrying creation returns
   the same first experiment, including when the original response was lost.
   Create subsequent experiments through the notebook's normal template controls.

If no workflows appear, ask the notebook owner for edit access and an active
template containing steps. Disabled notebook modules and unavailable access have
explicit guidance. Revoked notebook access hides the first experiment; it does
not expose titles or progress or delete the experiment. The guide is optional and
does not replace My Work or force a demo on existing users.

## Español

**Responsable:** configura el correo de [invitaciones](user_invitations.md), crea
la cuenta con correo y envía la invitación. La columna **Account setup** conserva
el estado del envío y de la contraseña. Un envío aceptado por SMTP no garantiza
entrega; revisa los rebotes. Si falla, recibirás una notificación interna y podrás
reenviarlo. Comparte una bitácora con permiso de edición y prepara una plantilla
activa con los pasos reales del laboratorio. La invitación no concede permisos
de proyecto o bitácora automáticamente.

**Usuario:** abre el enlace, establece tu contraseña e inicia sesión. En
**Primeros pasos**, elige el flujo, revisa sus campos y criterios, y escribe un
título. Crea el experimento y ábrelo para vincular la muestra, guardar una revisión,
adjuntar archivos y completar los pasos en orden. Guardar resultados no completa
un paso. Al terminar, completa el experimento; la revisión y firma son acciones
separadas. Puedes volver al inicio guiado y actualizar para consultar el progreso.
Los reintentos recuperan el mismo primer experimento. Para los siguientes, usa
las plantillas desde la bitácora.

## Upgrade and validation

Run migrations before starting the new backend/frontend:

```sh
docker compose -f deploy/docker-compose.yml run --rm api python manage.py migrate
```

Migration `notebook.0003_experimentonboarding` stores the per-user experiment
reference. No prior experiments or user permissions are changed. No real email
is sent during automated tests: invitation tests use Django's in-memory backend.
The new competing-creation test in `notebook/tests/test_concurrency.py` requires
PostgreSQL and runs under the existing CI concurrency gate.
