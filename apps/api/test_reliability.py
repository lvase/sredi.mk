import smtplib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffRole
from apps.issues.models import (
    AttachmentDeletionState,
    AuditLog,
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueStatus,
    ReceiptDelivery,
    ReceiptDeliveryState,
)
from apps.issues.retention import eligible_attachments, process_attachment_deletion
from apps.issues.tasks import send_receipt_email
from apps.municipalities.models import Municipality, Settlement
from config.throttling import SharedThrottleUnavailable


@pytest.fixture
def reliability_issue():
    municipality = Municipality.objects.create(name="Општина Сигурност", slug="reliability")
    settlement = Settlement.objects.create(municipality=municipality, name="Центар")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Пријава за проверка",
        description="Опис",
        location_text="Центар",
        citizen_email="citizen@example.com",
    )
    return municipality, issue


@pytest.mark.django_db
def test_stale_status_update_returns_conflict_without_partial_history(client, reliability_issue):
    municipality, issue = reliability_issue
    coordinator = get_user_model().objects.create_user(username="reliable", password="testpass")
    StaffProfile.objects.create(
        user=coordinator,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    client.force_login(coordinator)

    first = client.post(
        f"/api/staff/issues/{issue.pk}/status/",
        {"status": IssueStatus.ACCEPTED, "expected_version": issue.version},
    )
    assert first.status_code == 200
    assert first.json()["data"]["version"] == 2

    stale = client.post(
        f"/api/staff/issues/{issue.pk}/status/",
        {"status": IssueStatus.IN_PROGRESS, "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["meta"]["current_version"] == 2
    issue.refresh_from_db()
    assert issue.status == IssueStatus.ACCEPTED
    assert issue.status_events.count() == 1
    assert AuditLog.objects.filter(action="issue_status_changed", object_id=str(issue.pk)).count() == 1


@pytest.mark.django_db
def test_legal_hold_blocks_retention_and_release_makes_attachment_eligible(
    client, tmp_path, reliability_issue
):
    municipality, issue = reliability_issue
    coordinator = get_user_model().objects.create_user(username="hold-owner", password="testpass")
    StaffProfile.objects.create(
        user=coordinator,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    Issue.objects.filter(pk=issue.pk).update(
        submitted_at=timezone.now() - timedelta(days=91)
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        attachment = IssueAttachment.objects.create(
            issue=issue,
            image=SimpleUploadedFile("hold.jpg", b"photo", content_type="image/jpeg"),
        )
        client.force_login(coordinator)
        held = client.post(
            f"/api/staff/issues/{issue.pk}/legal-hold/",
            {"active": True, "reason": "Судска постапка", "expected_version": issue.version},
            content_type="application/json",
        )
        assert held.status_code == 200
        assert not eligible_attachments(municipality).filter(pk=attachment.pk).exists()

        released = client.post(
            f"/api/staff/issues/{issue.pk}/legal-hold/",
            {
                "active": False,
                "reason": "",
                "expected_version": held.json()["data"]["version"],
            },
            content_type="application/json",
        )
        assert released.status_code == 200
        assert eligible_attachments(municipality).filter(pk=attachment.pk).exists()


@pytest.mark.django_db
def test_interrupted_pending_deletion_treats_missing_storage_object_as_success(
    tmp_path, reliability_issue
):
    _, issue = reliability_issue
    Issue.objects.filter(pk=issue.pk).update(
        submitted_at=timezone.now() - timedelta(days=91)
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        attachment = IssueAttachment.objects.create(
            issue=issue,
            image=SimpleUploadedFile("pending.jpg", b"photo", content_type="image/jpeg"),
            deletion_state=AttachmentDeletionState.PENDING,
            deletion_started_at=timezone.now() - timedelta(hours=1),
        )
        attachment.image.storage.delete(attachment.image.name)

        assert process_attachment_deletion(attachment.pk) is True
        attachment.refresh_from_db()
        assert attachment.deletion_state == AttachmentDeletionState.DELETED
        assert attachment.deleted_at is not None


@pytest.mark.django_db
def test_submission_fails_closed_when_shared_throttle_is_unavailable(client, reliability_issue):
    municipality, issue = reliability_issue
    payload = {
        "settlement": issue.settlement_id,
        "category": issue.category_id,
        "title": "Нова пријава",
        "description": "Опис",
        "location_text": "Центар",
        "consent": "on",
        "website": "",
    }
    with patch(
        "apps.issues.services.increment_fixed_window",
        side_effect=SharedThrottleUnavailable,
    ):
        response = client.post(f"/api/municipalities/{municipality.slug}/issues/", payload)

    assert response.status_code == 503
    assert response["Retry-After"] == "60"
    assert Issue.objects.filter(title="Нова пријава").count() == 0


@pytest.mark.django_db
def test_transient_receipt_failure_stays_queued_for_retry(reliability_issue):
    _, issue = reliability_issue
    delivery = ReceiptDelivery.objects.create(issue=issue, recipient=issue.citizen_email)

    with (
        patch("apps.issues.tasks.send_mail", side_effect=smtplib.SMTPException("temporary")),
        pytest.raises(smtplib.SMTPException),
    ):
        send_receipt_email.run(delivery.pk)

    delivery.refresh_from_db()
    assert delivery.state == ReceiptDeliveryState.QUEUED
    assert delivery.attempt_count == 1
    assert delivery.failed_at is None
