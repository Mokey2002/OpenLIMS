from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


User = get_user_model()


@database_sync_to_async
def get_user_from_token(token):
    try:
        access_token = AccessToken(token)
        user_id = access_token.get("user_id")

        if not user_id:
            return AnonymousUser()

        return User.objects.get(id=user_id, is_active=True)

    except (TokenError, User.DoesNotExist):
        return AnonymousUser()


def _token_from_cookie(scope):
    headers = dict(scope.get("headers") or [])
    raw_cookie = headers.get(b"cookie", b"").decode()
    if not raw_cookie:
        return None

    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(settings.JWT_ACCESS_COOKIE_NAME)
    return morsel.value if morsel else None


def _token_from_query_string(scope):
    query_string = scope.get("query_string", b"").decode()
    query_params = parse_qs(query_string)
    values = query_params.get("token")
    return values[0] if values else None


class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Browser clients authenticate with the same-origin HttpOnly cookie.
        # Query-string JWTs remain a compatibility fallback for non-browser clients.
        token = _token_from_cookie(scope) or _token_from_query_string(scope)
        scope["user"] = await get_user_from_token(token) if token else AnonymousUser()
        return await self.app(scope, receive, send)


def JWTAuthMiddlewareStack(app):
    return JWTAuthMiddleware(app)
