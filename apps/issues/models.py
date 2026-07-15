import secrets
from pathlib import Path

from django.conf import settings
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
    description = models.TextField()
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
    public_resolution_note = models.TextField(blank=True)
    internal_note = models.TextField(blank=True)

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
        ]

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = self.generate_tracking_code()
        self.is_anonymous = not any([self.citizen_name, self.citizen_email, self.citizen_phone])
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
            self.save()
            IssueStatusEvent.objects.create(
                issue=self, from_status=old_status, to_status=status, changed_by=user, note=note
            )

    def __str__(self):
        return f"{self.tracking_code} — {self.title}"


class IssueAttachment(models.Model):
    issue = models.ForeignKey(Issue, related_name="attachments", on_delete=models.CASCADE)
    image = models.ImageField(upload_to=issue_attachment_path, validators=[validate_image_extension])
    uploaded_at = models.DateTimeField(auto_now_add=True)

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
    attachment_retention_days = models.PositiveIntegerField(default=1825)
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
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class IssueComment(models.Model):
    issue = models.ForeignKey(Issue, related_name="comments", on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()
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


class SlaPolicy(models.Model):
    municipality = models.ForeignKey(Municipality, related_name="sla_policies", on_delete=models.CASCADE)
    category = models.ForeignKey(
        IssueCategory, null=True, blank=True, related_name="sla_policies", on_delete=models.CASCADE
    )
    triage_hours = models.PositiveIntegerField(default=24)
    first_response_hours = models.PositiveIntegerField(default=48)
    resolution_hours = models.PositiveIntegerField(default=240)

    class Meta:
        verbose_name = "SLA policy"
        verbose_name_plural = "SLA policies"


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
