"""Shared admin changelist v2 layout (stats, toolbar, filters below table)."""

from __future__ import annotations

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, QuerySet, Sum
from django.http import Http404, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _


def cl_v2_stat_card(
    label: str,
    value: int,
    *,
    icon: str = "bi-collection-fill",
    tone: str = "primary",
) -> dict:
    return {"label": label, "value": value, "icon": icon, "tone": tone}


def cl_v2_total_and_active_cards(
    queryset: QuerySet,
    *,
    total_label: str,
    total_icon: str = "bi-collection-fill",
    active_label: str | None = None,
    active_field: str = "is_active",
    active_icon: str = "bi-check-circle-fill",
) -> list[dict]:
    cards = [
        cl_v2_stat_card(total_label, queryset.count(), icon=total_icon, tone="primary"),
    ]
    if active_label:
        cards.append(
            cl_v2_stat_card(
                active_label,
                queryset.filter(**{active_field: True}).count(),
                icon=active_icon,
                tone="success",
            )
        )
    return cards


def cl_v2_count_where(
    queryset: QuerySet,
    label: str,
    *,
    icon: str,
    tone: str = "info",
    **filters,
) -> dict:
    return cl_v2_stat_card(label, queryset.filter(**filters).count(), icon=icon, tone=tone)


class AdminChangelistV2Mixin:
    """Apply the v2 changelist template, stats strip, and optional quick actions."""

    change_list_template = "admin/changelist_v2.html"
    cl_v2_subtitle = ""
    cl_v2_search_placeholder = _("Search…")
    CL_V2_QUICK_ACTIONS: tuple[str, ...] = ()
    CL_V2_QUICK_ACTION_ICONS: dict[str, str] = {}
    cl_v2_default_filter_params: dict[str, str] = {}

    @admin.display(description=_("ID"), ordering="id")
    def id_display(self, obj):
        return obj.pk

    def get_list_display(self, request):
        list_display = super().get_list_display(request)
        if "id" not in list_display:
            return list_display
        return tuple("id_display" if name == "id" else name for name in list_display)

    def get_cl_v2_subtitle(self, request) -> str:
        return self.cl_v2_subtitle

    def get_cl_v2_search_placeholder(self, request) -> str:
        return self.cl_v2_search_placeholder

    def get_cl_v2_stat_cards(self, request, queryset) -> list[dict]:
        return []

    def get_cl_v2_default_filter_redirect(self, request):
        if not self.cl_v2_default_filter_params:
            return None
        missing = [
            key
            for key in self.cl_v2_default_filter_params
            if key not in request.GET
        ]
        if not missing:
            return None
        params = request.GET.copy()
        for key in missing:
            params[key] = self.cl_v2_default_filter_params[key]
        changelist_url = reverse(
            f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"
        )
        return HttpResponseRedirect(f"{changelist_url}?{params.urlencode()}")

    def get_cl_v2_quick_actions(self, request) -> list[dict]:
        if not self.CL_V2_QUICK_ACTIONS:
            return []
        actions = self.get_actions(request)
        quick = []
        for action_key in self.CL_V2_QUICK_ACTIONS:
            action = actions.get(action_key)
            if not action:
                continue
            _func, _name, description = action
            requires_selection = action_key.endswith("_selected")
            item = {
                "key": action_key,
                "label": description,
                "icon": self.CL_V2_QUICK_ACTION_ICONS.get(
                    action_key, "bi-lightning-charge"
                ),
                "requires_selection": requires_selection,
            }
            if not requires_selection:
                item["url"] = reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_quick_action",
                    args=[action_key],
                )
                item["return_url"] = request.get_full_path()
            quick.append(item)
        return quick

    def get_cl_v2_urls(self):
        if not self.CL_V2_QUICK_ACTIONS:
            return []
        global_actions = [
            action_key
            for action_key in self.CL_V2_QUICK_ACTIONS
            if not action_key.endswith("_selected")
        ]
        if not global_actions:
            return []
        return [
            path(
                "quick-action/<str:action_name>/",
                self.admin_site.admin_view(self.quick_action_view),
                name=f"{self.opts.app_label}_{self.opts.model_name}_quick_action",
            ),
        ]

    def quick_action_view(self, request, action_name):
        if request.method != "POST":
            return HttpResponseRedirect(
                request.GET.get("next", reverse("admin:index"))
            )

        if action_name not in self.CL_V2_QUICK_ACTIONS:
            raise Http404

        if action_name.endswith("_selected"):
            raise Http404

        if action_name not in self.get_actions(request):
            raise PermissionDenied

        queryset = self.get_queryset(request)
        getattr(self, action_name)(request, queryset)

        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return HttpResponseRedirect(next_url)
        return HttpResponseRedirect(
            reverse(f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist")
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        redirect = self.get_cl_v2_default_filter_redirect(request)
        if redirect is not None:
            return redirect

        extra_context["cl_v2_subtitle"] = self.get_cl_v2_subtitle(request)
        extra_context["cl_v2_search_placeholder"] = self.get_cl_v2_search_placeholder(
            request
        )
        extra_context["cl_v2_quick_actions"] = self.get_cl_v2_quick_actions(request)

        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and response.context_data.get("cl"):
            filtered_qs = response.context_data["cl"].queryset
            response.context_data["cl_v2_stat_cards"] = self.get_cl_v2_stat_cards(
                request, filtered_qs
            )
        return response


class AdminChangeFormV2Mixin:
    """Apply v2 layout to admin add/change forms."""

    change_form_template = "admin/change_form_v2.html"
    add_form_template = "admin/change_form_v2.html"
    cl_v2_form_subtitle = ""

    def get_cl_v2_page_title(self, request, obj=None, add=False):
        fixed = getattr(self, "cl_v2_page_title", "")
        if fixed and not add:
            return fixed
        if add:
            return _("Add New")
        if obj is not None:
            return str(obj)
        return ""

    def get_cl_v2_form_subtitle(self, request, obj=None, add=False):
        custom = self.cl_v2_form_subtitle or getattr(self, "cl_v2_subtitle", "")
        if custom:
            return custom
        if add:
            return _("Fill in the details below, then save to create the record.")
        return _("Update the fields below and save your changes.")

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        context = context or {}
        context["cl_v2_page_title"] = self.get_cl_v2_page_title(
            request, obj=obj, add=add
        )
        context["cl_v2_subtitle"] = self.get_cl_v2_form_subtitle(
            request, obj=obj, add=add
        )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )


class AdminClV2Mixin(AdminChangelistV2Mixin, AdminChangeFormV2Mixin):
    """Changelist and add/change form v2 layout."""
