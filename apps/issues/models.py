import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.municipalities.models import Department, Municipality, Settlement


def issue_attachment_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"issues/{instance.issue.tracking_code}/{secrets.token_hex(8)}{suffix}"


def validate_image_extension(file):
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    suffix = Path(file.name).suffix.lower()
    if suffix not in allowed:
        raise ValidationError("Дозволени се само JPG, PNG или WEBP фотографии.")


class IssueStatus(models.TextChoices):
    PENDING_TRIAGE = "pending_triage", "Чека проверка"
    ACCEPTED = "accepted", "Прифатена"
    ASSIGNED = "assigned", "Доделена"
    IN_PROGRESS = "in_progress", "Во тек"
    RESOLVED = "resolved", "Решена"
    CLOSED = "closed", "Затворена"
    DUPLICATE = "duplicate", "Дупликат"
    REJECTED_SPAM = "rejected_spam", "Одбиена / спам"
    NOT_JURISDICTION = "not_jurisdiction", "Не е во надлежност"
    WAITING_CITIZEN = "waiting_citizen", "Се чека граѓанин"
    WAITING_EXTERNAL = "waiting_external", "Се чека надворешна институција"
    PROCUREMENT_NEEDED = "procurement_needed", "Потребна е набавка"


class IssuePriority(models.TextChoices):
    LOW = "low", "Низок"
    NORMAL = "normal", "Нормален"
    HIGH = "high", "Висок"
    URGENT = "urgent", "Итен"


FINAL_ISSUE_STATUSES = {
    IssueStatus.RESOLVED,
    IssueStatus.CLOSED,
    IssueStatus.DUPLICATE,
    IssueStatus.REJECTED_SPAM,
    IssueStatus.NOT_JURISDICTION,
}


class AttachmentDeletionState(models.TextChoices):
    ACTIVE = "active", "Active"
    PENDING = "deletion_pending", "Deletion pending"
    DELETED = "deleted", "Deleted"
    FAILED = "deletion_failed", "Deletion failed"


