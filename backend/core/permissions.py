from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS


class HasInstrumentApiKey(BasePermission):
    def has_permission(self, request, view):
        api_key = request.headers.get("X-Instrument-Api-Key")
        return bool(
            api_key
            and settings.INSTRUMENT_API_KEY
            and api_key == settings.INSTRUMENT_API_KEY
        )

def in_group(user, name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=name).exists()


class IsAuthenticatedProjectReadAdminWrite(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return user.is_superuser or in_group(user, "admin")

class IsAuthenticatedReadOnlyOrTechAdminWrite(BasePermission):
    """
    Any authenticated user can READ (GET/HEAD/OPTIONS).
    Only tech/admin can WRITE (POST/PATCH/PUT/DELETE).
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # admin always allowed
        if user.is_superuser or in_group(user, "admin"):
            return True

        if request.method in SAFE_METHODS:
            # viewer + tech can read
            return in_group(user, "viewer") or in_group(user, "tech")

        # writes
        return in_group(user, "tech")


class IsAdminOnly(BasePermission):
    """Only admin group or superuser."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_superuser or in_group(user, "admin")))


class IsAuthenticatedReadOnly(BasePermission):
    """Authenticated users can read only."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return request.method in SAFE_METHODS
