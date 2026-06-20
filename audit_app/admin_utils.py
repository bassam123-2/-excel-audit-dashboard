"""Shared helpers for Django admin display."""
from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.widgets import AutocompleteSelect
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _


def format_admin_user_label(user: User) -> str:
    """Username plus full name for admin choice widgets."""
    full = user.get_full_name().strip()
    if full:
        return f"{user.username} - {full}"
    return user.username


def format_admin_boolean_icon(
    is_yes: bool,
    *,
    yes_label: str | None = None,
    no_label: str | None = None,
):
    """Bootstrap check / X icon for admin changelist boolean columns."""
    yes = yes_label if yes_label is not None else _("Active")
    no = no_label if no_label is not None else _("Inactive")
    if is_yes:
        return format_html(
            '<i class="bi bi-check-circle-fill admin-active-status admin-active-status--yes" '
            'title="{}" aria-label="{}"></i>',
            yes,
            yes,
        )
    return format_html(
        '<i class="bi bi-x-circle-fill admin-active-status admin-active-status--no" '
        'title="{}" aria-label="{}"></i>',
        no,
        no,
    )


format_admin_active_status_icon = format_admin_boolean_icon


def install_boolean_icon_list_columns(
    model_admin_cls,
    model_cls,
    field_names: tuple[str, ...],
    *,
    yes_label: str | None = None,
    no_label: str | None = None,
) -> tuple[str, ...]:
    """Attach changelist display methods that render unified boolean icons."""
    display_names: list[str] = []
    yes = yes_label if yes_label is not None else _("Yes")
    no = no_label if no_label is not None else _("No")

    for field_name in field_names:
        field = model_cls._meta.get_field(field_name)
        method_name = f"{field_name}_display"

        def make_display(
            bound_field_name=field_name,
            bound_verbose_name=field.verbose_name,
        ):
            @admin.display(description=bound_verbose_name, ordering=bound_field_name)
            def display_method(self, obj):
                return format_admin_boolean_icon(
                    getattr(obj, bound_field_name),
                    yes_label=yes,
                    no_label=no,
                )

            display_method.__name__ = method_name
            return display_method

        setattr(model_admin_cls, method_name, make_display())
        display_names.append(method_name)

    return tuple(display_names)


class WorkflowAssigneeAutocompleteWidget(AutocompleteSelect):
    """Workflow step assignee search with custom labels and duplicate exclusion."""

    def get_url(self):
        return reverse("admin:audit_app_workflowtemplate_assignee_autocomplete")

    def build_attrs(self, base_attrs, extra_attrs=None):
        built = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        built["data-ajax--cache"] = "false"
        css_class = built.get("class", "")
        css_class = " ".join(
            token for token in css_class.split() if token != "admin-autocomplete"
        )
        built["class"] = (css_class + " wf-assignee-autocomplete").strip()
        return built
