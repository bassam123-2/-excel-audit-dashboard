from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0009_userprofile_preferred_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark")],
                default="light",
                help_text="Light or dark appearance for the dashboard and admin site.",
                max_length=5,
                verbose_name="Preferred theme",
            ),
        ),
    ]
