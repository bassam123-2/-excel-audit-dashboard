# Generated manually — repairs partial DB state on servers where
# audit_app.0011 was not fully applied (missing company_id columns).

from django.db import migrations


def _table_columns(schema_editor, table_name: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table_name
        )
    return {column.name for column in description}


def repair_company_related_schema(apps, schema_editor):
    models_to_check = (
        ("CompanyAttachmentSetting", ("company",)),
        ("CompanyMembership", ("company", "user")),
    )

    for model_name, field_names in models_to_check:
        model = apps.get_model("audit_app", model_name)
        table = model._meta.db_table
        try:
            columns = _table_columns(schema_editor, table)
        except Exception:
            continue

        for field_name in field_names:
            column = f"{field_name}_id"
            if column in columns:
                continue
            field = model._meta.get_field(field_name)
            schema_editor.add_field(model, field)


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0014_alter_companymembership_can_view"),
    ]

    operations = [
        migrations.RunPython(repair_company_related_schema, migrations.RunPython.noop),
    ]
