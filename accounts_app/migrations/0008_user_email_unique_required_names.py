"""Unique email (DB index) and normalized user names."""
from __future__ import annotations

from django.db import migrations


def fill_empty_user_names(apps, schema_editor):
    User = apps.get_model("auth", "User")
    for user in User.objects.filter(first_name=""):
        user.first_name = user.username or "User"
        user.save(update_fields=["first_name"])
    for user in User.objects.filter(last_name=""):
        user.last_name = "—"
        user.save(update_fields=["last_name"])
    for user in User.objects.exclude(email=""):
        normalized = user.email.strip().lower()
        if normalized != user.email:
            user.email = normalized
            user.save(update_fields=["email"])


def add_unique_email_index(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_unique "
            "ON auth_user (email COLLATE NOCASE) WHERE email != ''"
        )
    elif vendor == "mysql":
        schema_editor.execute(
            "ALTER TABLE auth_user ADD UNIQUE KEY auth_user_email_unique (email)"
        )
    else:
        schema_editor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_unique ON auth_user (email)"
        )


def drop_unique_email_index(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute("DROP INDEX IF EXISTS auth_user_email_unique")
    elif vendor == "mysql":
        schema_editor.execute(
            "ALTER TABLE auth_user DROP INDEX auth_user_email_unique"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS auth_user_email_unique")


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("accounts_app", "0007_userprofile_security_fields"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(fill_empty_user_names, migrations.RunPython.noop),
        migrations.RunPython(add_unique_email_index, drop_unique_email_index),
    ]
