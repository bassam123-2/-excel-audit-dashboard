from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("audit_app", "0005_add_dashboard_template_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardReview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("body", models.TextField(verbose_name="Review text")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Created at"),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dashboard_reviews",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Author",
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="audit_app.dashboard",
                        verbose_name="Dashboard",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dashboard review",
                "verbose_name_plural": "Dashboard reviews",
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(
                        fields=["dashboard", "created_at"],
                        name="audit_app_d_dashboa_0f8b0d_idx",
                    )
                ],
            },
        ),
    ]
