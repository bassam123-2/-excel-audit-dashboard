"""Admin user forms — password authentication is always required."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordMixin, UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from accounts_app.models import UserProfile

User = get_user_model()

from audit_app.models import (
    ATTACHMENT_KIND_CHOICES,
    ATTACHMENT_KIND_CODES,
    COMPANY_KIND_MAIN,
    COMPANY_KIND_SUBSIDIARY,
    Company,
    CompanyAttachmentSetting,
)

IS_STAFF_LABEL = _("Admin")
IS_STAFF_HELP = _(
    "Designates whether this user has admin access to the administration site."
)


def apply_is_staff_labels(form: forms.BaseForm) -> None:
    if "is_staff" in form.fields:
        form.fields["is_staff"].label = IS_STAFF_LABEL
        form.fields["is_staff"].help_text = IS_STAFF_HELP


def _clear_password_help_text(form: forms.BaseForm) -> None:
    """Hide Django validator help — custom live checklist replaces it."""
    for name in ("password1", "password2"):
        if name in form.fields:
            form.fields[name].help_text = ""


def _validate_required_stripped(value: str, field_label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError(
            _("%(field)s is required.") % {"field": field_label}
        )
    return value


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _validate_email_format(email: str, *, exclude_user_id: int | None = None) -> str:
    email = _normalize_email(email)
    if not email:
        raise forms.ValidationError(_("Email address is required."))
    try:
        validate_email(email)
    except DjangoValidationError as exc:
        raise forms.ValidationError(_("Enter a valid email address.")) from exc
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    if qs.exists():
        raise forms.ValidationError(_("A user with this email already exists."))
    return email


def _validate_username(username: str) -> str:
    username = (username or "").strip()
    if not username:
        raise forms.ValidationError(_("Username is required."))
    if " " in username:
        raise forms.ValidationError(_("Username must not contain spaces."))
    return username


def _save_user_job_title(user, job_title: str) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.job_title = job_title or ""
    profile.save(update_fields=["job_title"])


def _save_user_two_factor(user, enabled: bool) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.two_factor_enabled = bool(enabled)
    profile.save(update_fields=["two_factor_enabled"])


def _save_user_password_expiry(user, enabled: bool) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.password_expiry_enabled = bool(enabled)
    profile.save(update_fields=["password_expiry_enabled"])


def _save_user_workflow_emails(user, enabled: bool) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.receive_workflow_emails = bool(enabled)
    profile.save(update_fields=["receive_workflow_emails"])


def apply_user_profile_form(user, cleaned_data: dict) -> None:
    """Persist profile fields from admin user forms (call after the User row exists)."""
    if not user.pk:
        return
    _save_user_job_title(user, cleaned_data.get("job_title", ""))
    _save_user_two_factor(user, cleaned_data.get("two_factor_enabled", True))
    _save_user_password_expiry(
        user, cleaned_data.get("password_expiry_enabled", True)
    )
    if user.is_superuser:
        _save_user_workflow_emails(
            user, cleaned_data.get("receive_workflow_emails", False)
        )


def _initial_job_title(user) -> str:
    if not user.pk:
        return ""
    try:
        return user.profile.job_title
    except UserProfile.DoesNotExist:
        return ""


def _form_data_requests_superuser(form: forms.BaseForm) -> bool:
    if not form.data:
        return False
    return form.data.get("is_superuser") in ("on", "true", "1", True)


class MandatoryPasswordAdminCreationForm(UserCreationForm):
    """Create users in admin with a required password (no disable-password option)."""

    email = forms.EmailField(
        label=_("Email address"),
        required=True,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "inputmode": "email"},
        ),
    )
    first_name = forms.CharField(
        label=_("First name"),
        required=True,
        max_length=150,
    )
    last_name = forms.CharField(
        label=_("Last name"),
        required=True,
        max_length=150,
    )
    job_title = forms.CharField(
        label=_("Job title"),
        required=True,
        max_length=128,
        help_text=_("The user's job title or position."),
    )
    send_credentials_email = forms.BooleanField(
        label=_("Send new password by email"),
        required=False,
        initial=False,
        help_text=_(
            "When checked, the new password is emailed to the user. "
            "They must change it on next sign-in."
        ),
    )
    two_factor_enabled = forms.BooleanField(
        label=_("Email two-factor authentication"),
        required=False,
        initial=True,
        help_text=_("When enabled, a one-time code is sent by email at sign-in."),
    )
    password_expiry_enabled = forms.BooleanField(
        label=_("Require password change every 6 months"),
        required=False,
        initial=True,
        help_text=_("When enabled, the user must change their password every 180 days."),
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _clear_password_help_text(self)
        self.fields["email"].required = True

    def clean_username(self):
        return _validate_username(self.cleaned_data.get("username", ""))

    def clean_first_name(self):
        return _validate_required_stripped(
            self.cleaned_data.get("first_name", ""), str(_("First name"))
        )

    def clean_last_name(self):
        return _validate_required_stripped(
            self.cleaned_data.get("last_name", ""), str(_("Last name"))
        )

    def clean_job_title(self):
        return _validate_required_stripped(
            self.cleaned_data.get("job_title", ""), str(_("Job title"))
        )

    def clean_email(self):
        return _validate_email_format(self.cleaned_data.get("email", ""))

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.pk:
            user.email = _normalize_email(user.email)
            user.save(update_fields=["email"])
        if user.pk:
            apply_user_profile_form(user, self.cleaned_data)
        return user


class AdminUserChangeForm(UserChangeForm):
    """User edit form — password is changed via a separate form on the change page."""

    job_title = forms.CharField(
        label=_("Job title"),
        required=True,
        max_length=128,
        help_text=_("The user's job title or position."),
    )
    two_factor_enabled = forms.BooleanField(
        label=_("Email two-factor authentication"),
        required=False,
        help_text=_("When enabled, a one-time code is sent by email at sign-in."),
    )
    password_expiry_enabled = forms.BooleanField(
        label=_("Require password change every 6 months"),
        required=False,
        help_text=_("When enabled, the user must change their password every 180 days."),
    )
    receive_workflow_emails = forms.BooleanField(
        label=_("Receive workflow notification emails"),
        required=False,
        help_text=_(
            "Superuser accounts only. Enable to receive dashboard workflow emails "
            "(pending review, publish, etc.) on this support account."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "password" in self.fields:
            del self.fields["password"]
        apply_is_staff_labels(self)
        self.fields["job_title"].initial = _initial_job_title(self.instance)
        profile = getattr(self.instance, "profile", None)
        self.fields["two_factor_enabled"].initial = (
            profile.two_factor_enabled if profile else False
        )
        self.fields["password_expiry_enabled"].initial = (
            profile.password_expiry_enabled if profile else True
        )
        workflow_field = self.fields.pop("receive_workflow_emails", None)
        show_workflow_emails = self.instance.is_superuser or _form_data_requests_superuser(
            self
        )
        if show_workflow_emails and workflow_field is not None:
            self.fields["receive_workflow_emails"] = workflow_field
            self.fields["receive_workflow_emails"].initial = (
                profile.receive_workflow_emails if profile else False
            )
        if "email" in self.fields:
            self.fields["email"].required = True
            self.fields["email"].widget = forms.EmailInput(
                attrs={"autocomplete": "email", "inputmode": "email"},
            )
        if "first_name" in self.fields:
            self.fields["first_name"].required = True
        if "last_name" in self.fields:
            self.fields["last_name"].required = True

    def clean_username(self):
        return _validate_username(self.cleaned_data.get("username", ""))

    def clean_first_name(self):
        return _validate_required_stripped(
            self.cleaned_data.get("first_name", ""), str(_("First name"))
        )

    def clean_last_name(self):
        return _validate_required_stripped(
            self.cleaned_data.get("last_name", ""), str(_("Last name"))
        )

    def clean_job_title(self):
        return _validate_required_stripped(
            self.cleaned_data.get("job_title", ""), str(_("Job title"))
        )

    def clean_email(self):
        exclude_id = self.instance.pk if self.instance and self.instance.pk else None
        return _validate_email_format(
            self.cleaned_data.get("email", ""),
            exclude_user_id=exclude_id,
        )

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.pk:
            user.email = _normalize_email(user.email)
            user.save(update_fields=["email"])
        if user.pk:
            apply_user_profile_form(user, self.cleaned_data)
        return user


class MandatoryPasswordAdminChangeForm(SetPasswordMixin, forms.Form):
    """Reset a user's password in admin — password auth cannot be disabled."""

    required_css_class = "required"
    password1, password2 = SetPasswordMixin.create_password_fields()
    send_credentials_email = forms.BooleanField(
        label=_("Send new password by email"),
        required=False,
        initial=False,
        help_text=_(
            "When checked, the new password is emailed to the user. "
            "They must change it on next sign-in."
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs["autofocus"] = True
        _clear_password_help_text(self)

    def clean(self):
        self.validate_passwords()
        self.validate_password_for_user(self.user)
        return super().clean()

    def save(self, commit=True):
        return self.set_password_and_save(self.user, commit=commit)

    @property
    def changed_data(self):
        data = super().changed_data
        if "password1" in data and "password2" in data:
            return ["password"]
        return []


def company_attachment_field_name(kind: str) -> str:
    return f"att_{kind}"


LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_ALLOWED_CONTENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)


class _CompanyAdminFormBase(forms.ModelForm):
    """Company form with attachment enable/disable toggles on add and edit."""

    class Meta:
        model = Company
        fields = (
            "code",
            "name",
            "company_kind",
            "parent",
            "logo",
            "is_active",
            "excel_company_names",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from audit_app.company_access import active_main_companies

        self.fields["parent"].queryset = active_main_companies().exclude(
            pk=self.instance.pk if self.instance.pk else None
        )
        self.fields["parent"].required = False
        self.fields["logo"].required = not bool(self.instance.pk and self.instance.logo)
        kind = (
            (self.data.get("company_kind") if self.data else None)
            or (self.instance.company_kind if self.instance.pk else COMPANY_KIND_MAIN)
        )
        if kind == COMPANY_KIND_SUBSIDIARY:
            for code in ATTACHMENT_KIND_CODES:
                self.fields.pop(company_attachment_field_name(code), None)
        elif self.instance.pk:
            for code, _ in ATTACHMENT_KIND_CHOICES:
                field_name = company_attachment_field_name(code)
                setting = self.instance.attachment_settings.filter(
                    attachment_kind=code
                ).first()
                if setting is not None:
                    self.fields[field_name].initial = setting.is_enabled

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo is False:
            return self.instance.logo if self.instance.pk else None
        if not logo:
            if self.instance.pk and self.instance.logo:
                return self.instance.logo
            raise forms.ValidationError(_("Company logo is required."))
        content_type = getattr(logo, "content_type", "") or ""
        if content_type and content_type not in LOGO_ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError(
                _("Logo must be PNG, JPEG, WebP, or GIF.")
            )
        size = getattr(logo, "size", 0) or 0
        if size > LOGO_MAX_BYTES:
            raise forms.ValidationError(
                _("Logo file is too large (maximum %(max)s MB).")
                % {"max": LOGO_MAX_BYTES // (1024 * 1024)}
            )
        return logo

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("company_kind") or COMPANY_KIND_MAIN
        parent = cleaned.get("parent")
        if kind == COMPANY_KIND_SUBSIDIARY:
            if parent is None:
                self.add_error(
                    "parent",
                    _("Select the parent main company for a subsidiary."),
                )
        else:
            cleaned["parent"] = None
            if parent is not None:
                self.add_error(
                    "parent",
                    _("Main companies cannot have a parent."),
                )
        return cleaned

    def save_attachment_settings(self, company: Company) -> None:
        """Persist attachment toggles (Admin saves the company with commit=False first)."""
        if company.is_subsidiary:
            return
        if not company.pk or not getattr(self, "cleaned_data", None):
            return
        for code in ATTACHMENT_KIND_CODES:
            field_name = company_attachment_field_name(code)
            enabled = self.cleaned_data.get(field_name, False)
            CompanyAttachmentSetting.objects.update_or_create(
                company=company,
                attachment_kind=code,
                defaults={"is_enabled": bool(enabled)},
            )

    def save(self, commit=True):
        company = super().save(commit=commit)
        if commit and company.pk:
            self.save_attachment_settings(company)
        return company


CompanyAdminForm = type(
    "CompanyAdminForm",
    (_CompanyAdminFormBase,),
    {
        company_attachment_field_name(code): forms.BooleanField(
            label=label,
            required=False,
            initial=True,
        )
        for code, label in ATTACHMENT_KIND_CHOICES
    },
)
