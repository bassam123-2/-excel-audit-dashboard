"""Admin user forms — password authentication is always required."""

from django import forms
from django.contrib.auth.forms import SetPasswordMixin, UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from accounts_app.models import UserProfile

from audit_app.models import ATTACHMENT_KIND_CHOICES, ATTACHMENT_KIND_CODES, Company, CompanyAttachmentSetting

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


def _validate_email_format(email: str) -> str:
    email = (email or "").strip()
    if not email:
        raise forms.ValidationError(_("Email address is required."))
    try:
        validate_email(email)
    except DjangoValidationError as exc:
        raise forms.ValidationError(_("Enter a valid email address.")) from exc
    return email


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


def _initial_job_title(user) -> str:
    if not user.pk:
        return ""
    try:
        return user.profile.job_title
    except UserProfile.DoesNotExist:
        return ""


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
        required=False,
        max_length=150,
    )
    last_name = forms.CharField(
        label=_("Last name"),
        required=False,
        max_length=150,
    )
    job_title = forms.CharField(
        label=_("Job title"),
        required=False,
        max_length=128,
        help_text=_("The user's job title or position."),
    )
    two_factor_enabled = forms.BooleanField(
        label=_("Email two-factor authentication"),
        required=False,
        initial=False,
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

    def clean_email(self):
        return _validate_email_format(self.cleaned_data.get("email", ""))

    def save(self, commit=True):
        user = super().save(commit=commit)
        _save_user_job_title(user, self.cleaned_data.get("job_title", ""))
        _save_user_two_factor(user, self.cleaned_data.get("two_factor_enabled", False))
        _save_user_password_expiry(
            user, self.cleaned_data.get("password_expiry_enabled", True)
        )
        return user


class AdminUserChangeForm(UserChangeForm):
    """User edit form — password is changed via a separate form on the change page."""

    job_title = forms.CharField(
        label=_("Job title"),
        required=False,
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
        if "email" in self.fields:
            self.fields["email"].required = True
            self.fields["email"].widget = forms.EmailInput(
                attrs={"autocomplete": "email", "inputmode": "email"},
            )

    def clean_email(self):
        return _validate_email_format(self.cleaned_data.get("email", ""))

    def save(self, commit=True):
        user = super().save(commit=commit)
        _save_user_job_title(user, self.cleaned_data.get("job_title", ""))
        _save_user_two_factor(
            user, self.cleaned_data.get("two_factor_enabled", False)
        )
        _save_user_password_expiry(
            user, self.cleaned_data.get("password_expiry_enabled", True)
        )
        return user


class MandatoryPasswordAdminChangeForm(SetPasswordMixin, forms.Form):
    """Reset a user's password in admin — password auth cannot be disabled."""

    required_css_class = "required"
    password1, password2 = SetPasswordMixin.create_password_fields()

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


class _CompanyAdminFormBase(forms.ModelForm):
    """Company form with attachment enable/disable toggles on add and edit."""

    class Meta:
        model = Company
        fields = ("code", "name", "is_active", "excel_company_names")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            for code, _ in ATTACHMENT_KIND_CHOICES:
                field_name = company_attachment_field_name(code)
                setting = self.instance.attachment_settings.filter(
                    attachment_kind=code
                ).first()
                if setting is not None:
                    self.fields[field_name].initial = setting.is_enabled

    def save_attachment_settings(self, company: Company) -> None:
        """Persist attachment toggles (Admin saves the company with commit=False first)."""
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
