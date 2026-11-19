from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from .permissions import is_requester_only


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


def enforce_csrf(request):
    check = _CSRFCheck(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF validation failed: {reason}")


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate API clients with Bearer JWTs or same-origin HttpOnly cookies.

    Authorization headers remain supported for scripts and instrument/API clients.
    Browser sessions use an HttpOnly access cookie and therefore receive CSRF
    enforcement on unsafe requests.
    """

    def get_user(self, validated_token):
        from .session_revocation import validate_session_generation
        user = super().get_user(validated_token)
        validate_session_generation(user, validated_token)
        return user

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            authenticated = super().authenticate(request)
        else:
            raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE_NAME)
            if not raw_token:
                return None

            validated_token = self.get_validated_token(raw_token)
            enforce_csrf(request)
            authenticated = self.get_user(validated_token), validated_token

        # Legacy lab endpoints use varied permissions. Portal-only accounts
        # can authenticate solely on views that explicitly accept them.
        view = (request.parser_context or {}).get("view")
        if authenticated and not getattr(view, "requester_access", False) and is_requester_only(authenticated[0]):
            raise exceptions.PermissionDenied("This account can only use the requester portal.")
        return authenticated
