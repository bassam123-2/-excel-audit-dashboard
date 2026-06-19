from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0006_add_dashboard_review"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="dashboard",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("can_upload_files", "Can upload files and create dashboards"),
                    ("can_view_dashboards", "Can view dashboards"),
                    ("can_delete_dashboards", "Can delete dashboards"),
                ],
                "verbose_name": "Dashboard",
                "verbose_name_plural": "Dashboards",
            },
        ),
    ]
