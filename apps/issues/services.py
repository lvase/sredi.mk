import hashlib
import ipaddress
import math
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from PIL import Image, UnidentifiedImageError

from apps.accounts.models import StaffRole
from apps.issues.models import (
    AuditLog,
    Issue,
    IssueComment,
    IssueStatus,
    SlaPolicy,
    SubmissionRateLimit,
)

TRIAGE_ROLES = {
    StaffRole.MUNICIPALITY_ADMIN,
    StaffRole.COORDINATOR,
}
DEPARTMENT_ROLES = {
    StaffRole.DEPARTMENT_MANAGER,
}
FIELD_WORKER_STATUSES = {
    IssueStatus.IN_PROGRESS,
    IssueStatus.RESOLVED,
}
SENSITIVE_STATUS_NOTE_REQUIRED = {
    IssueStatus.REJECTED_SPAM,
    IssueStatus.NOT_JURISDICTION,
    IssueStatus.DUPLICATE,
    IssueStatus.RESOLVED,
}
MAX_SUBMISSIONS_PER_HOUR = settings.ISSUE_RATE_LIMIT_HOURLY
MAX_SUBMISSIONS_PER_DAY = settings.ISSUE_RATE_LIMIT_DAILY
MAX_PHOTOS_PER_ISSUE = settings.MAX_ISSUE_PHOTOS
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE_BYTES = getattr(settings, "MAX_ISSUE_IMAGE_SIZE_BYTES", 5 * 1024 * 1024)


@dataclass(frozen=True)
class SubmissionRateState:
    hour_count: int
    day_count: int
    retry_after_seconds: int = 0


