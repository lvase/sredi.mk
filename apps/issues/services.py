import hashlib
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.accounts.models import StaffRole
from apps.issues.models import (
    DEFAULT_RESOLUTION_TARGET_HOURS,
    DEFAULT_REVIEW_TARGET_HOURS,
    FINAL_ISSUE_STATUSES,
    AuditLog,
    Issue,
    IssueComment,
    IssueStatus,
    ResponseTarget,
)
from config.throttling import increment_fixed_window

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
audit_logger = logging.getLogger("apps.issues.audit")


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


def can_manage_legal_hold(user, issue):
    if not can_staff_access_issue(user, issue):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staffprofile", None)
    return bool(
        profile
        and profile.municipality_id == issue.municipality_id
        and profile.role in {StaffRole.MUNICIPALITY_ADMIN, StaffRole.COORDINATOR}
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


def consume_submission_rate_limit(municipality, ip_hash):
    created_marker = getattr(municipality, "created_at", None)
    identity = f"{municipality.pk}:{created_marker.timestamp() if created_marker else 0}:{ip_hash}"
    hour_count, hour_retry = increment_fixed_window("submission-hour", identity, 60 * 60)
    day_count, day_retry = increment_fixed_window("submission-day", identity, 24 * 60 * 60)
    allowed = hour_count <= MAX_SUBMISSIONS_PER_HOUR and day_count <= MAX_SUBMISSIONS_PER_DAY
    retry_waits = []
    if hour_count > MAX_SUBMISSIONS_PER_HOUR:
        retry_waits.append(hour_retry)
    if day_count > MAX_SUBMISSIONS_PER_DAY:
        retry_waits.append(day_retry)
    state = SubmissionRateState(
        hour_count=max(0, hour_count - 1),
        day_count=max(0, day_count - 1),
        retry_after_seconds=max(retry_waits, default=0) if not allowed else 0,
    )
    return allowed, state


def validate_issue_uploads(files):
    from apps.issues.image_processing import IssueImageValidationError, prepare_issue_images

    try:
        prepare_issue_images(files)
    except IssueImageValidationError as exc:
        return exc.errors
    return []


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
    if hasattr(issue, "target_overdue"):
        return bool(issue.target_overdue)
    if issue.status in FINAL_ISSUE_STATUSES:
        return False
    target = ResponseTarget.objects.filter(municipality=issue.municipality).first()
    review_hours = (
        target.review_hours if target else DEFAULT_REVIEW_TARGET_HOURS
    )
    resolution_hours = (
        target.resolution_hours if target else DEFAULT_RESOLUTION_TARGET_HOURS
    )
    age = timezone.now() - issue.submitted_at
    if issue.status == IssueStatus.PENDING_TRIAGE:
        return age > timedelta(hours=review_hours)
    return age > timedelta(hours=resolution_hours)


def issue_response_deadline(issue):
    """Return the active municipality review or resolution target."""
    if hasattr(issue, "target_deadline"):
        return None if issue.status in FINAL_ISSUE_STATUSES else issue.target_deadline
    if issue.status in FINAL_ISSUE_STATUSES:
        return None
    target = ResponseTarget.objects.filter(municipality=issue.municipality).first()
    if issue.status == IssueStatus.PENDING_TRIAGE:
        hours = target.review_hours if target else DEFAULT_REVIEW_TARGET_HOURS
    else:
        hours = target.resolution_hours if target else DEFAULT_RESOLUTION_TARGET_HOURS
    return issue.submitted_at + timedelta(hours=hours)


def is_issue_due_soon(issue, *, hours=24):
    if hours == 24 and hasattr(issue, "target_due_soon"):
        return bool(issue.target_due_soon)
    deadline = issue_response_deadline(issue)
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
    target_municipality = municipality or getattr(issue, "municipality", None)
    audit = AuditLog.objects.create(
        municipality=target_municipality,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=issue.__class__.__name__ if issue else "",
        object_id=str(issue.pk) if issue else "",
        metadata=metadata or {},
    )
    audit_logger.info(
        "audit_event",
        extra={
            "action": action,
            "actor_id": getattr(actor, "pk", None),
            "municipality_id": getattr(target_municipality, "pk", None),
            "object_type": audit.object_type,
            "object_id": audit.object_id,
        },
    )
    return audit


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
