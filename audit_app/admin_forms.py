"""Admin user forms — password authentication is always required."""

from django import forms
from django.contrib.auth.forms import SetPasswordMixin, UserChangeForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

IS_STAFF_LABEL = _("Admin")
IS_STAFF_HELP = _(
    "Designates whether this user has admin access to the administration site."
)


def apply_is_staff_labels(form: forms.BaseForm) -> None:
    if "is_staff" in form.fields:
        form.fields["is_staff"].label = IS_STAFF_LABEL
        form.fields["is_staff"].help_text = IS_STAFF_HELP


class MandatoryPasswordAdminCreationForm(UserCreationForm):
    """Create users in admin with a required password (no disable-password option)."""


class AdminUserChangeForm(UserChangeForm):
    """User edit form with is_staff relabeled as Admin."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_is_staff_labels(self)


class MandatoryPasswordAdminChangeForm(SetPasswordMixin, forms.Form):
    """Reset a user's password in admin — password auth cannot be disabled."""

    required_css_class = "required"
    password1, password2 = SetPasswordMixin.create_password_fields()

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs["autofocus"] = True

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
