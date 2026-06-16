from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0008_user_email_unique_required_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_language",
            field=models.CharField(
                choices=[("en", "English"), ("ar", "Arabic")],
                default="en",
                help_text="UI language for the dashboard and administration site.",
                max_length=2,
                verbose_name="Preferred language",
            ),
        ),
    ]
