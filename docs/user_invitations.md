# Account invitation setup / Configuración de invitaciones

## English

Configure `deploy/.env` with the SMTP service supplied by the hosting team:

```dotenv
OPENLIMS_EMAIL_ENABLED=true
OPENLIMS_PUBLIC_URL=https://agrobiom.matmor.unam.mx:8443
EMAIL_HOST=YOUR_SMTP_HOST
EMAIL_PORT=587
EMAIL_HOST_USER=YOUR_SMTP_USERNAME
EMAIL_HOST_PASSWORD=YOUR_SMTP_PASSWORD
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=OpenLIMS <YOUR_APPROVED_SENDER_ADDRESS>
```

The public URL must include the port and use HTTPS. It is configured explicitly;
request Host headers never determine invitation links. Configure CSRF_TRUSTED_ORIGINS
with the same origin. Port 587 uses STARTTLS; for an SMTP service requiring implicit
TLS, use its port (typically 465), EMAIL_USE_TLS=false and EMAIL_USE_SSL=true.
Keep credentials out of Git. Ask the host administrator for an approved sender,
SMTP credentials and outbound network access. No public database port is needed.

Rebuild API and frontend after updating code, and recreate API to apply .env changes.
No schema migration is introduced. A Docker restart alone does not reload environment.

API clients opt in with `send_invitation: true`; omitting it preserves the manual-password API contract.

In Users, email invitations are selected by default. Enter an email, username, name
and role, then create the user. The new account has an unusable password until the
recipient follows the bilingual welcome email and chooses a password. No password
is emailed. Links expire after 24 hours and become invalid after password setup.

Existing accounts: use **Send invitation** beside the user. This does not change
an existing password or role, and no existing account is emailed automatically by
an upgrade. An existing password continues working until the recipient sets a new
one. Resending does not revoke earlier links; password setup invalidates them all.

The UI distinguishes account creation from email delivery failure. If delivery
fails, the account remains created: fix SMTP settings and use Send invitation.
Do not create duplicate accounts. “Submitted for email delivery” means the SMTP
server accepted the message, not proof it reached the recipient's inbox. Check spam
and delivery logs. The feature sends synchronously with a 10-second SMTP timeout.

If SMTP is not configured, invitation creation is rejected before creating the
account. Uncheck the invitation option to use the existing manual-password flow.
That manual fallback does not enforce a password change on first login.

Validate with a test account and your actual SMTP service before inviting the lab.
Automated tests use an in-memory mail backend; they do not send external messages.

## Español

Solicita a Luis el servidor SMTP, puerto, credenciales y remitente autorizado.
Configura las variables anteriores en `deploy/.env`, incluyendo la URL pública
con `:8443`. Recrea la API después de modificar las variables.

En **Usuarios**, deja activado el envío de invitación, completa el correo y los
datos de la cuenta y pulsa **Crear usuario**. La persona recibirá su usuario y un
enlace para elegir una contraseña. El enlace vence en 24 horas y deja de funcionar
al guardar la contraseña; no se envían contraseñas por correo.

Para cuentas ya creadas, pulsa **Enviar invitación**. Esto conserva sus permisos y
su contraseña actual hasta que la persona establezca otra. Actualizar el software
no envía correos masivos. Reenviar no revoca enlaces anteriores; establecer la
contraseña los invalida todos.

Si falla el envío, la cuenta sigue creada. Corrige la configuración del correo y
reenvía la invitación. Si no hay SMTP, puedes desactivar la invitación y crear una
cuenta con contraseña manual; ese modo no obliga a cambiarla al iniciar sesión.
