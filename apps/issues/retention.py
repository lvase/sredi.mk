import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.issues.models import (
    FINAL_ISSUE_STATUSES,
    AttachmentDeletionState,
    AuditLog,
    DataRetentionPolicy,
    Issue,
    IssueAttachment,
    ReceiptDelivery,
    SubmissionRateLimit,
)

logger = logging.getLogger(__name__)


def _policy_for(municipality):
    policy, _ = DataRetentionPolicy.objects.get_or_create(municipality=municipality)
    return policy


def _eligible_issue_filter(policy, now):
    cutoff = now - timedelta(days=policy.attachment_retention_days)
    return Q(
        issue__status__in=FINAL_ISSUE_STATUSES,
        issue__attachment_retention_started_at__isnull=False,
        issue__attachment_retention_started_at__lte=cutoff,
    ) | Q(
        ~Q(issue__status__in=FINAL_ISSUE_STATUSES),
        issue__submitted_at__lte=cutoff,
    )


def eligible_attachments(municipality, now=None):
    now = now or timezone.now()
    policy = _policy_for(municipality)
    return IssueAttachment.objects.filter(
        issue__municipality=municipality,
        issue__legal_hold_active=False,
        deletion_state__in=[
            AttachmentDeletionState.ACTIVE,
            AttachmentDeletionState.PENDING,
            AttachmentDeletionState.FAILED,
        ],
    ).filter(_eligible_issue_filter(policy, now))


