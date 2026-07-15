from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("municipalities", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="municipality",
            name="configuration_source",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="municipality",
            name="configuration_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="municipality",
            name="configuration_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="municipality",
            name="configuration_verified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="verified_municipality_configurations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
