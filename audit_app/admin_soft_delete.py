"""Reusable soft-delete behaviour for Django admin ModelAdmin classes."""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR, TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Model
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


def user_can_view_deleted_records(request, model) -> bool:
    """True when the user may view the admin \"All\" / deleted-record filters."""
    opts = model._meta
    codename = f"{opts.app_label}.delete_{opts.model_name}"
    return request.user.has_perm(codename) or request.user.is_superuser


class DeletedRecordFilter(admin.SimpleListFilter):
    title = _("Deletion status")
    parameter_name = "deleted"

    def lookups(self, request, model_admin):
        choices = [
            ("active", _("Active records")),
            ("deleted", _("Deleted records")),
        ]
        if model_admin.can_view_deleted_records(request):
            choices.insert(0, ("all", _("All")))
        return tuple(choices)

    def queryset(self, request, queryset):
        if not hasattr(queryset.model, "is_deleted"):
            return queryset
        value = self.value() or "active"
        if value == "all":
            if user_can_view_deleted_records(request, queryset.model):
                return queryset
            value = "active"
        if value == "deleted":
            return queryset.filter(is_deleted=True)
        return queryset.filter(is_deleted=False)

    def choices(self, changelist):
        model_admin = changelist.model_admin
        value = self.value() or "active"
        can_view_all = model_admin.can_view_deleted_records(self.request)

        if can_view_all:
            yield {
                "selected": value == "all",
                "query_string": changelist.get_query_string(
                    {self.parameter_name: "all"}
                ),
                "display": _("All"),
            }

        yield {
            "selected": value == "active",
            "query_string": changelist.get_query_string(
                {self.parameter_name: "active"}
            ),
            "display": _("Active records"),
        }
        yield {
            "selected": value == "deleted",
            "query_string": changelist.get_query_string(
                {self.parameter_name: "deleted"}
            ),
            "display": _("Deleted records"),
        }


