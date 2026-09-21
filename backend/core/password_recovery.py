"""Public password recovery; account lookup and delivery happen in the worker."""
import hashlib
import logging

from kombu.exceptions import OperationalError
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from .authentication import enforce_csrf
from .tasks import send_password_recovery

logger = logging.getLogger(__name__)


class RecoveryIPThrottle(AnonRateThrottle):
    rate = '10/hour'
    scope = 'password_recovery_ip'


class RecoveryEmailThrottle(SimpleRateThrottle):
    rate = '3/hour'
    scope = 'password_recovery_email'

    def get_cache_key(self, request, view):
        email = str(request.data.get('email', '')).strip().casefold()
        return self.cache_format % {'scope': self.scope, 'ident': hashlib.sha256(email.encode()).hexdigest()}


class RecoverySerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordRecoveryView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RecoveryIPThrottle, RecoveryEmailThrottle]

    def post(self, request):
        enforce_csrf(request)
        data = RecoverySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Queue every valid address so response timing does not depend on account existence.
        try:
            send_password_recovery.apply_async(
                args=[data.validated_data['email']], argsrepr='[redacted]', retry=False)
        except (OperationalError, OSError):
            logger.warning('Password recovery queue unavailable')
            return Response({'detail': 'Password recovery is temporarily unavailable. Try again later.'}, status=503)
        return Response({'detail': 'If an eligible account exists, you will receive a password reset email. Check your inbox and spam folder.'})