class ReceiptDeliveryState(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class IssueCategory(models.Model):
    municipality = models.ForeignKey(
        Municipality, null=True, blank=True, related_name="issue_categories", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    default_department = models.ForeignKey(
        Department, null=True, blank=True, related_name="default_categories", on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("municipality", "name")]

    def __str__(self):
        return self.name


class Issue(models.Model):
    municipality = models.ForeignKey(Municipality, related_name="issues", on_delete=models.PROTECT)
    settlement = models.ForeignKey(Settlement, related_name="issues", on_delete=models.PROTECT)
    category = models.ForeignKey(IssueCategory, related_name="issues", on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    public_title = models.CharField(max_length=180, blank=True)
    public_title_approved_at = models.DateTimeField(null=True, blank=True)
    public_title_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_issue_titles",
        on_delete=models.SET_NULL,
    )
    description = models.TextField(max_length=5000)
    location_text = models.CharField(max_length=255)
    status = models.CharField(
        max_length=40, choices=IssueStatus.choices, default=IssueStatus.PENDING_TRIAGE
    )
    priority = models.CharField(
        max_length=20, choices=IssuePriority.choices, default=IssuePriority.NORMAL
    )
    tracking_code = models.CharField(max_length=16, unique=True, editable=False)

    citizen_name = models.CharField(max_length=160, blank=True)
    citizen_email = models.EmailField(blank=True)
    citizen_phone = models.CharField(max_length=40, blank=True)
    is_anonymous = models.BooleanField(default=True)

    submitted_ip_hash = models.CharField(max_length=128, blank=True)
    submitted_user_agent_hash = models.CharField(max_length=128, blank=True)
    suspicious_score = models.PositiveSmallIntegerField(default=0)
    suspicious_reasons = models.JSONField(default=list, blank=True)
    is_spam = models.BooleanField(default=False)
    contact_anonymized_at = models.DateTimeField(null=True, blank=True)
    attachments_deleted_at = models.DateTimeField(null=True, blank=True)
    attachment_retention_started_at = models.DateTimeField(null=True, blank=True)
    legal_hold_active = models.BooleanField(default=False)
    legal_hold_reason = models.TextField(max_length=2000, blank=True)
    legal_hold_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="issue_legal_holds",
        on_delete=models.SET_NULL,
    )
    legal_hold_set_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    assigned_department = models.ForeignKey(
        Department, null=True, blank=True, related_name="assigned_issues", on_delete=models.SET_NULL
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="assigned_issues",
        on_delete=models.SET_NULL,
    )
    public_resolution_note = models.TextField(max_length=5000, blank=True)
    internal_note = models.TextField(max_length=10000, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    triaged_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["municipality", "status"]),
            models.Index(fields=["settlement", "status"]),
            models.Index(fields=["tracking_code"]),
            models.Index(fields=["municipality", "submitted_at"], name="iss_mun_sub_idx"),
            models.Index(
                fields=["municipality", "status", "submitted_at"],
                name="iss_mun_status_sub_idx",
            ),
            models.Index(
                fields=["municipality", "assigned_to", "submitted_at"],
                name="iss_mun_assign_sub_idx",
            ),
            models.Index(
                fields=["municipality", "assigned_department", "submitted_at"],
                name="iss_mun_dept_sub_idx",
            ),
            models.Index(
                fields=["municipality", "submitted_ip_hash", "submitted_at"],
                name="iss_mun_ip_sub_idx",
            ),
            models.Index(
                fields=["municipality", "is_spam", "submitted_at"],
                name="iss_mun_spam_sub_idx",
            ),
            models.Index(
                fields=["attachment_retention_started_at"],
                name="iss_retention_start_idx",
            ),
            GinIndex(fields=["title"], name="iss_title_trgm_idx", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["location_text"],
                name="iss_location_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = self.generate_tracking_code()
        self.tracking_code = self.tracking_code.upper()
        self.is_anonymous = not any([self.citizen_name, self.citizen_email, self.citizen_phone])
        if self._state.adding and self.status in FINAL_ISSUE_STATUSES:
            self.attachment_retention_started_at = (
                self.closed_at or self.resolved_at or timezone.now()
            )
        super().save(*args, **kwargs)

    @staticmethod
    def generate_tracking_code():
        for _ in range(20):
            code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10].upper()
            if not Issue.objects.filter(tracking_code=code).exists():
                return code
        raise RuntimeError("Could not generate unique tracking code")

    def mark_status(self, status, user=None, note=""):
        old_status = self.status
        self.status = status
        now = timezone.now()
        if status != old_status:
            if status in {IssueStatus.ACCEPTED, IssueStatus.REJECTED_SPAM, IssueStatus.NOT_JURISDICTION}:
                self.triaged_at = self.triaged_at or now
            if status == IssueStatus.ASSIGNED:
                self.assigned_at = self.assigned_at or now
            if status == IssueStatus.RESOLVED:
                self.resolved_at = self.resolved_at or now
            if status == IssueStatus.CLOSED:
                self.closed_at = self.closed_at or now
            if status in FINAL_ISSUE_STATUSES and old_status not in FINAL_ISSUE_STATUSES:
                self.attachment_retention_started_at = now
            elif status not in FINAL_ISSUE_STATUSES and old_status in FINAL_ISSUE_STATUSES:
                self.attachment_retention_started_at = None
            self.version += 1
            self.save()
            return IssueStatusEvent.objects.create(
                issue=self, from_status=old_status, to_status=status, changed_by=user, note=note
            )
        return None

    def __str__(self):
        return f"{self.tracking_code} — {self.title}"


class IssueAttachment(models.Model):
    issue = models.ForeignKey(Issue, related_name="attachments", on_delete=models.CASCADE)
    image = models.ImageField(upload_to=issue_attachment_path, validators=[validate_image_extension])
    original_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    stored_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    processed_width = models.PositiveIntegerField(null=True, blank=True)
    processed_height = models.PositiveIntegerField(null=True, blank=True)
    stored_format = models.CharField(max_length=16, null=True, blank=True)
    processing_version = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    deletion_state = models.CharField(
        max_length=24,
        choices=AttachmentDeletionState.choices,
        default=AttachmentDeletionState.ACTIVE,
    )
    deletion_started_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deletion_reason = models.CharField(max_length=160, blank=True)
    deletion_error = models.TextField(max_length=1000, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["deletion_state", "deleted_at"], name="attach_state_del_idx")
        ]

    def __str__(self):
        return f"Attachment for {self.issue.tracking_code}"


