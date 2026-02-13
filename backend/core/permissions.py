from rest_framework.permissions import BasePermission, SAFE_METHODS


def in_group(user, name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=name).exists()


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
