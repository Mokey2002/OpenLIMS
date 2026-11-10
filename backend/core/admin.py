from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import Group
from django.forms import ModelForm
from django.utils.translation import gettext_lazy as _
from django.contrib.admin.actions import delete_selected
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from .models import AccessRequest
from .user_safety import (
    LastAdministratorError, lock_users, protect_admin_group_removal, protect_user_deletion,
    protect_user_state, user_administration,
)


class ProtectedUserChangeForm(UserChangeForm):
    def clean(self):
        data = super().clean()
        if self.instance.pk:
            with user_administration():
                current = get_user_model().objects.get(pk=self.instance.pk)
                groups = data.get("groups", current.groups.all())
                protect_user_state(
                    current, active=data.get("is_active", current.is_active),
                    administrator=data.get("is_superuser", current.is_superuser) or any(group.name == "admin" for group in groups),
                )
        return data


class ProtectedGroupForm(ModelForm):
    class Meta:
        model = Group
        fields = "__all__"

    def clean(self):
        data = super().clean()
        with user_administration():
            if self.instance.pk and data.get("name") != "admin" and Group.objects.filter(pk=self.instance.pk, name="admin").exists():
                protect_admin_group_removal()
        return data


@admin.action(permissions=["delete"], description=_("Delete selected %(verbose_name_plural)s"))
def protected_delete_selected(modeladmin, request, queryset):
    with user_administration():
        return delete_selected(modeladmin, request, queryset)


class AdministratorSafetyMixin:
    def _lock_people(self, request, objects=()):
        targets = objects if self.model is get_user_model() else ()
        current = lock_users(request.user, targets).get(request.user.pk)
        if not current or not current.is_active or not current.is_staff:
            raise PermissionDenied("Your administrator access changed. Refresh the page and sign in again if needed.")
        request.user = current

    @method_decorator(sensitive_post_parameters())
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        with user_administration():
            target = self.get_object(request, unquote(object_id)) if object_id and self.model is get_user_model() else None
            self._lock_people(request, [target] if target else [])
            return super().changeform_view(request, object_id, form_url, extra_context)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            actions["delete_selected"] = (protected_delete_selected, "delete_selected", protected_delete_selected.short_description)
        return actions

    def get_deleted_objects(self, objs, request):
        # Both Django's single-delete view and the wrapped bulk action hold an
        # outer transaction, so this lock lasts through the actual deletion.
        with user_administration():
            self._lock_people(request, objs)
            result = super().get_deleted_objects(objs, request)
            try:
                self.protect_deletion(objs)
            except LastAdministratorError as error:
                result[3].append(error.messages[0])
            return result

    def delete_model(self, request, obj):
        with user_administration():
            self._lock_people(request, [obj])
            self.protect_deletion([obj])
            return super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with user_administration():
            self._lock_people(request, queryset)
            self.protect_deletion(queryset)
            return super().delete_queryset(request, queryset)


class ProtectedUserAdmin(AdministratorSafetyMixin, UserAdmin):
    form = ProtectedUserChangeForm

    @method_decorator(sensitive_post_parameters())
    def user_change_password(self, request, id, form_url=""):
        if request.method != "POST":
            return super().user_change_password(request, id, form_url)
        with user_administration():
            target = self.get_object(request, unquote(id))
            self._lock_people(request, [target] if target else [])
            return super().user_change_password(request, id, form_url)

    def protect_deletion(self, objects):
        protect_user_deletion([obj.pk for obj in objects])


class ProtectedGroupAdmin(AdministratorSafetyMixin, GroupAdmin):
    form = ProtectedGroupForm

    def protect_deletion(self, objects):
        if Group.objects.filter(pk__in=[obj.pk for obj in objects], name="admin").exists():
            protect_admin_group_removal()


for model, model_admin in [(get_user_model(), ProtectedUserAdmin), (Group, ProtectedGroupAdmin)]:
    if admin.site.is_registered(model):
        admin.site.unregister(model)
    admin.site.register(model, model_admin)


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ["requester_username", "kind", "project_code", "role", "status", "created_at"]
    list_filter = ["status", "kind"]
    readonly_fields = [field.name for field in AccessRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