def anonymize_expired_contacts(municipality, now=None, batch_size=100):
    now = now or timezone.now()
    policy = _policy_for(municipality)
    cutoff = now - timedelta(days=policy.contact_retention_days)
    issue_ids = list(
        Issue.objects.filter(
            municipality=municipality,
            legal_hold_active=False,
            closed_at__isnull=False,
            closed_at__lte=cutoff,
            contact_anonymized_at__isnull=True,
        )
        .order_by("closed_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    if not issue_ids:
        return 0
    updated = Issue.objects.filter(pk__in=issue_ids).update(
        citizen_name="",
        citizen_email="",
        citizen_phone="",
        submitted_ip_hash="",
        submitted_user_agent_hash="",
        is_anonymous=True,
        contact_anonymized_at=now,
    )
    ReceiptDelivery.objects.filter(issue_id__in=issue_ids).update(recipient="")
    return updated


def preview_retention(municipalities, now=None):
    now = now or timezone.now()
    previews = []
    for municipality in municipalities:
        policy = _policy_for(municipality)
        contact_cutoff = now - timedelta(days=policy.contact_retention_days)
        eligible = eligible_attachments(municipality, now)
        previews.append(
            {
                "municipality": municipality,
                "policy": policy,
                "contact_cutoff": contact_cutoff,
                "attachment_cutoff": now - timedelta(days=policy.attachment_retention_days),
                "contact_count": Issue.objects.filter(
                    municipality=municipality,
                    legal_hold_active=False,
                    closed_at__isnull=False,
                    closed_at__lte=contact_cutoff,
                    contact_anonymized_at__isnull=True,
                ).count(),
                "attachment_issue_count": eligible.values("issue_id").distinct().count(),
                "attachment_count": eligible.count(),
                "rate_limit_count": SubmissionRateLimit.objects.filter(
                    municipality=municipality,
                    updated_at__lte=now - timedelta(hours=48),
                ).count(),
            }
        )
    return previews


def _still_eligible(attachment, now):
    issue = attachment.issue
    if issue.legal_hold_active:
        return False
    policy = _policy_for(issue.municipality)
    cutoff = now - timedelta(days=policy.attachment_retention_days)
    if issue.status in FINAL_ISSUE_STATUSES:
        return bool(
            issue.attachment_retention_started_at
            and issue.attachment_retention_started_at <= cutoff
        )
    return issue.submitted_at <= cutoff


def process_attachment_deletion(attachment_id, now=None, reason="retention_policy"):
    now = now or timezone.now()
    with transaction.atomic():
        attachment = (
            IssueAttachment.objects.select_for_update()
            .select_related("issue", "issue__municipality")
            .get(pk=attachment_id)
        )
        if attachment.deletion_state == AttachmentDeletionState.DELETED:
            return True
        if not _still_eligible(attachment, now):
            if attachment.deletion_state == AttachmentDeletionState.PENDING:
                attachment.deletion_state = AttachmentDeletionState.ACTIVE
                attachment.deletion_started_at = None
                attachment.deletion_reason = ""
                attachment.save(
                    update_fields=[
                        "deletion_state",
                        "deletion_started_at",
                        "deletion_reason",
                    ]
                )
            return False
        attachment.deletion_state = AttachmentDeletionState.PENDING
        attachment.deletion_started_at = attachment.deletion_started_at or now
        attachment.deletion_reason = reason
        attachment.deletion_error = ""
        attachment.save(
            update_fields=[
                "deletion_state",
                "deletion_started_at",
                "deletion_reason",
                "deletion_error",
            ]
        )
        storage = attachment.image.storage
        storage_name = attachment.image.name
        issue_id = attachment.issue_id
        municipality_id = attachment.issue.municipality_id

    try:
        if storage_name and storage.exists(storage_name):
            storage.delete(storage_name)
    except Exception as exc:
        with transaction.atomic():
            failed = IssueAttachment.objects.select_for_update().get(pk=attachment_id)
            failed.deletion_state = AttachmentDeletionState.FAILED
            failed.deletion_error = exc.__class__.__name__[:1000]
            failed.save(update_fields=["deletion_state", "deletion_error"])
        logger.exception(
            "attachment_retention_delete_failed",
            extra={"issue_attachment_id": attachment_id},
        )
        return False

    with transaction.atomic():
        deleted = IssueAttachment.objects.select_for_update().get(pk=attachment_id)
        deleted.deletion_state = AttachmentDeletionState.DELETED
        deleted.deleted_at = now
        deleted.deletion_error = ""
        deleted.save(update_fields=["deletion_state", "deleted_at", "deletion_error"])
        remaining = IssueAttachment.objects.filter(issue_id=issue_id).exclude(
            deletion_state=AttachmentDeletionState.DELETED
        )
        if not remaining.exists():
            Issue.objects.filter(pk=issue_id).update(attachments_deleted_at=now)
        AuditLog.objects.create(
            municipality_id=municipality_id,
            action="issue_attachment_deleted",
            object_type="IssueAttachment",
            object_id=str(attachment_id),
            metadata={"issue_id": issue_id, "reason": reason},
        )
        logger.info(
            "issue_attachment_retained_tombstone",
            extra={
                "issue_attachment_id": attachment_id,
                "issue_id": issue_id,
                "municipality_id": municipality_id,
            },
        )
    return True


def run_retention_batch(municipalities, now=None, batch_size=100, retry_failed=True):
    now = now or timezone.now()
    processed = 0
    failed = 0
    for municipality in municipalities:
        remaining = batch_size - processed - failed
        if remaining <= 0:
            break
        eligible = eligible_attachments(municipality, now)
        if not retry_failed:
            eligible = eligible.exclude(deletion_state=AttachmentDeletionState.FAILED)
        attachment_ids = list(
            eligible.order_by("uploaded_at", "pk").values_list("pk", flat=True)[:remaining]
        )
        for attachment_id in attachment_ids:
            if process_attachment_deletion(attachment_id, now=now):
                processed += 1
            else:
                failed += 1
    contact_count = sum(
        anonymize_expired_contacts(municipality, now=now, batch_size=batch_size)
        for municipality in municipalities
    )
    return {"processed": processed, "failed": failed, "contacts_anonymized": contact_count}


def apply_retention(municipalities, actor, now=None):
    """Synchronous service for maintenance commands; HTTP admin queues the Celery task."""
    now = now or timezone.now()
    summaries = []
    for municipality in municipalities:
        before = preview_retention([municipality], now)[0]
        result = run_retention_batch([municipality], now=now, batch_size=100)
        stale_rate_limits, _ = SubmissionRateLimit.objects.filter(
            municipality=municipality,
            updated_at__lte=now - timedelta(hours=48),
        ).delete()
        summary = {
            "municipality": municipality,
            "contact_count": result["contacts_anonymized"],
            "attachment_issue_count": before["attachment_issue_count"],
            "attachment_count": result["processed"],
            "rate_limit_count": stale_rate_limits,
            "contact_cutoff": before["contact_cutoff"],
            "attachment_cutoff": before["attachment_cutoff"],
        }
        AuditLog.objects.create(
            municipality=municipality,
            actor=actor,
            action="data_retention_applied",
            object_type="Municipality",
            object_id=str(municipality.pk),
            metadata={
                "attachment_count": result["processed"],
                "attachment_failed": result["failed"],
                "contact_count": result["contacts_anonymized"],
                "rate_limit_count": stale_rate_limits,
            },
        )
        summaries.append(summary)
    return summaries
