import hashlib
import json
import logging
import mimetypes
from csv import writer
from datetime import timedelta
from functools import wraps
from pathlib import Path
from statistics import median

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Aggregate,
    Avg,
    Case,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Extract, TruncDay, TruncMonth, TruncWeek
from django.http import FileResponse, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import RecoveryCode, TrustedDevice
from apps.accounts.security import (
    TRUSTED_DEVICE_COOKIE,
    auth_attempt_state,
    begin_totp_enrollment,
    clear_auth_failures,
    clear_pending_auth,
    confirmed_totp_device,
    enrollment_payload,
    ensure_staff_profile,
    generate_recovery_codes,
    issue_trusted_device,
    pending_user,
    record_auth_failure,
    revoke_trusted_devices,
    set_pending_auth,
    validate_trusted_device,
    verify_second_factor,
)
from apps.api.serializers import (
    AuditLogSerializer,
    DepartmentSerializer,
    IssueCategorySerializer,
    IssueCommentSerializer,
    IssueStatusEventSerializer,
    MunicipalitySerializer,
    PublicIssueRowSerializer,
    SettlementSerializer,
    StaffChoicesSerializer,
    StaffIssueDetailSerializer,
    StaffIssueListSerializer,
    StaffUserCreateSerializer,
    TrackedIssueSerializer,
    UserSummarySerializer,
)
from apps.issues.delivery import queue_receipt_delivery
from apps.issues.forms import CitizenIssueForm, IssueCommentForm, StaffIssueUpdateForm
from apps.issues.image_processing import (
    IssueImageValidationError,
    prepare_issue_images,
    save_issue_with_attachments,
)
from apps.issues.models import (
    AttachmentDeletionState,
    AuditLog,
    DEFAULT_RESOLUTION_TARGET_HOURS,
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueComment,
    IssueStatus,
    IssueStatusEvent,
    ResponseTarget,
)
from apps.issues.services import (
    apply_default_department,
    calculate_suspicious_assessment,
    can_add_issue_comment,
    can_change_issue_status,
    can_manage_legal_hold,
    can_moderate_public_title,
    can_update_issue_assignment,
    consume_submission_rate_limit,
    get_client_ip,
    hash_client_value,
    is_issue_due_soon,
    is_issue_overdue,
    normalize_tracking_code,
    public_status_label,
    publish_resolution_note_update,
    status_requires_note,
    tracking_code_matches,
    write_audit_log,
)
from apps.issues.views_staff import quick_status_actions, staff_issue_queryset
from apps.municipalities.models import (
    Department,
    Municipality,
    MunicipalityPublicNotice,
    NoticePublicationState,
)
from config.throttling import SharedThrottleUnavailable

security_logger = logging.getLogger("apps.issues.security")


def ok(data=None, status_code=status.HTTP_200_OK, **extra):
    payload = {"data": data if data is not None else {}}
    payload.update(extra)
    return Response(payload, status=status_code)


