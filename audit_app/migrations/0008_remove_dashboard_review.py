from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0007_add_delete_dashboard_permission"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DashboardReview",
        ),
    ]
