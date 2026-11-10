"""Revoke browser, bearer and Django sessions without changing a password."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.signals import user_logged_in
from django.contrib.sessions.models import Session
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import UserSessionState

GENERATION_CLAIM = "session_generation"
logger = logging.getLogger(__name__)


def session_generation(user):
    return UserSessionState.objects.filter(user_id=user.pk).values_list("generation", flat=True).first() or 0


def validate_session_generation(user, token):
    if token.get(GENERATION_CLAIM, 0) != session_generation(user):
        raise AuthenticationFailed("This session was revoked. Please sign in again.", code="session_revoked")


@receiver(user_logged_in, dispatch_uid="openlims_session_generation")
def remember_session_generation(sender, request, user, **kwargs):
    if request is None:
        return
    with transaction.atomic():
        current = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not current.is_active:
            logout(request)
            return
        request.session[GENERATION_CLAIM] = session_generation(current)


class SessionRevocationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.get(GENERATION_CLAIM, 0) != session_generation(request.user):
            logout(request)
        return self.get_response(request)


def _close_sockets(user_id):
    try:
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(f"user_sessions_{user_id}", {"type": "session.revoked"})
    except Exception:
        # Each outbound message also revalidates the credential. A channel-layer
        # outage must not prevent the database revocation from taking effect.
        logger.warning("Could not deliver an offboarding socket close for user %s", user_id)


def revoke_user_sessions(user):
    """Caller holds the User row lock inside the offboarding transaction."""
    state, _ = UserSessionState.objects.get_or_create(user=user)
    state.generation += 1
    state.save(update_fields=["generation"])
    now = timezone.now()
    tokens = OutstandingToken.objects.filter(user=user, expires_at__gt=now)
    blacklisted = 0
    for token in tokens:
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        blacklisted += int(created)
    session_keys = [row.session_key for row in Session.objects.filter(expire_date__gt=now).iterator()
                    if str(row.get_decoded().get("_auth_user_id", "")) == str(user.pk)]
    Session.objects.filter(session_key__in=session_keys).delete()
    transaction.on_commit(lambda: _close_sockets(user.pk))
    return {"generation": state.generation, "refresh_tokens_blacklisted": blacklisted,
            "django_sessions_removed": len(session_keys)}