class SubmissionRateLimit(models.Model):
    municipality = models.ForeignKey(
        Municipality, related_name="submission_rate_limits", on_delete=models.CASCADE
    )
    ip_hash = models.CharField(max_length=128)
    window_start = models.DateTimeField()
    hour_count = models.PositiveSmallIntegerField(default=0)
    day_count = models.PositiveSmallIntegerField(default=0)
    last_submission_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("municipality", "ip_hash")]
        indexes = [
            models.Index(fields=["municipality", "ip_hash"]),
            models.Index(fields=["window_start"]),
        ]


class DataRetentionPolicy(models.Model):
    municipality = models.OneToOneField(
        Municipality,
        related_name="data_retention_policy",
        on_delete=models.CASCADE,
    )
    contact_retention_days = models.PositiveIntegerField(default=365)
    attachment_retention_days = models.PositiveIntegerField(default=90)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "data retention policy"
        verbose_name_plural = "data retention policies"

    def __str__(self):
        return f"Retention policy — {self.municipality.name}"


class IssueStatusEvent(models.Model):
    issue = models.ForeignKey(Issue, related_name="status_events", on_delete=models.CASCADE)
    from_status = models.CharField(max_length=40, blank=True)
    to_status = models.CharField(max_length=40, choices=IssueStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    note = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class IssueComment(models.Model):
    issue = models.ForeignKey(Issue, related_name="comments", on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(max_length=5000)
    is_internal = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class IssueDuplicateLink(models.Model):
    issue = models.ForeignKey(Issue, related_name="duplicate_links", on_delete=models.CASCADE)
    duplicate_of = models.ForeignKey(
        Issue, related_name="duplicates", on_delete=models.CASCADE
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


DEFAULT_REVIEW_TARGET_HOURS = 24
DEFAULT_RESOLUTION_TARGET_HOURS = 240


class ResponseTarget(models.Model):
    municipality = models.OneToOneField(
        Municipality,
        related_name="response_target",
        on_delete=models.CASCADE,
    )
    review_hours = models.PositiveIntegerField(default=DEFAULT_REVIEW_TARGET_HOURS)
    resolution_hours = models.PositiveIntegerField(
        default=DEFAULT_RESOLUTION_TARGET_HOURS
    )

    class Meta:
        verbose_name = "response target"
        verbose_name_plural = "response targets"

    def __str__(self):
        return f"Response targets — {self.municipality.name}"


class AuditLog(models.Model):
    municipality = models.ForeignKey(
        Municipality, null=True, blank=True, related_name="audit_logs", on_delete=models.SET_NULL
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120)
    object_id = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["object_type", "object_id", "created_at"],
                name="audit_object_created_idx",
            )
        ]


class ReceiptDelivery(models.Model):
    issue = models.ForeignKey(Issue, related_name="receipt_deliveries", on_delete=models.CASCADE)
    recipient = models.EmailField()
    state = models.CharField(
        max_length=16,
        choices=ReceiptDeliveryState.choices,
        default=ReceiptDeliveryState.QUEUED,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    queued_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)

    class Meta:
        indexes = [models.Index(fields=["state", "queued_at"], name="receipt_state_queue_idx")]
