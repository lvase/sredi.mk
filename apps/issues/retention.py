from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.issues.models import (
    AuditLog,
    DataRetentionPolicy,
    Issue,
    SubmissionRateLimit,
)


def _policy_for(municipality):
    policy, _ = DataRetentionPolicy.objects.get_or_create(municipality=municipality)
    return policy


def preview_retention(municipalities, now=None):
    now = now or timezone.now()
    previews = []
    for municipality in municipalities:
        policy = _policy_for(municipality)
        contact_cutoff = now - timedelta(days=policy.contact_retention_days)
        attachment_cutoff = now - timedelta(days=policy.attachment_retention_days)
        previews.append(
            {
                "municipality": municipality,
                "policy": policy,
                "contact_cutoff": contact_cutoff,
                "attachment_cutoff": attachment_cutoff,
                "contact_count": Issue.objects.filter(
                    municipality=municipality,
                    closed_at__isnull=False,
                    closed_at__lte=contact_cutoff,
                    contact_anonymized_at__isnull=True,
                ).count(),
                "attachment_issue_count": Issue.objects.filter(
                    municipality=municipality,
                    closed_at__isnull=False,
                    closed_at__lte=attachment_cutoff,
                    attachments_deleted_at__isnull=True,
                ).count(),
                "rate_limit_count": SubmissionRateLimit.objects.filter(
                    municipality=municipality,
                    updated_at__lte=now - timedelta(hours=48),
                ).count(),
            }
        )
    return previews


def apply_retention(municipalities, actor, now=None):
    now = now or timezone.now()
    summaries = []
    for municipality in municipalities:
        policy = _policy_for(municipality)
        contact_cutoff = now - timedelta(days=policy.contact_retention_days)
        attachment_cutoff = now - timedelta(days=policy.attachment_retention_days)
        contact_count = 0
        attachment_issue_count = 0
        attachment_count = 0

        contact_ids = list(
            Issue.objects.filter(
                municipality=municipality,
                closed_at__isnull=False,
                closed_at__lte=contact_cutoff,
                contact_anonymized_at__isnull=True,
            ).values_list("pk", flat=True)
        )
        for issue_id in contact_ids:
            with transaction.atomic():
                issue = Issue.objects.select_for_update().get(pk=issue_id)
                if issue.contact_anonymized_at:
                    continue
                issue.citizen_name = ""
                issue.citizen_email = ""
                issue.citizen_phone = ""
                issue.submitted_ip_hash = ""
                issue.submitted_user_agent_hash = ""
                issue.is_anonymous = True
                issue.contact_anonymized_at = now
                issue.save(
                    update_fields=[
                        "citizen_name",
                        "citizen_email",
                        "citizen_phone",
                        "submitted_ip_hash",
                        "submitted_user_agent_hash",
                        "is_anonymous",
                        "contact_anonymized_at",
                        "updated_at",
                    ]
                )
                AuditLog.objects.create(
                    municipality=municipality,
                    actor=actor,
                    action="issue_contact_anonymized",
                    object_type="Issue",
                    object_id=str(issue.pk),
                    metadata={"cutoff": contact_cutoff.isoformat()},
                )
                contact_count += 1

        attachment_issue_ids = list(
            Issue.objects.filter(
                municipality=municipality,
                closed_at__isnull=False,
                closed_at__lte=attachment_cutoff,
                attachments_deleted_at__isnull=True,
            ).values_list("pk", flat=True)
        )
        for issue_id in attachment_issue_ids:
            with transaction.atomic():
                issue = Issue.objects.select_for_update().get(pk=issue_id)
                if issue.attachments_deleted_at:
                    continue
                attachments = list(issue.attachments.all())
                for attachment in attachments:
                    if attachment.image.name:
                        attachment.image.storage.delete(attachment.image.name)
                    attachment.delete()
                    attachment_count += 1
                issue.attachments_deleted_at = now
                issue.save(update_fields=["attachments_deleted_at", "updated_at"])
                AuditLog.objects.create(
                    municipality=municipality,
                    actor=actor,
                    action="issue_attachments_deleted",
                    object_type="Issue",
                    object_id=str(issue.pk),
                    metadata={
                        "attachment_count": len(attachments),
                        "cutoff": attachment_cutoff.isoformat(),
                    },
                )
                attachment_issue_count += 1

        rate_limit_count, _ = SubmissionRateLimit.objects.filter(
            municipality=municipality,
            updated_at__lte=now - timedelta(hours=48),
        ).delete()
        summary = {
            "municipality": municipality,
            "contact_count": contact_count,
            "attachment_issue_count": attachment_issue_count,
            "attachment_count": attachment_count,
            "rate_limit_count": rate_limit_count,
            "contact_cutoff": contact_cutoff,
            "attachment_cutoff": attachment_cutoff,
        }
        AuditLog.objects.create(
            municipality=municipality,
            actor=actor,
            action="data_retention_applied",
            object_type="Municipality",
            object_id=str(municipality.pk),
            metadata={
                "contact_count": contact_count,
                "attachment_issue_count": attachment_issue_count,
                "attachment_count": attachment_count,
                "rate_limit_count": rate_limit_count,
                "contact_cutoff": contact_cutoff.isoformat(),
                "attachment_cutoff": attachment_cutoff.isoformat(),
            },
        )
        summaries.append(summary)
    return summaries
