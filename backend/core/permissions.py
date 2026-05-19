from rest_framework.permissions import BasePermission, SAFE_METHODS


def has_role(user, role_name):
    return (
        user
        and user.is_authenticated
        and user.groups.filter(name=role_name).exists()
    )


def is_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name="admin").exists()
        )
    )


def is_tech(user):
    return has_role(user, "tech")


def is_viewer(user):
    return has_role(user, "viewer")


class IsAdminOnly(BasePermission):
    """
    Only OpenLIMS admins or Django superusers can access.
    """

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsAuthenticatedReadOnly(BasePermission):
    """
    Read-only access for any authenticated user.
    Write actions are blocked.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        return request.method in SAFE_METHODS


class IsAuthenticatedReadOnlyOrTechAdminWrite(BasePermission):
    """
    Read:
      - admin
      - tech
      - viewer

    Write:
      - admin
      - tech
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return is_admin(user) or is_tech(user) or is_viewer(user)

        return is_admin(user) or is_tech(user)


class IsAuthenticatedReadOnlyAdminWrite(BasePermission):
    """
    Read:
      - admin
      - tech
      - viewer

    Write:
      - admin only
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return is_admin(user) or is_tech(user) or is_viewer(user)

        return is_admin(user)


class IsAuthenticatedProjectReadAdminWrite(BasePermission):
    """
    Project permissions.

    Read:
      - any authenticated user

    Write:
      - admin or superuser

    This preserves your existing projects.views import.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return is_admin(user)


class IsProjectAdminOrReadOnly(BasePermission):
    """
    Read:
      - authenticated users

    Write:
      - admin or superuser
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return is_admin(user)


class IsAdminOrSelf(BasePermission):
    """
    Admins can manage anyone.
    Users can access themselves when object-level checks are used.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return is_admin(request.user) or obj == request.user
