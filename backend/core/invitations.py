"""Account invitations: email contains a password-setup token, never a password."""
import logging
from smtplib import SMTPException
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import BadHeaderError, send_mail
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from events.models import Event
from .authentication import enforce_csrf

logger = logging.getLogger(__name__)


def invitation_origin():
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        raise serializers.ValidationError({'detail': 'Configure either STARTTLS or SSL for email, not both.'})
    origin = settings.OPENLIMS_PUBLIC_URL.rstrip('/')
    parsed = urlsplit(origin)
    if (not settings.OPENLIMS_EMAIL_ENABLED or parsed.scheme != 'https'
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise serializers.ValidationError({'detail': 'Invitation email is not configured. Contact the administrator.'})
    return origin


def send_invitation(user, actor):
    origin = invitation_origin()
    if not user.is_active or not user.email:
        raise serializers.ValidationError({'detail': 'An active account with an email address is required.'})
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    # Fragments are not sent to the web server in requests or referrer headers.
    link = f'{origin}/set-password#uid={uid}&token={token}'
    body = (
        f'Welcome to OpenLIMS / Bienvenido a OpenLIMS\n\n'
        f'Username / Usuario: {user.username}\n\n'
        f'Set your password / Establece tu contraseña:\n{link}\n\n'
        f'This link expires in {settings.PASSWORD_RESET_TIMEOUT // 3600} hours and can only be used once.\n'
        f'Este enlace vence en {settings.PASSWORD_RESET_TIMEOUT // 3600} horas y solo puede usarse una vez.\n'
        'If you did not expect this invitation, contact your lab administrator.\n'
        'Si no esperabas esta invitación, contacta al administrador del laboratorio.\n'
    )
    try:
        sent = send_mail('OpenLIMS — Set your password / Establece tu contraseña', body,
                         settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        status = 'sent' if sent == 1 else 'failed'
    except (SMTPException, OSError, BadHeaderError):
        # Do not log SMTP responses, credentials, or invitation links.
        logger.warning('Invitation email delivery failed for user id %s', user.pk)
        status = 'failed'
    Event.objects.create(entity_type='User', entity_id=str(user.pk),
                         action='USER_INVITATION_SENT' if status == 'sent' else 'USER_INVITATION_FAILED',
                         actor=actor, payload={'user_id': user.pk, 'status': status})
    return status


class InvitationSendThrottle(UserRateThrottle):
    rate = '20/hour'
    scope = 'invitation_send'


class InvitationAcceptThrottle(AnonRateThrottle):
    rate = '10/minute'
    scope = 'invitation_accept'


class AcceptInvitationSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=128)
    token = serializers.CharField(max_length=256)
    password = serializers.CharField(write_only=True, max_length=1024, trim_whitespace=False)


class AcceptInvitationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [InvitationAcceptThrottle]

    def post(self, request):
        enforce_csrf(request)
        data = AcceptInvitationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        User = get_user_model()
        with transaction.atomic():
            try:
                pk = urlsafe_base64_decode(values['uid']).decode()
                user = User.objects.select_for_update().get(pk=pk, is_active=True)
            except (ValueError, UnicodeDecodeError, OverflowError, User.DoesNotExist):
                raise serializers.ValidationError({'detail': 'Invalid or expired invitation.'})
            if not default_token_generator.check_token(user, values['token']):
                raise serializers.ValidationError({'detail': 'Invalid or expired invitation.'})
            try:
                validate_password(values['password'], user)
            except ValidationError as exc:
                raise serializers.ValidationError({'password': exc.messages})
            user.set_password(values['password'])
            user.save(update_fields=['password'])
            Event.objects.create(entity_type='User', entity_id=str(user.pk),
                                 action='USER_PASSWORD_SET', actor=user,
                                 payload={'user_id': user.pk})
        return Response({'detail': 'Password saved. You can now sign in.'})