def fail(errors, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({"errors": errors}, status=status_code)


def require_shared_throttle(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except SharedThrottleUnavailable:
            security_logger.error(
                "shared_throttle_unavailable",
                extra={"request_id": getattr(request, "request_id", None), "path": request.path},
            )
            response = fail(
                {"detail": "Заштитата е привремено недостапна. Обиди се повторно."},
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            response["Retry-After"] = "60"
            return response

    return guarded


def get_municipality_or_404(municipality_slug):
    return get_object_or_404(Municipality, slug=municipality_slug, is_active=True)


def ordered_municipality_settlements(municipality):
    namesake = municipality.name.removeprefix("Општина ").strip()
    return (
        municipality.settlements.filter(is_active=True)
        .annotate(
            namesake_order=Case(
                When(name=namesake, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("namesake_order", "name")
    )


def legal_payload(kind):
    shared = {
        "notice": (
            "Овој текст е работна верзија и треба да биде проверен од правник и од "
            "секоја општина пред јавно пуштање во употреба."
        ),
        "platform_operator_name": settings.PLATFORM_OPERATOR_NAME,
        "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
    }
    if kind == "privacy":
        return {
            **shared,
            "title": "Политика за приватност",
            "updated_at": "13.07.2026",
        }
    return {
        **shared,
        "title": "Услови за користење",
        "updated_at": "14.07.2026",
    }


def add_issue_api_fields(user, issue):
    issue.is_overdue = (
        bool(issue.target_overdue)
        if hasattr(issue, "target_overdue")
        else is_issue_overdue(issue)
    )
    issue.is_due_soon = (
        bool(issue.target_due_soon)
        if hasattr(issue, "target_due_soon")
        else is_issue_due_soon(issue)
    )
    issue.quick_status_actions = [
        {"value": value, "label": label} for value, label in quick_status_actions(user, issue)
    ]
    issue.permissions = {
        "can_update": can_update_issue_assignment(user, issue),
        "can_change_status": can_change_issue_status(user, issue),
        "can_comment": can_add_issue_comment(user, issue),
        "can_moderate_public_title": can_moderate_public_title(user, issue),
        "can_manage_legal_hold": can_manage_legal_hold(user, issue),
    }
    return issue


def conflict_response(issue):
    return Response(
        {
            "errors": {"detail": "Пријавата е променета од друг корисник."},
            "meta": {"current_version": issue.version},
        },
        status=status.HTTP_409_CONFLICT,
    )


def check_expected_version(request, issue):
    try:
        expected = int(request.data.get("expected_version"))
    except (TypeError, ValueError):
        return fail({"expected_version": ["Испратете ја верзијата што ја уредувате."]})
    if expected != issue.version:
        return conflict_response(issue)
    return None


def load_staff_issue_detail(user, pk):
    comment_counts = (
        IssueComment.objects.filter(issue_id=OuterRef("pk"))
        .values("issue_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    status_counts = (
        IssueStatusEvent.objects.filter(issue_id=OuterRef("pk"))
        .values("issue_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    issue = get_object_or_404(
        staff_issue_queryset(user)
        .annotate(
            comments_count=Coalesce(Subquery(comment_counts[:1]), Value(0)),
            status_events_count=Coalesce(Subquery(status_counts[:1]), Value(0)),
        )
        .prefetch_related(
            "attachments",
            Prefetch(
                "comments",
                queryset=IssueComment.objects.select_related("author").order_by(
                    "-created_at", "-pk"
                )[:20],
                to_attr="bounded_comments",
            ),
            Prefetch(
                "status_events",
                queryset=IssueStatusEvent.objects.select_related("changed_by").order_by(
                    "-created_at", "-pk"
                )[:20],
                to_attr="bounded_status_events",
            ),
        ),
        pk=pk,
    )
    issue.bounded_audit_logs = list(
        AuditLog.objects.filter(object_type="Issue", object_id=str(issue.pk))
        .select_related("actor")
        .order_by("-created_at", "-pk")[:20]
    )
    issue.audit_logs_count = AuditLog.objects.filter(
        object_type="Issue", object_id=str(issue.pk)
    ).count()
    return add_issue_api_fields(user, issue)


def staff_filter_queryset(request):
    issues = staff_issue_queryset(request.user)
    filters = {
        "municipality": "municipality_id",
        "status": "status",
        "settlement": "settlement_id",
        "category": "category_id",
        "priority": "priority",
        "department": "assigned_department_id",
        "assigned_to": "assigned_to_id",
    }
    for query_key, field_name in filters.items():
        value = request.query_params.get(query_key)
        if value:
            issues = issues.filter(**{field_name: value})
    if request.query_params.get("mine"):
        issues = issues.filter(assigned_to=request.user)
    if request.query_params.get("unassigned") == "1":
        issues = issues.filter(assigned_to__isnull=True)
    search = request.query_params.get("search", "").strip()
    if search:
        normalized_code = normalize_tracking_code(search)
        query = Q(title__icontains=search) | Q(location_text__icontains=search)
        if normalized_code:
            query |= Q(tracking_code__icontains=normalized_code)
        issues = issues.filter(query)
    return issues


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_view(request):
    return ok({"csrfToken": get_token(request)})


@api_view(["GET"])
@permission_classes([AllowAny])
def session_view(request):
    user = request.user if request.user.is_authenticated else None
    return ok(
        {
            "isAuthenticated": bool(user),
            "user": UserSummarySerializer(user).data if user else None,
            "csrfToken": get_token(request),
            "pendingAuthentication": bool(pending_user(request)),
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
@require_shared_throttle
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = request.data.get("password", "")
    ip_address = get_client_ip(request)
    attempt = auth_attempt_state(username, ip_address)
    if not attempt.allowed:
        response = fail(
            {"detail": "Премногу неуспешни обиди. Обиди се повторно подоцна."},
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(attempt.retry_after_seconds)
        return response
    user = authenticate(request, username=username, password=password)
    if not user:
        failure = record_auth_failure(username, ip_address)
        if not failure.allowed:
            response = fail(
                {"detail": "Премногу неуспешни обиди. Обиди се повторно подоцна."},
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(failure.retry_after_seconds)
            return response
        return fail(
            {"detail": "Невалидно корисничко име или лозинка."}, status.HTTP_400_BAD_REQUEST
        )
    clear_auth_failures(username, ip_address)
    profile = ensure_staff_profile(user)
    if profile.must_change_password:
        set_pending_auth(request, user)
        return ok({"authenticated": False, "next_step": "change_password"})
    device = confirmed_totp_device(user)
    if user.is_superuser and not device:
        set_pending_auth(request, user)
        return ok({"authenticated": False, "next_step": "enroll_superuser_2fa"})
    if device and not validate_trusted_device(
        user, request.COOKIES.get(TRUSTED_DEVICE_COOKIE, "")
    ):
        set_pending_auth(request, user)
        return ok({"authenticated": False, "next_step": "verify_2fa"})
    return _complete_authentication(request, user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    clear_pending_auth(request)
    logout(request)
    return ok({"loggedOut": True})


def _auth_user_for_security_flow(request):
    if request.user.is_authenticated:
        return request.user
    return pending_user(request)


def _complete_authentication(request, user, remember_device=False):
    clear_pending_auth(request)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    device = confirmed_totp_device(user)
    if device:
        otp_login(request, device)
    response = ok(
        {
            "authenticated": True,
            "next_step": "authenticated",
            "user": UserSummarySerializer(user).data,
            "csrfToken": get_token(request),
        }
    )
    if remember_device:
        cookie, expires_at = issue_trusted_device(user, request)
        response.set_cookie(
            TRUSTED_DEVICE_COOKIE,
            cookie,
            expires=expires_at,
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="Lax",
        )
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def security_status(request):
    active_devices = TrustedDevice.objects.filter(
        user=request.user,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-last_used_at", "-created_at")
    return ok(
        {
            "two_factor_enabled": bool(confirmed_totp_device(request.user)),
            "recovery_codes_remaining": RecoveryCode.objects.filter(
                user=request.user, used_at__isnull=True
            ).count(),
            "trusted_devices": [
                {
                    "id": item.pk,
                    "label": item.label or "Непознат прелистувач",
                    "created_at": item.created_at,
                    "last_used_at": item.last_used_at,
                    "expires_at": item.expires_at,
                }
                for item in active_devices
            ],
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def totp_setup(request):
    user = _auth_user_for_security_flow(request)
    if not user:
        return fail({"detail": "Потребна е повторна најава."}, status.HTTP_401_UNAUTHORIZED)
    device = begin_totp_enrollment(user)
    return ok(enrollment_payload(device))


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
@require_shared_throttle
@transaction.atomic
def totp_confirm(request):
    user = _auth_user_for_security_flow(request)
    if not user:
        return fail({"detail": "Потребна е повторна најава."}, status.HTTP_401_UNAUTHORIZED)
    token = str(request.data.get("token", "")).strip()
    ip_address = get_client_ip(request)
    attempt = auth_attempt_state(user.get_username(), ip_address)
    if not attempt.allowed:
        return fail(
            {"detail": "Премногу неуспешни обиди. Обиди се повторно подоцна."},
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-id").first()
    if not device or not device.verify_token(token):
        failure = record_auth_failure(user.get_username(), ip_address)
        code = status.HTTP_400_BAD_REQUEST if failure.allowed else status.HTTP_429_TOO_MANY_REQUESTS
        return fail({"token": ["Кодот не е валиден или е истечен."]}, code)
    TOTPDevice.objects.filter(user=user, confirmed=True).delete()
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    codes = generate_recovery_codes(user)
    revoke_trusted_devices(user)
    clear_auth_failures(user.get_username(), ip_address)
    write_audit_log(
        user,
        "two_factor_enabled",
        municipality=getattr(ensure_staff_profile(user), "municipality", None),
    )
    remember = bool(request.data.get("remember_device", True))
    if pending_user(request):
        response = _complete_authentication(request, user, remember_device=remember)
        response.data["data"]["recovery_codes"] = codes
        return response
    response = ok({"two_factor_enabled": True, "recovery_codes": codes})
    otp_login(request, device)
    if remember:
        cookie, expires_at = issue_trusted_device(user, request)
        response.set_cookie(
            TRUSTED_DEVICE_COOKIE,
            cookie,
            expires=expires_at,
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="Lax",
        )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
@require_shared_throttle
def verify_two_factor(request):
    user = pending_user(request)
    if not user:
        return fail({"detail": "Потребна е повторна најава."}, status.HTTP_401_UNAUTHORIZED)
    ip_address = get_client_ip(request)
    attempt = auth_attempt_state(user.get_username(), ip_address)
    if not attempt.allowed:
        return fail(
            {"detail": "Премногу неуспешни обиди. Обиди се повторно подоцна."},
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    method = verify_second_factor(user, request.data.get("token", ""))
    if not method:
        failure = record_auth_failure(user.get_username(), ip_address)
        code = status.HTTP_400_BAD_REQUEST if failure.allowed else status.HTTP_429_TOO_MANY_REQUESTS
        return fail({"token": ["Кодот не е валиден или е веќе искористен."]}, code)
    clear_auth_failures(user.get_username(), ip_address)
    return _complete_authentication(
        request,
        user,
        remember_device=bool(request.data.get("remember_device", True)),
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def change_password(request):
    user = _auth_user_for_security_flow(request)
    if not user:
        return fail({"detail": "Потребна е повторна најава."}, status.HTTP_401_UNAUTHORIZED)
    current_password = request.data.get("current_password", "")
    new_password = request.data.get("new_password", "")
    if not user.check_password(current_password):
        return fail({"current_password": ["Тековната лозинка не е точна."]})
    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        return fail({"new_password": list(exc.messages)})
    user.set_password(new_password)
    user.save(update_fields=["password"])
    profile = ensure_staff_profile(user)
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password", "updated_at"])
    revoke_trusted_devices(user)
    write_audit_log(user, "password_changed", municipality=profile.municipality)
    if pending_user(request):
        if user.is_superuser and not confirmed_totp_device(user):
            set_pending_auth(request, user)
            return ok({"authenticated": False, "next_step": "enroll_superuser_2fa"})
        if confirmed_totp_device(user):
            set_pending_auth(request, user)
            return ok({"authenticated": False, "next_step": "verify_2fa"})
        return _complete_authentication(request, user)
    return ok({"changed": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def disable_two_factor(request):
    if request.user.is_superuser:
        return fail(
            {"detail": "2FA е задолжителна за администраторот на платформата."},
            status.HTTP_403_FORBIDDEN,
        )
    if not request.user.check_password(request.data.get("password", "")):
        return fail({"password": ["Лозинката не е точна."]})
    if not verify_second_factor(request.user, request.data.get("token", "")):
        return fail({"token": ["Кодот не е валиден."]})
    TOTPDevice.objects.filter(user=request.user).delete()
    RecoveryCode.objects.filter(user=request.user).delete()
    revoke_trusted_devices(request.user)
    write_audit_log(
        request.user,
        "two_factor_disabled",
        municipality=getattr(ensure_staff_profile(request.user), "municipality", None),
    )
    response = ok({"two_factor_enabled": False})
    response.delete_cookie(TRUSTED_DEVICE_COOKIE)
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def regenerate_recovery_codes(request):
    if not verify_second_factor(request.user, request.data.get("token", "")):
        return fail({"token": ["Кодот не е валиден."]})
    codes = generate_recovery_codes(request.user)
    revoke_trusted_devices(request.user)
    write_audit_log(
        request.user,
        "two_factor_recovery_codes_regenerated",
        municipality=getattr(ensure_staff_profile(request.user), "municipality", None),
    )
    response = ok({"recovery_codes": codes})
    response.delete_cookie(TRUSTED_DEVICE_COOKIE)
    return response


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def revoke_trusted_device(request, pk):
    device = get_object_or_404(TrustedDevice, pk=pk, user=request.user)
    device.revoked_at = timezone.now()
    device.save(update_fields=["revoked_at"])
    return ok({"revoked": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reset_staff_two_factor(request, user_id):
    if not request.user.is_superuser:
        return fail({"detail": "Немате дозвола за оваа операција."}, status.HTTP_403_FORBIDDEN)
    target = get_object_or_404(get_user_model(), pk=user_id, is_superuser=False)
    TOTPDevice.objects.filter(user=target).delete()
    RecoveryCode.objects.filter(user=target).delete()
    revoke_trusted_devices(target)
    write_audit_log(
        request.user,
        "staff_two_factor_reset",
        municipality=getattr(ensure_staff_profile(target), "municipality", None),
        metadata={"target_user_id": target.pk},
    )
    return ok({"reset": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def privacy_view(request):
    return ok(legal_payload("privacy"))


@api_view(["GET"])
@permission_classes([AllowAny])
def terms_view(request):
    return ok(legal_payload("terms"))


@api_view(["GET"])
@permission_classes([AllowAny])
def municipality_list(request):
    municipalities = Municipality.objects.filter(is_active=True)
    return ok(MunicipalitySerializer(municipalities, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def municipality_detail(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    return ok(MunicipalitySerializer(municipality).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def municipality_crest(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    if not municipality.official_coat_of_arms:
        return fail({"detail": "Општината нема објавен официјален грб."}, status.HTTP_404_NOT_FOUND)
    content_type = mimetypes.guess_type(municipality.official_coat_of_arms.name)[0] or "image/png"
    response = FileResponse(municipality.official_coat_of_arms.open("rb"), content_type=content_type)
    response["Cache-Control"] = "public, max-age=86400"
    response["Content-Disposition"] = "inline"
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def form_options(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    categories = IssueCategory.objects.filter(is_active=True).filter(
        municipality__in=[municipality, None]
    )
    return ok(
        {
            "municipality": MunicipalitySerializer(municipality).data,
            "settlements": SettlementSerializer(
                ordered_municipality_settlements(municipality), many=True
            ).data,
            "categories": IssueCategorySerializer(categories, many=True).data,
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@require_shared_throttle
def submit_issue(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    form = CitizenIssueForm(request.data, municipality=municipality)
    files = request.FILES.getlist("photos")
    form_is_valid = form.is_valid()
    if not form_is_valid:
        return fail(dict(form.errors))
    ip_hash = hash_client_value(get_client_ip(request))
    allowed, rate_state = consume_submission_rate_limit(municipality, ip_hash)
    if not allowed:
        response = Response(
            {
                "errors": {
                    "rate_limit": [
                        "Испратени се премногу пријави од оваа мрежа. Обиди се повторно подоцна."
                    ]
                },
                "meta": {"retry_after_seconds": rate_state.retry_after_seconds},
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(rate_state.retry_after_seconds)
        return response
    try:
        processed_images = prepare_issue_images(files)
    except IssueImageValidationError as exc:
        return fail({"photos": exc.errors})
    issue = form.save(commit=False)
    issue.municipality = municipality
    issue.submitted_ip_hash = ip_hash
    issue.submitted_user_agent_hash = hash_client_value(
        request.META.get("HTTP_USER_AGENT", "")[:500]
    )
    issue.suspicious_score, issue.suspicious_reasons = calculate_suspicious_assessment(
        files,
        rate_state,
        municipality=municipality,
        ip_hash=ip_hash,
        description=issue.description,
        location_text=issue.location_text,
    )
    save_issue_with_attachments(issue, processed_images)

    receipt_delivery = "not_requested"
    if form.cleaned_data.get("send_receipt"):
        try:
            queue_receipt_delivery(issue)
        except Exception:
            security_logger.exception(
                "receipt_delivery_record_failed", extra={"issue_id": issue.pk}
            )
            receipt_delivery = "failed"
        else:
            receipt_delivery = "queued"
    return ok(
        {
            "id": issue.pk,
            "tracking_code": issue.tracking_code,
            "status": issue.status,
            "status_label": issue.get_status_display(),
            "receipt_delivery": receipt_delivery,
        },
        status_code=status.HTTP_201_CREATED,
    )


PUBLIC_STATUS_GROUPS = {
    "submitted": [IssueStatus.PENDING_TRIAGE],
    "verified": [IssueStatus.ACCEPTED],
    "assigned": [IssueStatus.ASSIGNED],
    "in_progress": [
        IssueStatus.IN_PROGRESS,
        IssueStatus.WAITING_CITIZEN,
        IssueStatus.WAITING_EXTERNAL,
        IssueStatus.PROCUREMENT_NEEDED,
    ],
    "resolved": [IssueStatus.RESOLVED, IssueStatus.CLOSED],
    "exceptional": [
        IssueStatus.DUPLICATE,
        IssueStatus.REJECTED_SPAM,
        IssueStatus.NOT_JURISDICTION,
    ],
}
STATISTICS_PERIODS = {"30": 30, "90": 90, "365": 365, "all": None}
MIN_PUBLIC_GROUP_SIZE = 5


def _statistics_bucket(date_value, period):
    day = timezone.localtime(date_value).date()
    if period == "30":
        return day.isoformat()
    if period == "90":
        monday = day - timedelta(days=day.weekday())
        return monday.isoformat()
    return day.replace(day=1).isoformat()


def _suppressed_distribution(rows, label_key):
    visible = []
    suppressed = 0
    for row in rows:
        total = row["total"]
        if total < MIN_PUBLIC_GROUP_SIZE:
            suppressed += 1
            continue
        visible.append({"label": row[label_key], "total": total, "suppressed": False})
    return visible, suppressed


def _legacy_build_public_statistics(request, municipality):
    period = request.query_params.get("period", "90")
    if period not in STATISTICS_PERIODS:
        period = "90"
    settlement = request.query_params.get("settlement", "")
    category = request.query_params.get("category", "")
    public_status = request.query_params.get("status", "")

    issues = (
        Issue.objects.filter(municipality=municipality, is_spam=False)
        .exclude(status=IssueStatus.REJECTED_SPAM)
        .select_related("settlement", "category")
    )
    days = STATISTICS_PERIODS[period]
    if days:
        issues = issues.filter(submitted_at__gte=timezone.now() - timedelta(days=days))
    if settlement:
        issues = issues.filter(settlement_id=settlement)
    if category:
        issues = issues.filter(category_id=category)
    if public_status in PUBLIC_STATUS_GROUPS:
        issues = issues.filter(status__in=PUBLIC_STATUS_GROUPS[public_status])
    elif public_status:
        public_status = ""

    issue_rows = list(issues)
    terminal = {
        IssueStatus.RESOLVED,
        IssueStatus.CLOSED,
        IssueStatus.DUPLICATE,
        IssueStatus.REJECTED_SPAM,
        IssueStatus.NOT_JURISDICTION,
    }
    stats = {
        "total": len(issue_rows),
        "open": sum(item.status not in terminal for item in issue_rows),
        "resolved": sum(
            item.status in {IssueStatus.RESOLVED, IssueStatus.CLOSED} for item in issue_rows
        ),
        "pending": sum(item.status == IssueStatus.PENDING_TRIAGE for item in issue_rows),
    }

    settlement_rows = list(
        issues.values("settlement__name").annotate(total=Count("id")).order_by("settlement__name")
    )
    category_rows = list(
        issues.values("category__name").annotate(total=Count("id")).order_by("category__name")
    )
    by_settlement, suppressed_settlements = _suppressed_distribution(
        settlement_rows, "settlement__name"
    )
    by_category, suppressed_categories = _suppressed_distribution(category_rows, "category__name")

    buckets = {}
    for issue in issue_rows:
        key = _statistics_bucket(issue.submitted_at, period)
        buckets[key] = buckets.get(key, 0) + 1
    time_series = []
    suppressed_buckets = 0
    for key, total in sorted(buckets.items()):
        suppressed = total < MIN_PUBLIC_GROUP_SIZE
        suppressed_buckets += int(suppressed)
        time_series.append(
            {"bucket": key, "total": None if suppressed else total, "suppressed": suppressed}
        )

    review_hours = [
        (issue.triaged_at - issue.submitted_at).total_seconds() / 3600
        for issue in issue_rows
        if issue.triaged_at and issue.triaged_at >= issue.submitted_at
    ]
    resolution_hours = []
    resolved_within_target = []
    target = ResponseTarget.objects.filter(municipality=municipality).first()
    for issue in issue_rows:
        resolved_at = issue.resolved_at or issue.closed_at
        if not resolved_at or resolved_at < issue.submitted_at:
            continue
        elapsed = (resolved_at - issue.submitted_at).total_seconds() / 3600
        resolution_hours.append(elapsed)
        allowed_hours = (
            target.resolution_hours if target else DEFAULT_RESOLUTION_TARGET_HOURS
        )
        resolved_within_target.append(elapsed <= allowed_hours)

    recent_reports = list(
        issues.filter(public_title_approved_at__isnull=False)
        .exclude(public_title="")
        .order_by("-submitted_at")[:20]
    )
    latest = issues.aggregate(value=Max("updated_at"))["value"]
    return {
        "municipality": MunicipalitySerializer(municipality, context={"request": request}).data,
        "applied_filters": {
            "period": period,
            "settlement": settlement or None,
            "category": category or None,
            "status": public_status or None,
        },
        "filter_options": {
            "settlements": SettlementSerializer(
                ordered_municipality_settlements(municipality), many=True
            ).data,
            "categories": IssueCategorySerializer(
                IssueCategory.objects.filter(is_active=True).filter(
                    municipality__in=[municipality, None]
                ),
                many=True,
            ).data,
            "statuses": [
                {"value": "submitted", "label": "Примени"},
                {"value": "verified", "label": "Проверени"},
                {"value": "assigned", "label": "Доделени"},
                {"value": "in_progress", "label": "Во тек"},
                {"value": "resolved", "label": "Решени"},
                {"value": "exceptional", "label": "Исклучителен исход"},
            ],
        },
        "stats": stats,
        "recent_reports": PublicIssueRowSerializer(recent_reports, many=True).data,
        "time_series": time_series,
        "by_settlement": by_settlement,
        "by_category": by_category,
        "performance": {
            "median_review_hours": round(median(review_hours), 1) if review_hours else None,
            "median_resolution_hours": round(median(resolution_hours), 1)
            if resolution_hours
            else None,
            "resolved_within_target_percent": (
                round(sum(resolved_within_target) * 100 / len(resolved_within_target), 1)
                if resolved_within_target
                else None
            ),
        },
        "suppression": {
            "minimum_group_size": MIN_PUBLIC_GROUP_SIZE,
            "suppressed_time_buckets": suppressed_buckets,
            "suppressed_category_groups": suppressed_categories,
            "suppressed_settlement_groups": suppressed_settlements,
            "message": (
                "Групите со помалку од 5 пријави не се прикажуваат за заштита на "
                "приватноста."
            ),
        },
        "definitions": {
            "review": "Време од поднесување до првата службена проверка.",
            "resolution": "Време од поднесување до решавање или затворање.",
            "target": "Удел на решени пријави во општинскиот целен рок.",
        },
        "last_updated": latest,
    }


class PercentileCont(Aggregate):
    function = "PERCENTILE_CONT"
    template = "%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()


def _statistics_filters(request):
    period = request.query_params.get("period", "90")
    if period not in STATISTICS_PERIODS:
        period = "90"
    public_status = request.query_params.get("status", "")
    if public_status not in PUBLIC_STATUS_GROUPS:
        public_status = ""
    def identifier(name):
        value = request.query_params.get(name, "")
        return int(value) if value.isdigit() and int(value) > 0 else ""

    return {
        "period": period,
        "settlement": identifier("settlement"),
        "category": identifier("category"),
        "status": public_status,
    }


def _statistics_queryset(municipality, filters):
    issues = Issue.objects.filter(municipality=municipality, is_spam=False).exclude(
        status=IssueStatus.REJECTED_SPAM
    )
    days = STATISTICS_PERIODS[filters["period"]]
    if days:
        issues = issues.filter(submitted_at__gte=timezone.now() - timedelta(days=days))
    if filters["settlement"]:
        issues = issues.filter(settlement_id=filters["settlement"])
    if filters["category"]:
        issues = issues.filter(category_id=filters["category"])
    if filters["status"]:
        issues = issues.filter(status__in=PUBLIC_STATUS_GROUPS[filters["status"]])
    return issues


def _compute_public_statistics(request, municipality, filters):
    issues = _statistics_queryset(municipality, filters)
    terminal = [
        IssueStatus.RESOLVED,
        IssueStatus.CLOSED,
        IssueStatus.DUPLICATE,
        IssueStatus.REJECTED_SPAM,
        IssueStatus.NOT_JURISDICTION,
    ]
    stats = issues.aggregate(
        total=Count("id"),
        open=Count("id", filter=~Q(status__in=terminal)),
        resolved=Count(
            "id", filter=Q(status__in=[IssueStatus.RESOLVED, IssueStatus.CLOSED])
        ),
        pending=Count("id", filter=Q(status=IssueStatus.PENDING_TRIAGE)),
    )
    settlement_rows = list(
        issues.values("settlement__name").annotate(total=Count("id")).order_by(
            "settlement__name"
        )
    )
    category_rows = list(
        issues.values("category__name").annotate(total=Count("id")).order_by(
            "category__name"
        )
    )
    by_settlement, suppressed_settlements = _suppressed_distribution(
        settlement_rows, "settlement__name"
    )
    by_category, suppressed_categories = _suppressed_distribution(
        category_rows, "category__name"
    )

    truncation = {
        "30": TruncDay("submitted_at"),
        "90": TruncWeek("submitted_at"),
        "365": TruncMonth("submitted_at"),
        "all": TruncMonth("submitted_at"),
    }[filters["period"]]
    bucket_rows = list(
        issues.annotate(bucket=truncation)
        .values("bucket")
        .annotate(total=Count("id"))
        .order_by("bucket")
    )
    time_series = []
    suppressed_buckets = 0
    for row in bucket_rows:
        suppressed = row["total"] < MIN_PUBLIC_GROUP_SIZE
        suppressed_buckets += int(suppressed)
        time_series.append(
            {
                "bucket": row["bucket"].date().isoformat(),
                "total": None if suppressed else row["total"],
                "suppressed": suppressed,
            }
        )

    performance_rows = issues.annotate(
        review_hours=ExpressionWrapper(
            Extract(F("triaged_at") - F("submitted_at"), "epoch") / Value(3600.0),
            output_field=FloatField(),
        ),
        resolution_moment=Coalesce("resolved_at", "closed_at"),
        target_resolution_hours=Coalesce(
            "municipality__response_target__resolution_hours",
            Value(DEFAULT_RESOLUTION_TARGET_HOURS),
        ),
    ).annotate(
        resolution_hours=ExpressionWrapper(
            Extract(F("resolution_moment") - F("submitted_at"), "epoch") / Value(3600.0),
            output_field=FloatField(),
        )
    )
    performance = performance_rows.aggregate(
        median_review_hours=PercentileCont(
            "review_hours", filter=Q(triaged_at__gte=F("submitted_at"))
        ),
        median_resolution_hours=PercentileCont(
            "resolution_hours", filter=Q(resolution_moment__gte=F("submitted_at"))
        ),
        resolved_within_target=Avg(
            Case(
                When(resolution_hours__isnull=True, then=None),
                When(
                    resolution_hours__lte=F("target_resolution_hours"),
                    then=Value(1.0),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            )
        ),
    )
    recent_reports = [
        {
            "title": row["public_title"],
            "submitted_at": row["submitted_at"],
            "status": row["status"],
            "status_label": public_status_label(row["status"]),
        }
        for row in issues.filter(public_title_approved_at__isnull=False)
        .exclude(public_title="")
        .order_by("-submitted_at")
        .values("public_title", "submitted_at", "status")[:20]
    ]
    latest = issues.aggregate(value=Max("updated_at"))["value"]
    return {
        "municipality": MunicipalitySerializer(
            municipality, context={"request": request}
        ).data,
        "applied_filters": {
            key: value or None for key, value in filters.items()
        },
        "filter_options": {
            "settlements": SettlementSerializer(
                ordered_municipality_settlements(municipality), many=True
            ).data,
            "categories": IssueCategorySerializer(
                IssueCategory.objects.filter(is_active=True).filter(
                    municipality__in=[municipality, None]
                ),
                many=True,
            ).data,
            "statuses": [
                {"value": "submitted", "label": "Примени"},
                {"value": "verified", "label": "Проверени"},
                {"value": "assigned", "label": "Доделени"},
                {"value": "in_progress", "label": "Во тек"},
                {"value": "resolved", "label": "Решени"},
                {"value": "exceptional", "label": "Исклучителен исход"},
            ],
        },
        "stats": stats,
        "recent_reports": recent_reports,
        "time_series": time_series,
        "by_settlement": by_settlement,
        "by_category": by_category,
        "performance": {
            "median_review_hours": round(performance["median_review_hours"], 1)
            if performance["median_review_hours"] is not None
            else None,
            "median_resolution_hours": round(performance["median_resolution_hours"], 1)
            if performance["median_resolution_hours"] is not None
            else None,
            "resolved_within_target_percent": round(
                performance["resolved_within_target"] * 100, 1
            )
            if performance["resolved_within_target"] is not None
            else None,
        },
        "suppression": {
            "minimum_group_size": MIN_PUBLIC_GROUP_SIZE,
            "suppressed_time_buckets": suppressed_buckets,
            "suppressed_category_groups": suppressed_categories,
            "suppressed_settlement_groups": suppressed_settlements,
            "message": "Групите со помалку од 5 пријави не се прикажуваат за заштита на приватноста.",
        },
        "definitions": {
            "review": "Време од поднесување до првата службена проверка.",
            "resolution": "Време од поднесување до решавање или затворање.",
            "target": "Удел на решени пријави во општинскиот целен рок.",
        },
        "last_updated": latest,
    }


def build_public_statistics(request, municipality):
    filters = _statistics_filters(request)
    digest = hashlib.sha256(
        json.dumps(filters, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    cache_key = f"statistics:{municipality.pk}:{municipality.statistics_version}:{digest}"
    stale_key = f"statistics:stale:{municipality.pk}:{digest}"
    lock_key = f"statistics:lock:{municipality.pk}:{digest}"
    lock_acquired = False
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        lock_acquired = cache.add(lock_key, True, timeout=15)
        if not lock_acquired:
            stale = cache.get(stale_key)
            if stale is not None:
                return stale
    except Exception:
        lock_acquired = False
    payload = _compute_public_statistics(request, municipality, filters)
    try:
        cache.set(cache_key, payload, timeout=5 * 60)
        cache.set(stale_key, payload, timeout=15 * 60)
        if lock_acquired:
            cache.delete(lock_key)
    except Exception:
        pass
    return payload


@api_view(["GET"])
@permission_classes([AllowAny])
def public_statistics(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    return ok(build_public_statistics(request, municipality))


@api_view(["GET"])
@permission_classes([AllowAny])
def public_statistics_csv(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    payload = build_public_statistics(request, municipality)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="sredi-{municipality.slug}-statistics.csv"'
    )
    response.write("\ufeff")
    csv = writer(response)
    csv.writerow(["Sredi јавна агрегирана статистика", municipality.name])
    csv.writerow(["Филтри", str(payload["applied_filters"])])
    csv.writerow(["Заштита", payload["suppression"]["message"]])
    csv.writerow([])
    csv.writerow(["Димензија", "Група / период", "Број"])
    for row in payload["time_series"]:
        csv.writerow(["период", row["bucket"], "<5" if row["suppressed"] else row["total"]])
    for row in payload["by_category"]:
        csv.writerow(["категорија", row["label"], row["total"]])
    for row in payload["by_settlement"]:
        csv.writerow(["населено место", row["label"], row["total"]])
    for dimension, count in [
        ("период", payload["suppression"]["suppressed_time_buckets"]),
        ("категорија", payload["suppression"]["suppressed_category_groups"]),
        ("населено место", payload["suppression"]["suppressed_settlement_groups"]),
    ]:
        if count:
            csv.writerow(["потиснати групи", dimension, f"{count} групи со <5"])
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def track_issue(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    code = normalize_tracking_code(request.query_params.get("code", ""))
    if not code:
        return fail({"code": ["Внеси код за следење."]})
    issue = (
        Issue.objects.filter(municipality=municipality, tracking_code=code)
        .select_related("settlement", "category")
        .prefetch_related(
            Prefetch(
                "comments",
                queryset=IssueComment.objects.filter(is_internal=False)
                .select_related("author")
                .order_by("-created_at", "-pk")[:100],
                to_attr="public_comments",
            ),
            Prefetch(
                "status_events",
                queryset=IssueStatusEvent.objects.order_by("-created_at", "-pk")[:100],
                to_attr="public_status_events",
            ),
        )
        .first()
    )
    if not issue or not tracking_code_matches(issue, code):
        return fail({"code": ["Не е пронајдена пријава со тој код."]}, status.HTTP_404_NOT_FOUND)
    return ok(TrackedIssueSerializer(issue).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_choices(request):
    profile = getattr(request.user, "staffprofile", None)
    try:
        choices_version = cache.get("staff-choices:version", 1)
        choices_cache_key = (
            f"staff-choices:{choices_version}:{request.user.pk}:"
            f"{getattr(profile, 'municipality_id', 0)}:{int(request.user.is_superuser)}"
        )
        cached_choices = cache.get(choices_cache_key)
        if cached_choices is not None:
            return ok(cached_choices)
    except Exception:
        choices_cache_key = None
    if request.user.is_superuser:
        municipalities = Municipality.objects.all()
        departments = Department.objects.filter(is_active=True).select_related("municipality")
        assignees = get_user_model().objects.filter(staffprofile__isnull=False, is_active=True)
    elif profile and profile.municipality_id:
        municipalities = Municipality.objects.filter(pk=profile.municipality_id)
        departments = Department.objects.filter(
            municipality_id=profile.municipality_id,
            is_active=True,
        ).select_related("municipality")
        assignees = get_user_model().objects.filter(
            staffprofile__municipality_id=profile.municipality_id,
            is_active=True,
        )
    else:
        municipalities = Municipality.objects.none()
        departments = Department.objects.none()
        assignees = get_user_model().objects.none()
    terminal = [
        IssueStatus.RESOLVED,
        IssueStatus.CLOSED,
        IssueStatus.DUPLICATE,
        IssueStatus.REJECTED_SPAM,
        IssueStatus.NOT_JURISDICTION,
    ]
    municipalities = municipalities.annotate(
        active_report_count_value=Count("issues", filter=~Q(issues__status__in=terminal))
    ).prefetch_related(
        Prefetch(
            "public_notices",
            queryset=MunicipalityPublicNotice.objects.filter(
                publication_state=NoticePublicationState.PUBLISHED,
                published_at__isnull=False,
                published_at__lte=timezone.now(),
            ).order_by("-published_at", "-created_at"),
            to_attr="published_public_notices",
        )
    )
    assignees = assignees.select_related(
        "staffprofile__municipality", "staffprofile__department"
    ).annotate(
        two_factor_enabled_annotation=Exists(
            TOTPDevice.objects.filter(user_id=OuterRef("pk"), confirmed=True)
        )
    )
    choices = StaffChoicesSerializer({}).data
    choices.update(
        {
            "municipalities": MunicipalitySerializer(municipalities, many=True).data,
            "departments": DepartmentSerializer(departments, many=True).data,
            "assignees": UserSummarySerializer(assignees.order_by("username"), many=True).data,
            "show_configuration_warning": request.user.is_superuser,
        }
    )
    if choices_cache_key:
        try:
            cache.set(choices_cache_key, choices, timeout=5 * 60)
        except Exception:
            pass
    return ok(choices)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_issues(request):
    issues = staff_filter_queryset(request)
    base = staff_issue_queryset(request.user)
    if request.query_params.get("overdue") == "1":
        issues = issues.filter(target_overdue=True)
    if request.query_params.get("due_soon") == "1":
        issues = issues.filter(target_due_soon=True)

    allowed_sorting = {
        "submitted_at": "submitted_at",
        "-submitted_at": "-submitted_at",
        "updated_at": "updated_at",
        "-updated_at": "-updated_at",
        "title": "title",
        "-title": "-title",
        "status": "status",
        "-status": "-status",
        "priority": "priority",
        "-priority": "-priority",
    }
    sort = request.query_params.get("sort", "-submitted_at")
    issues = issues.order_by(allowed_sorting.get(sort, "-submitted_at"), "-id")
    try:
        page_size = min(100, max(1, int(request.query_params.get("page_size", 25))))
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page_size, page = 25, 1
    total_items = issues.count()
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    rows = [
        add_issue_api_fields(request.user, issue) for issue in issues[start : start + page_size]
    ]
    terminal_statuses = [
        IssueStatus.RESOLVED,
        IssueStatus.CLOSED,
        IssueStatus.DUPLICATE,
        IssueStatus.REJECTED_SPAM,
        IssueStatus.NOT_JURISDICTION,
    ]
    metrics = base.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=IssueStatus.PENDING_TRIAGE)),
        open=Count("id", filter=~Q(status__in=terminal_statuses)),
        my=Count("id", filter=Q(assigned_to=request.user)),
        unassigned=Count("id", filter=Q(assigned_to__isnull=True)),
        overdue=Count("id", filter=Q(target_overdue=True)),
        due_soon=Count("id", filter=Q(target_due_soon=True)),
    )
    return ok(
        {
            "metrics": metrics,
            "items": StaffIssueListSerializer(rows, many=True).data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            },
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def staff_bulk_assign(request):
    raw_items = request.data.get("issues")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 100:
        return fail({"issues": ["Изберете од 1 до 100 пријави со нивните верзии."]})
    try:
        expected_versions = {int(item["id"]): int(item["expected_version"]) for item in raw_items}
        issue_ids = list(expected_versions)
    except (KeyError, TypeError, ValueError):
        return fail({"issues": ["Идентификаторите или верзиите не се валидни."]})
    if len(issue_ids) != len(raw_items):
        return fail({"issues": ["Истата пријава не може да биде избрана двапати."]})

    authorized_ids = staff_issue_queryset(request.user).filter(pk__in=issue_ids).values("pk")
    authorized = list(Issue.objects.select_for_update().filter(pk__in=authorized_ids))
    if len(authorized) != len(issue_ids) or any(
        not can_update_issue_assignment(request.user, issue) for issue in authorized
    ):
        return fail(
            {"detail": "Немате дозвола за една или повеќе избрани пријави."},
            status.HTTP_403_FORBIDDEN,
        )
    stale = [issue for issue in authorized if expected_versions[issue.pk] != issue.version]
    if stale:
        return Response(
            {
                "errors": {"detail": "Една или повеќе пријави се променети."},
                "meta": {"current_versions": {str(issue.pk): issue.version for issue in stale}},
            },
            status=status.HTTP_409_CONFLICT,
        )
    municipality_ids = {issue.municipality_id for issue in authorized}
    if len(municipality_ids) != 1:
        return fail({"issue_ids": ["Сите избрани пријави мора да бидат од иста општина."]})
    municipality_id = municipality_ids.pop()

    department_id = request.data.get("department_id") or None
    assignee_id = request.data.get("assignee_id") or None
    if not department_id and not assignee_id:
        return fail({"detail": "Изберете одделение или задолжен службеник."})
    department = None
    assignee = None
    if department_id:
        department = get_object_or_404(
            Department,
            pk=department_id,
            municipality_id=municipality_id,
            is_active=True,
        )
    if assignee_id:
        assignee = get_object_or_404(
            get_user_model(),
            pk=assignee_id,
            staffprofile__municipality_id=municipality_id,
            is_active=True,
        )

    now = timezone.now()
    for issue in authorized:
        old_values = {
            "assigned_department_id": issue.assigned_department_id,
            "assigned_to_id": issue.assigned_to_id,
        }
        if department:
            issue.assigned_department = department
        if assignee:
            issue.assigned_to = assignee
        issue.assigned_at = issue.assigned_at or now
        issue.version += 1
        issue.save(
            update_fields=[
                "assigned_department",
                "assigned_to",
                "assigned_at",
                "version",
                "updated_at",
            ]
        )
        write_audit_log(
            request.user,
            "issue_bulk_assigned",
            issue=issue,
            metadata={
                "from": old_values,
                "to": {
                    "assigned_department_id": issue.assigned_department_id,
                    "assigned_to_id": issue.assigned_to_id,
                },
            },
        )
    return ok(
        {
            "updated": len(authorized),
            "issues": [{"id": issue.pk, "version": issue.version} for issue in authorized],
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def staff_issue_detail(request, pk):
    if request.method == "PATCH":
        issue = get_object_or_404(
            staff_issue_queryset(request.user).select_for_update(of=("self",)), pk=pk
        )
        if not can_update_issue_assignment(request.user, issue):
            return fail(
                {"detail": "Немате дозвола да ја ажурирате пријавата."}, status.HTTP_403_FORBIDDEN
            )
        conflict = check_expected_version(request, issue)
        if conflict:
            return conflict
        old_values = {
            "priority": issue.priority,
            "assigned_department_id": issue.assigned_department_id,
            "assigned_to_id": issue.assigned_to_id,
            "internal_note": issue.internal_note,
            "public_resolution_note": issue.public_resolution_note,
        }
        form = StaffIssueUpdateForm(request.data, instance=issue, issue=issue)
        if not form.is_valid():
            return fail(form.errors)
        issue.version += 1
        form.save()
        issue.refresh_from_db()
        new_values = {
            "priority": issue.priority,
            "assigned_department_id": issue.assigned_department_id,
            "assigned_to_id": issue.assigned_to_id,
            "internal_note": issue.internal_note,
            "public_resolution_note": issue.public_resolution_note,
        }
        write_audit_log(
            request.user,
            "issue_updated",
            issue=issue,
            metadata={
                key: {"from": old_values[key], "to": new_values[key]}
                for key in old_values
                if old_values[key] != new_values[key]
            },
        )
        publish_resolution_note_update(
            issue,
            request.user,
            old_values["public_resolution_note"],
        )
    issue = load_staff_issue_detail(request.user, pk)
    return ok(StaffIssueDetailSerializer(issue).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def approve_public_title(request, pk):
    issue = get_object_or_404(
        staff_issue_queryset(request.user).select_for_update(of=("self",)), pk=pk
    )
    if not can_moderate_public_title(request.user, issue):
        return fail(
            {"detail": "Немате дозвола да одобрувате јавни наслови."},
            status.HTTP_403_FORBIDDEN,
        )
    conflict = check_expected_version(request, issue)
    if conflict:
        return conflict
    if issue.is_spam or issue.status == IssueStatus.REJECTED_SPAM:
        return fail({"detail": "Спам пријава не може да има јавен наслов."})
    public_title = " ".join(str(request.data.get("public_title", "")).split())
    if len(public_title) < 5 or len(public_title) > 180:
        return fail({"public_title": ["Насловот мора да содржи од 5 до 180 знаци."]})
    action = "issue_public_title_edited" if issue.public_title_approved_at else "issue_public_title_approved"
    issue.public_title = public_title
    issue.public_title_approved_at = timezone.now()
    issue.public_title_approved_by = request.user
    issue.version += 1
    issue.save(
        update_fields=[
            "public_title",
            "public_title_approved_at",
            "public_title_approved_by",
            "version",
            "updated_at",
        ]
    )
    write_audit_log(
        request.user,
        action,
        issue=issue,
        metadata={"public_title": public_title},
    )
    return ok(StaffIssueDetailSerializer(load_staff_issue_detail(request.user, pk)).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def revoke_public_title(request, pk):
    issue = get_object_or_404(
        staff_issue_queryset(request.user).select_for_update(of=("self",)), pk=pk
    )
    if not can_moderate_public_title(request.user, issue):
        return fail(
            {"detail": "Немате дозвола да повлекувате јавни наслови."},
            status.HTTP_403_FORBIDDEN,
        )
    conflict = check_expected_version(request, issue)
    if conflict:
        return conflict
    was_approved = bool(issue.public_title_approved_at)
    issue.public_title = ""
    issue.public_title_approved_at = None
    issue.public_title_approved_by = None
    issue.version += 1
    issue.save(
        update_fields=[
            "public_title",
            "public_title_approved_at",
            "public_title_approved_by",
            "version",
            "updated_at",
        ]
    )
    if was_approved:
        write_audit_log(request.user, "issue_public_title_revoked", issue=issue)
    return ok(StaffIssueDetailSerializer(load_staff_issue_detail(request.user, pk)).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def staff_issue_status(request, pk):
    issue = get_object_or_404(
        staff_issue_queryset(request.user).select_for_update(of=("self",)), pk=pk
    )
    new_status = request.data.get("status")
    note = request.data.get("note", "")
    valid = {choice[0] for choice in IssueStatus.choices}
    if new_status not in valid:
        return fail({"status": ["Невалиден статус."]})
    if not can_change_issue_status(request.user, issue, new_status):
        return fail(
            {"detail": "Немате дозвола да го промените статусот."}, status.HTTP_403_FORBIDDEN
        )
    conflict = check_expected_version(request, issue)
    if conflict:
        return conflict
    if status_requires_note(new_status) and not note.strip():
        return fail({"note": ["За овој статус мора да внесете белешка."]})
    if len(note) > 2000:
        return fail({"note": ["Белешката може да содржи најмногу 2.000 знаци."]})
    old_status = issue.status
    old_department_id = issue.assigned_department_id
    apply_default_department(issue, new_status)
    status_event = issue.mark_status(new_status, user=request.user, note=note)
    write_audit_log(
        request.user,
        "issue_status_changed",
        issue=issue,
        metadata={
            "from_status": old_status,
            "to_status": new_status,
            "status_event_id": status_event.pk if status_event else None,
            "default_department_applied": bool(
                not old_department_id and issue.assigned_department_id
            ),
        },
    )
    return ok(StaffIssueDetailSerializer(load_staff_issue_detail(request.user, pk)).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def staff_issue_comments(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    if not can_add_issue_comment(request.user, issue):
        return fail({"detail": "Немате дозвола да додадете коментар."}, status.HTTP_403_FORBIDDEN)
    form = IssueCommentForm(request.data)
    if not form.is_valid():
        return fail(form.errors)
    comment = form.save(commit=False)
    comment.issue = issue
    comment.author = request.user
    comment.save()
    write_audit_log(
        request.user,
        "issue_comment_added",
        issue=issue,
        metadata={"comment_id": comment.pk, "is_internal": comment.is_internal},
    )
    return ok(StaffIssueDetailSerializer(load_staff_issue_detail(request.user, pk)).data)


def _history_page(request, queryset, serializer_class):
    try:
        limit = min(100, max(1, int(request.query_params.get("limit", 50))))
    except ValueError:
        limit = 50
    cursor = request.query_params.get("cursor")
    if cursor:
        try:
            queryset = queryset.filter(pk__lt=int(cursor))
        except ValueError:
            return None, fail({"cursor": ["Курсорот не е валиден."]})
    rows = list(queryset.order_by("-created_at", "-pk")[: limit + 1])
    has_next = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": serializer_class(rows, many=True).data,
        "next_cursor": str(rows[-1].pk) if has_next and rows else None,
    }, None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_issue_comment_history(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    queryset = IssueComment.objects.filter(issue=issue).select_related("author")
    total = queryset.count()
    payload, error = _history_page(request, queryset, IssueCommentSerializer)
    if error:
        return error
    payload["total"] = total
    return ok(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_issue_status_history(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    queryset = IssueStatusEvent.objects.filter(issue=issue).select_related("changed_by")
    total = queryset.count()
    payload, error = _history_page(request, queryset, IssueStatusEventSerializer)
    if error:
        return error
    payload["total"] = total
    return ok(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_issue_audit_history(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    queryset = AuditLog.objects.filter(
        object_type="Issue", object_id=str(issue.pk)
    ).select_related("actor")
    total = queryset.count()
    payload, error = _history_page(request, queryset, AuditLogSerializer)
    if error:
        return error
    payload["total"] = total
    return ok(payload)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def staff_issue_legal_hold(request, pk):
    issue = get_object_or_404(
        staff_issue_queryset(request.user).select_for_update(of=("self",)), pk=pk
    )
    if not can_manage_legal_hold(request.user, issue):
        return fail(
            {"detail": "Немате дозвола да управувате со правно задржување."},
            status.HTTP_403_FORBIDDEN,
        )
    conflict = check_expected_version(request, issue)
    if conflict:
        return conflict
    active = request.data.get("active")
    if not isinstance(active, bool):
        return fail({"active": ["Испратете true или false."]})
    reason = str(request.data.get("reason", "")).strip()
    if active and not reason:
        return fail({"reason": ["Причината е задолжителна при вклучување."]})
    if len(reason) > 2000:
        return fail({"reason": ["Причината може да содржи најмногу 2.000 знаци."]})
    issue.legal_hold_active = active
    issue.legal_hold_reason = reason if active else ""
    issue.legal_hold_set_by = request.user
    issue.legal_hold_set_at = timezone.now()
    issue.version += 1
    issue.save(
        update_fields=[
            "legal_hold_active",
            "legal_hold_reason",
            "legal_hold_set_by",
            "legal_hold_set_at",
            "version",
            "updated_at",
        ]
    )
    write_audit_log(
        request.user,
        "issue_legal_hold_enabled" if active else "issue_legal_hold_released",
        issue=issue,
        metadata={"reason": reason if active else ""},
    )
    return ok(StaffIssueDetailSerializer(load_staff_issue_detail(request.user, pk)).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_attachment(request, pk):
    attachment = get_object_or_404(
        IssueAttachment.objects.select_related("issue"),
        pk=pk,
        issue__in=staff_issue_queryset(request.user),
    )
    if attachment.deletion_state != AttachmentDeletionState.ACTIVE:
        return fail(
            {"detail": "Фотографијата е избришана согласно политиката за задржување."},
            status.HTTP_410_GONE,
        )
    content_type = mimetypes.guess_type(attachment.image.name)[0] or "application/octet-stream"
    response = FileResponse(
        attachment.image.open("rb"),
        content_type=content_type,
        as_attachment=False,
        filename=Path(attachment.image.name).name,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def staff_users(request):
    if not request.user.is_superuser:
        return fail(
            {"detail": "Само администратор на платформата може да креира службени корисници."},
            status.HTTP_403_FORBIDDEN,
        )
    serializer = StaffUserCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return fail(serializer.errors)
    user = serializer.save()
    write_audit_log(
        request.user,
        "staff_user_created",
        municipality=user.staffprofile.municipality,
        metadata={
            "created_user_id": user.pk,
            "created_username": user.get_username(),
            "role": user.staffprofile.role,
            "department_id": user.staffprofile.department_id,
        },
    )
    return ok(UserSummarySerializer(user).data, status_code=status.HTTP_201_CREATED)
