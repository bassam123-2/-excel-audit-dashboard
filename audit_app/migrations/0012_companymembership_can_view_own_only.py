from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0011_company_and_security"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymembership",
            name="can_view_own_only",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "View only dashboards this user created in this company "
                    "(draft, rejected, or published)."
                ),
                verbose_name="Can view own dashboards only",
            ),
        ),
    ]
