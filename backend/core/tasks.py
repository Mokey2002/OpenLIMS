import logging
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import BadHeaderError, send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.exceptions import ValidationError

from .invitations import invitation_origin

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def send_password_recovery(email):
    try:
        origin = invitation_origin()
    except ValidationError:
        logger.warning('Password recovery email is not configured')
        return
    for user in get_user_model().objects.filter(email__iexact=email, is_active=True):
        # Invited accounts must use their administrator-issued setup link.
        if not user.has_usable_password():
            continue
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        link = f'{origin}/set-password#uid={uid}&token={token}'
        body = (
            f'OpenLIMS password reset / Restablecer contraseña\n\n'
            f'Username / Usuario: {user.username}\n\n{link}\n\n'
            f'This link expires in {settings.PASSWORD_RESET_TIMEOUT // 3600} hours and can only be used once.\n'
            f'Este enlace vence en {settings.PASSWORD_RESET_TIMEOUT // 3600} horas y solo puede usarse una vez.\n\n'
            'If you did not request this, ignore this email. Your password has not changed.\n'
            'Si no lo solicitaste, ignora este correo. Tu contraseña no ha cambiado.\n'
        )
        try:
            send_mail('OpenLIMS — Reset password / Restablecer contraseña', body,
                      settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        except (SMTPException, OSError, BadHeaderError):
            logger.warning('Password recovery email delivery failed for user id %s', user.pk)