def hash_client_value(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_ip(value):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _is_trusted_proxy(value):
    address = _parse_ip(value)
    if address is None:
        return False
    for trusted_value in settings.TRUSTED_PROXY_IPS:
        try:
            if address in ipaddress.ip_network(trusted_value.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request):
    remote_address = request.META.get("REMOTE_ADDR", "")
    if not _is_trusted_proxy(remote_address):
        parsed_remote = _parse_ip(remote_address)
        return str(parsed_remote) if parsed_remote else ""

    forwarded_chain = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
    candidates = [candidate.strip() for candidate in forwarded_chain if candidate.strip()]
    candidates.append(remote_address)
    for candidate in reversed(candidates):
        parsed_candidate = _parse_ip(candidate)
        if parsed_candidate is None:
            continue
        if _is_trusted_proxy(str(parsed_candidate)):
            continue
        return str(parsed_candidate)
    return ""


def can_staff_access_issue(user, issue):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    return bool(profile and profile.municipality_id == issue.municipality_id)


def staff_belongs_to_issue_municipality(user, issue):
    profile = getattr(user, "staffprofile", None)
    return bool(profile and profile.municipality_id == issue.municipality_id)


def can_update_issue_assignment(user, issue):
    if not can_staff_access_issue(user, issue):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    return bool(
        profile
        and staff_belongs_to_issue_municipality(user, issue)
        and profile.role in TRIAGE_ROLES
    )


def can_change_issue_status(user, issue, new_status=None):
    if not can_staff_access_issue(user, issue):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    if not profile or not staff_belongs_to_issue_municipality(user, issue):
        return False
    if profile.role in TRIAGE_ROLES:
        return True
    if profile.role == StaffRole.DEPARTMENT_MANAGER:
        return bool(profile.department_id and issue.assigned_department_id == profile.department_id)
    if profile.role == StaffRole.FIELD_WORKER:
        if issue.assigned_to_id != user.id:
            return False
        return new_status in FIELD_WORKER_STATUSES if new_status else True
    return False


def can_add_issue_comment(user, issue):
    if not can_staff_access_issue(user, issue):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    if not profile or not staff_belongs_to_issue_municipality(user, issue):
        return False
    if profile.role in TRIAGE_ROLES:
        return True
    if profile.role == StaffRole.DEPARTMENT_MANAGER:
        return bool(profile.department_id and issue.assigned_department_id == profile.department_id)
    if profile.role == StaffRole.FIELD_WORKER:
        return issue.assigned_to_id == user.id
    return False


def can_moderate_public_title(user, issue):
    if not can_staff_access_issue(user, issue):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    return bool(
        profile
        and profile.municipality_id == issue.municipality_id
        and profile.role in TRIAGE_ROLES
    )


def public_status_label(status):
    labels = {
        IssueStatus.PENDING_TRIAGE: "Примена",
        IssueStatus.ACCEPTED: "Прифатена",
        IssueStatus.ASSIGNED: "Доделена",
        IssueStatus.IN_PROGRESS: "Во тек",
        IssueStatus.RESOLVED: "Решена",
        IssueStatus.CLOSED: "Затворена",
        IssueStatus.DUPLICATE: "Дупликат",
        IssueStatus.REJECTED_SPAM: "Неважечка",
        IssueStatus.NOT_JURISDICTION: "Не е во надлежност",
        IssueStatus.WAITING_CITIZEN: "Се чека дополнување",
        IssueStatus.WAITING_EXTERNAL: "Се чека надворешна институција",
        IssueStatus.PROCUREMENT_NEEDED: "Потребна е набавка",
    }
    return labels.get(status, status)


def normalize_tracking_code(raw_code):
    return "".join(character for character in (raw_code or "").upper() if character not in " -")


def tracking_code_matches(issue, raw_code):
    return constant_time_compare(
        normalize_tracking_code(issue.tracking_code),
        normalize_tracking_code(raw_code),
    )


@transaction.atomic
def consume_submission_rate_limit(municipality, ip_hash):
    now = timezone.now()
    limit, _ = SubmissionRateLimit.objects.select_for_update().get_or_create(
        municipality=municipality,
        ip_hash=ip_hash,
        defaults={"window_start": now},
    )
    if now - limit.window_start >= timedelta(days=1):
        limit.window_start = now
        limit.hour_count = 0
        limit.day_count = 0
    elif limit.last_submission_at and now - limit.last_submission_at >= timedelta(hours=1):
        limit.hour_count = 0

    allowed = (
        limit.hour_count < MAX_SUBMISSIONS_PER_HOUR
        and limit.day_count < MAX_SUBMISSIONS_PER_DAY
    )
    if allowed:
        limit.hour_count += 1
        limit.day_count += 1
        limit.last_submission_at = timezone.now()
    retry_waits = []
    if not allowed and limit.hour_count >= MAX_SUBMISSIONS_PER_HOUR and limit.last_submission_at:
        retry_waits.append((limit.last_submission_at + timedelta(hours=1) - now).total_seconds())
    if not allowed and limit.day_count >= MAX_SUBMISSIONS_PER_DAY:
        retry_waits.append((limit.window_start + timedelta(days=1) - now).total_seconds())
    state = SubmissionRateState(
        hour_count=limit.hour_count - (1 if allowed else 0),
        day_count=limit.day_count - (1 if allowed else 0),
        retry_after_seconds=max(1, math.ceil(max(retry_waits, default=0))) if not allowed else 0,
    )
    limit.save(update_fields=["hour_count", "day_count", "last_submission_at", "window_start", "updated_at"])
    return allowed, state


def validate_issue_uploads(files):
    errors = []
    if len(files) > MAX_PHOTOS_PER_ISSUE:
        errors.append("Може да прикачиш најмногу 5 фотографии.")
    for file in files[:MAX_PHOTOS_PER_ISSUE]:
        suffix = Path(file.name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            errors.append("Дозволени се само JPG, PNG или WEBP фотографии.")
            continue
        content_type = getattr(file, "content_type", "")
        if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            errors.append("Фотографиите мора да бидат JPG, PNG или WEBP.")
        if file.size > MAX_IMAGE_SIZE_BYTES:
            errors.append("Секоја фотографија мора да биде помала од 5 MB.")
        try:
            Image.open(file).verify()
        except (UnidentifiedImageError, OSError):
            errors.append("Една од фотографиите не може да се прочита како валидна слика.")
        finally:
            file.seek(0)
    return errors


def calculate_suspicious_assessment(
    files,
    rate_state,
    *,
    municipality,
    ip_hash,
    description,
    location_text,
):
    score = 0
    reasons = []
    frequency_points = min(rate_state.hour_count * 10, 30)
    if frequency_points:
        score += frequency_points
        reasons.append(
            {
                "code": "rapid_submissions",
                "label": "Повеќе пријави од иста мрежа во последниот час.",
                "points": frequency_points,
            }
        )
    if rate_state.day_count >= 5:
        score += 20
        reasons.append(
            {
                "code": "high_daily_volume",
                "label": "Најмалку пет претходни пријави од иста мрежа во 24 часа.",
                "points": 20,
            }
        )

    recent_issues = Issue.objects.filter(
        municipality=municipality,
        submitted_ip_hash=ip_hash,
        submitted_at__gte=timezone.now() - timedelta(days=1),
    )
    normalized_description = description.strip()
    if ip_hash and normalized_description and recent_issues.filter(
        description__iexact=normalized_description
    ).exists():
        score += 25
        reasons.append(
            {
                "code": "repeated_description",
                "label": "Истиот опис веќе е испратен од оваа мрежа во последните 24 часа.",
                "points": 25,
            }
        )

    normalized_location = location_text.strip()
    if ip_hash and normalized_location and recent_issues.filter(
        location_text__iexact=normalized_location
    ).count() >= 2:
        score += 15
        reasons.append(
            {
                "code": "repeated_location",
                "label": "Истата локација е пријавена повеќепати од оваа мрежа во последните 24 часа.",
                "points": 15,
            }
        )

    if len(files) >= 4:
        score += 10
        reasons.append(
            {
                "code": "many_attachments",
                "label": "Прикачени се четири или повеќе фотографии.",
                "points": 10,
            }
        )
    return min(score, 100), reasons


def is_issue_overdue(issue):
    if issue.status in {IssueStatus.RESOLVED, IssueStatus.CLOSED}:
        return False
    policy = (
        SlaPolicy.objects.filter(municipality=issue.municipality, category=issue.category).first()
        or SlaPolicy.objects.filter(municipality=issue.municipality, category__isnull=True).first()
    )
    triage_hours = policy.triage_hours if policy else 24
    resolution_hours = policy.resolution_hours if policy else 240
    age = timezone.now() - issue.submitted_at
    if issue.status == IssueStatus.PENDING_TRIAGE:
        return age > timedelta(hours=triage_hours)
    return age > timedelta(hours=resolution_hours)


def issue_sla_deadline(issue):
    """Return the active triage/resolution deadline using category then municipal fallback."""
    if issue.status in {IssueStatus.RESOLVED, IssueStatus.CLOSED}:
        return None
    policy = (
        SlaPolicy.objects.filter(municipality=issue.municipality, category=issue.category).first()
        or SlaPolicy.objects.filter(municipality=issue.municipality, category__isnull=True).first()
    )
    if issue.status == IssueStatus.PENDING_TRIAGE:
        hours = policy.triage_hours if policy else 24
    else:
        hours = policy.resolution_hours if policy else 240
    return issue.submitted_at + timedelta(hours=hours)


def is_issue_due_soon(issue, *, hours=24):
    deadline = issue_sla_deadline(issue)
    if deadline is None:
        return False
    now = timezone.now()
    return now <= deadline <= now + timedelta(hours=hours)


def status_requires_note(status):
    return status in SENSITIVE_STATUS_NOTE_REQUIRED


def apply_default_department(issue, status):
    if (
        status in {IssueStatus.ACCEPTED, IssueStatus.ASSIGNED}
        and not issue.assigned_department_id
        and issue.category.default_department_id
    ):
        issue.assigned_department = issue.category.default_department


def write_audit_log(actor, action, issue=None, municipality=None, metadata=None):
    AuditLog.objects.create(
        municipality=municipality or getattr(issue, "municipality", None),
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=issue.__class__.__name__ if issue else "",
        object_id=str(issue.pk) if issue else "",
        metadata=metadata or {},
    )


def publish_resolution_note_update(issue, actor, previous_note):
    """Preserve a changed public resolution note as a public timeline update."""
    current_note = issue.public_resolution_note.strip()
    if not current_note or current_note == previous_note.strip():
        return None
    comment = IssueComment.objects.create(
        issue=issue,
        author=actor,
        body=current_note,
        is_internal=False,
    )
    write_audit_log(
        actor,
        "issue_public_update_published",
        issue=issue,
        metadata={"comment_id": comment.pk, "source": "public_resolution_note"},
    )
    getattr(issue, "_prefetched_objects_cache", {}).pop("comments", None)
    return comment