class SoftDeleteAdminMixin:
    """Soft-delete admin records instead of removing database rows."""

    soft_delete_filter_class = DeletedRecordFilter
    cl_v2_default_filter_params = {"deleted": "active"}
    soft_delete_deactivate_active_field: str | None = None
    delete_confirmation_template = "admin/soft_delete_confirmation.html"
    delete_selected_confirmation_template = "admin/soft_delete_selected_confirmation.html"

    def can_view_deleted_records(self, request) -> bool:
        return user_can_view_deleted_records(request, self.model)

    def has_restore_permission(self, request, obj=None) -> bool:
        return self.can_view_deleted_records(request)

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if not hasattr(self.model, "is_deleted"):
            return filters
        if not any(
            f is self.soft_delete_filter_class
            or (isinstance(f, type) and issubclass(f, DeletedRecordFilter))
            for f in filters
        ):
            filters = [self.soft_delete_filter_class, *filters]
        return filters

    def get_actions(self, request):
        actions = super().get_actions(request)
        if hasattr(self.model, "is_deleted"):
            actions.setdefault(
                "restore_selected",
                (
                    SoftDeleteAdminMixin.restore_selected,
                    "restore_selected",
                    _("Restore selected records"),
                ),
            )
        if not self.has_restore_permission(request):
            actions.pop("restore_selected", None)
        return actions

    def _is_soft_deleted(self, obj: Model | None) -> bool:
        return bool(obj is not None and getattr(obj, "is_deleted", False))

    def has_delete_permission(self, request, obj=None):
        if obj is not None and self._is_soft_deleted(obj):
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and hasattr(obj, "is_deleted"):
            for field_name in ("is_deleted", "deleted_at", "deleted_by"):
                if field_name not in readonly and hasattr(obj, field_name):
                    readonly.append(field_name)
            if self._is_soft_deleted(obj) and self.soft_delete_deactivate_active_field:
                active_field = self.soft_delete_deactivate_active_field
                if active_field not in readonly and hasattr(obj, active_field):
                    readonly.append(active_field)
        return readonly

    def perform_soft_delete(self, request, obj: Model) -> None:
        obj.is_deleted = True
        obj.deleted_at = timezone.now()
        update_fields = ["is_deleted", "deleted_at"]
        if hasattr(obj, "deleted_by_id"):
            obj.deleted_by = request.user
            update_fields.append("deleted_by")
        deactivate_field = self.soft_delete_deactivate_active_field
        if deactivate_field and hasattr(obj, deactivate_field):
            setattr(obj, deactivate_field, False)
            update_fields.append(deactivate_field)
        obj.save(update_fields=update_fields)

    def perform_restore(self, request, obj: Model) -> None:
        obj.is_deleted = False
        obj.deleted_at = None
        update_fields = ["is_deleted", "deleted_at"]
        if hasattr(obj, "deleted_by_id"):
            obj.deleted_by = None
            update_fields.append("deleted_by")
        restore_field = self.soft_delete_deactivate_active_field
        if restore_field and hasattr(obj, restore_field) and not getattr(obj, restore_field):
            setattr(obj, restore_field, True)
            update_fields.append(restore_field)
        obj.save(update_fields=update_fields)

    def restore_selected(self, request, queryset):
        if not self.has_restore_permission(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        restored = 0
        for obj in queryset.filter(is_deleted=True):
            self.perform_restore(request, obj)
            restored += 1
        if restored:
            self.message_user(
                request,
                gettext("Restored %(count)d record(s) successfully.")
                % {"count": restored},
                messages.SUCCESS,
            )

    def delete_model(self, request, obj):
        self.perform_soft_delete(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            if not self._is_soft_deleted(obj):
                self.perform_soft_delete(request, obj)

    def _soft_delete_success_message(self, obj: Model) -> str:
        return gettext('The %(type)s "%(name)s" was removed successfully.') % {
            "type": self.opts.verbose_name,
            "name": str(obj),
        }

    def _restore_success_message(self, obj: Model) -> str:
        return gettext('The %(type)s "%(name)s" was restored successfully.') % {
            "type": self.opts.verbose_name,
            "name": str(obj),
        }

    def _enforce_soft_deleted_save_state(self, obj: Model) -> None:
        original = self.model.objects.filter(pk=obj.pk).first()
        if original is None or not original.is_deleted:
            return
        obj.is_deleted = True
        obj.deleted_at = original.deleted_at
        if hasattr(obj, "deleted_by_id"):
            obj.deleted_by = original.deleted_by
        deactivate_field = self.soft_delete_deactivate_active_field
        if deactivate_field and hasattr(obj, deactivate_field):
            setattr(obj, deactivate_field, False)

    def save_model(self, request, obj, form, change):
        if change:
            self._enforce_soft_deleted_save_state(obj)
        super().save_model(request, obj, form, change)

    def response_change(self, request, obj):
        if "_restore" in request.POST:
            if not self.has_restore_permission(request, obj):
                raise PermissionDenied
            if not self._is_soft_deleted(obj):
                raise ValidationError(_("This record is not deleted."))
            self.perform_restore(request, obj)
            self.message_user(
                request,
                self._restore_success_message(obj),
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                    args=(obj.pk,),
                    current_app=self.admin_site.name,
                )
            )
        return super().response_change(request, obj)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if change and obj is not None and hasattr(obj, "is_deleted"):
            context["record_is_soft_deleted"] = self._is_soft_deleted(obj)
            context["can_restore_record"] = (
                self._is_soft_deleted(obj) and self.has_restore_permission(request, obj)
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None and hasattr(obj, "is_deleted"):
            extra_context["record_is_soft_deleted"] = self._is_soft_deleted(obj)
            extra_context["can_restore_record"] = (
                self._is_soft_deleted(obj) and self.has_restore_permission(request, obj)
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)

        if not self.has_delete_permission(request, obj):
            raise PermissionDenied

        if request.method == "POST":
            self.perform_soft_delete(request, obj)
            self.log_deletion(request, obj, str(obj))
            self.message_user(
                request,
                self._soft_delete_success_message(obj),
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist",
                    current_app=self.admin_site.name,
                )
            )

        context = {
            **self.admin_site.each_context(request),
            "title": _("Remove %(name)s") % {"name": self.opts.verbose_name},
            "object": obj,
            "object_name": self.opts.verbose_name,
            "opts": self.opts,
            "deleted_objects": [],
            "model_count": {},
            "perms_lacking": set(),
            "protected": [],
            "is_popup": IS_POPUP_VAR in request.POST or IS_POPUP_VAR in request.GET,
            "is_popup_var": IS_POPUP_VAR,
            "to_field_var": TO_FIELD_VAR,
            "to_field": request.POST.get(TO_FIELD_VAR) or request.GET.get(TO_FIELD_VAR),
            **(extra_context or {}),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            self.delete_confirmation_template or [
                "admin/{}/{}/delete_confirmation.html".format(
                    self.opts.app_label,
                    self.opts.model_name,
                ),
                "admin/soft_delete_confirmation.html",
                "admin/delete_confirmation.html",
            ],
            context,
        )
