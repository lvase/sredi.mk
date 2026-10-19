import django.contrib.postgres.indexes
import django.contrib.postgres.operations
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def normalize_and_validate(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")
    seen = {}
    for issue in Issue.objects.only("pk", "tracking_code").iterator():
        normalized = issue.tracking_code.upper()
        if normalized in seen and seen[normalized] != issue.pk:
            raise RuntimeError(f"Tracking codes collide after uppercasing: {normalized}")
        seen[normalized] = issue.pk
    for issue in Issue.objects.only("pk", "tracking_code").iterator():
        normalized = issue.tracking_code.upper()
        if issue.tracking_code != normalized:
            Issue.objects.filter(pk=issue.pk).update(tracking_code=normalized)

    SlaPolicy = apps.get_model("issues", "SlaPolicy")
    default_duplicates = (
        SlaPolicy.objects.filter(category__isnull=True)
        .values("municipality_id")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
    )
    category_duplicates = (
        SlaPolicy.objects.filter(category__isnull=False)
        .values("municipality_id", "category_id")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
    )
    if default_duplicates.exists() or category_duplicates.exists():
        raise RuntimeError("Duplicate SLA policies must be resolved before migration")

    DataRetentionPolicy = apps.get_model("issues", "DataRetentionPolicy")
    DataRetentionPolicy.objects.filter(attachment_retention_days=1825).update(
        attachment_retention_days=90
    )


def backfill_retention_start(apps, schema_editor):
    schema_editor.execute(
        """
        UPDATE issues_issue AS issue
        SET attachment_retention_started_at = COALESCE(
            (
                SELECT MIN(event.created_at)
                FROM issues_issuestatusevent AS event
                WHERE event.issue_id = issue.id
                  AND event.to_status IN (
                    'resolved', 'closed', 'duplicate', 'rejected_spam', 'not_jurisdiction'
                  )
            ),
            issue.resolved_at,
            issue.closed_at,
            issue.submitted_at
        )
        WHERE issue.status IN (
            'resolved', 'closed', 'duplicate', 'rejected_spam', 'not_jurisdiction'
        )
          AND issue.attachment_retention_started_at IS NULL
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0006_issueattachment_processing_metadata"),
        ("municipalities", "0004_municipality_statistics_version"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        django.contrib.postgres.operations.TrigramExtension(),
        migrations.RunPython(normalize_and_validate, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dataretentionpolicy",
            name="attachment_retention_days",
            field=models.PositiveIntegerField(default=90),
        ),
        migrations.AlterField(
            model_name="issue",
            name="description",
            field=models.TextField(max_length=5000),
        ),
        migrations.AlterField(
            model_name="issue",
            name="internal_note",
            field=models.TextField(blank=True, max_length=10000),
        ),
        migrations.AlterField(
            model_name="issue",
            name="public_resolution_note",
            field=models.TextField(blank=True, max_length=5000),
        ),
        migrations.AlterField(
            model_name="issuecomment",
            name="body",
            field=models.TextField(max_length=5000),
        ),
        migrations.AlterField(
            model_name="issuestatusevent",
            name="note",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AddField(
            model_name="issue",
            name="attachment_retention_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_retention_start, migrations.RunPython.noop),
        migrations.AddField(
            model_name="issue",
            name="legal_hold_active",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="issue",
            name="legal_hold_reason",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AddField(
            model_name="issue",
            name="legal_hold_set_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issue",
            name="legal_hold_set_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="issue_legal_holds",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="issue",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="deletion_state",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("deletion_pending", "Deletion pending"),
                    ("deleted", "Deleted"),
                    ("deletion_failed", "Deletion failed"),
                ],
                default="active",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="deletion_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="deletion_reason",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="deletion_error",
            field=models.TextField(blank=True, max_length=1000),
        ),
        migrations.CreateModel(
            name="ReceiptDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recipient", models.EmailField(max_length=254)),
                ("state", models.CharField(choices=[("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed")], default="queued", max_length=16)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("queued_at", models.DateTimeField(auto_now_add=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("issue", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="receipt_deliveries", to="issues.issue")),
            ],
        ),
        migrations.AddConstraint(
            model_name="slapolicy",
            constraint=models.UniqueConstraint(condition=models.Q(("category__isnull", True)), fields=("municipality",), name="unique_default_sla_per_mun"),
        ),
        migrations.AddConstraint(
            model_name="slapolicy",
            constraint=models.UniqueConstraint(condition=models.Q(("category__isnull", False)), fields=("municipality", "category"), name="unique_category_sla_per_mun"),
        ),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "submitted_at"], name="iss_mun_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "status", "submitted_at"], name="iss_mun_status_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "assigned_to", "submitted_at"], name="iss_mun_assign_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "assigned_department", "submitted_at"], name="iss_mun_dept_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "submitted_ip_hash", "submitted_at"], name="iss_mun_ip_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["municipality", "is_spam", "submitted_at"], name="iss_mun_spam_sub_idx")),
        migrations.AddIndex(model_name="issue", index=models.Index(fields=["attachment_retention_started_at"], name="iss_retention_start_idx")),
        migrations.AddIndex(model_name="issueattachment", index=models.Index(fields=["deletion_state", "deleted_at"], name="attach_state_del_idx")),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["object_type", "object_id", "created_at"], name="audit_object_created_idx")),
        migrations.AddIndex(model_name="receiptdelivery", index=models.Index(fields=["state", "queued_at"], name="receipt_state_queue_idx")),
        migrations.AddIndex(model_name="issue", index=django.contrib.postgres.indexes.GinIndex(fields=["title"], name="iss_title_trgm_idx", opclasses=["gin_trgm_ops"])),
        migrations.AddIndex(model_name="issue", index=django.contrib.postgres.indexes.GinIndex(fields=["location_text"], name="iss_location_trgm_idx", opclasses=["gin_trgm_ops"])),
    ]
