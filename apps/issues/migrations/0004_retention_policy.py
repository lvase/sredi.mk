from django.db import migrations, models
import django.db.models.deletion


def create_default_policies(apps, schema_editor):
    Municipality = apps.get_model("municipalities", "Municipality")
    DataRetentionPolicy = apps.get_model("issues", "DataRetentionPolicy")
    for municipality in Municipality.objects.all():
        DataRetentionPolicy.objects.get_or_create(municipality=municipality)


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0003_issue_suspicious_reasons"),
        ("municipalities", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="attachments_deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issue",
            name="contact_anonymized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="DataRetentionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact_retention_days", models.PositiveIntegerField(default=365)),
                ("attachment_retention_days", models.PositiveIntegerField(default=1825)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "municipality",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="data_retention_policy",
                        to="municipalities.municipality",
                    ),
                ),
            ],
            options={
                "verbose_name": "data retention policy",
                "verbose_name_plural": "data retention policies",
            },
        ),
        migrations.RunPython(create_default_policies, migrations.RunPython.noop),
    ]
