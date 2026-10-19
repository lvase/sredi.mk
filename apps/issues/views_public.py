from django.contrib import messages
from django.db.models import Count, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.issues.forms import CitizenIssueForm
from apps.issues.image_processing import (
    IssueImageValidationError,
    prepare_issue_images,
    save_issue_with_attachments,
)
from apps.issues.models import (
    Issue,
    IssueComment,
    IssueStatus,
    IssueStatusEvent,
)
from apps.issues.public_updates import build_public_updates
from apps.issues.services import (
    calculate_suspicious_assessment,
    consume_submission_rate_limit,
    get_client_ip,
    hash_client_value,
    normalize_tracking_code,
    public_status_label,
    tracking_code_matches,
)
from apps.municipalities.models import Municipality
from config.throttling import SharedThrottleUnavailable


def get_municipality_or_404(municipality_slug):
    return get_object_or_404(Municipality, slug=municipality_slug, is_active=True)


def sredi_home(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    return render(request, "issues/public/home.html", {"municipality": municipality})


def public_dashboard(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    issues = Issue.objects.filter(municipality=municipality, is_spam=False).exclude(
        status=IssueStatus.REJECTED_SPAM
    )
    stats = {
        "total": issues.count(),
        "open": issues.exclude(status__in=[IssueStatus.RESOLVED, IssueStatus.CLOSED]).count(),
        "resolved": issues.filter(status__in=[IssueStatus.RESOLVED, IssueStatus.CLOSED]).count(),
        "pending": issues.filter(status=IssueStatus.PENDING_TRIAGE).count(),
    }
    by_settlement = issues.values("settlement__name").annotate(total=Count("id")).order_by("settlement__name")
    by_category = issues.values("category__name").annotate(total=Count("id")).order_by("category__name")
    public_issues = issues.select_related("settlement", "category").order_by("-submitted_at")
    return render(
        request,
        "issues/public/dashboard.html",
        {
            "municipality": municipality,
            "stats": stats,
            "by_settlement": by_settlement,
            "by_category": by_category,
            "public_issues": public_issues,
        },
    )


def submit_issue(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    if request.method == "POST":
        form = CitizenIssueForm(request.POST, request.FILES, municipality=municipality)
        files = request.FILES.getlist("photos")
        form_is_valid = form.is_valid()
        if form_is_valid:
            ip_hash = hash_client_value(get_client_ip(request))
            try:
                allowed, rate_state = consume_submission_rate_limit(municipality, ip_hash)
            except SharedThrottleUnavailable:
                return HttpResponse(
                    "Заштитата е привремено недостапна. Обиди се повторно.",
                    status=503,
                    headers={"Retry-After": "60"},
                )
            if not allowed:
                messages.error(
                    request,
                    f"Испратени се премногу пријави од оваа мрежа. Обиди се повторно за приближно {max(1, (rate_state.retry_after_seconds + 59) // 60)} минути.",
                )
            else:
                try:
                    processed_images = prepare_issue_images(files)
                except IssueImageValidationError as exc:
                    for error in exc.errors:
                        messages.error(request, error)
                    return render(
                        request,
                        "issues/public/report_form.html",
                        {"form": form, "municipality": municipality},
                    )
                issue = form.save(commit=False)
                issue.municipality = municipality
                issue.submitted_ip_hash = ip_hash
                issue.submitted_user_agent_hash = hash_client_value(
                    request.META.get("HTTP_USER_AGENT", "")[:500]
                )
                issue.suspicious_score, issue.suspicious_reasons = (
                    calculate_suspicious_assessment(
                        files,
                        rate_state,
                        municipality=municipality,
                        ip_hash=ip_hash,
                        description=issue.description,
                        location_text=issue.location_text,
                    )
                )
                save_issue_with_attachments(issue, processed_images)
                return render(
                    request,
                    "issues/public/report_success.html",
                    {"issue": issue, "municipality": municipality},
                )
    else:
        form = CitizenIssueForm(municipality=municipality)

    return render(
        request,
        "issues/public/report_form.html",
        {"form": form, "municipality": municipality},
    )


def track_issue(request, municipality_slug):
    municipality = get_municipality_or_404(municipality_slug)
    code = normalize_tracking_code(request.GET.get("code", ""))
    issue = None
    if code:
        candidate = (
            Issue.objects.filter(
                municipality=municipality,
                tracking_code=code,
            )
            .prefetch_related(
                Prefetch(
                    "comments",
                    queryset=IssueComment.objects.filter(is_internal=False).select_related(
                        "author"
                    ).order_by("-created_at", "-pk")[:100],
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
        if candidate and tracking_code_matches(candidate, code):
            issue = candidate
            issue.public_updates = build_public_updates(issue)
            issue.latest_public_update = issue.public_updates[-1]
        else:
            messages.error(request, "Не е пронајдена пријава со тој код.")
    return render(
        request,
        "issues/public/track.html",
        {
            "issue": issue,
            "code": code,
            "municipality": municipality,
            "public_status_label": public_status_label,
        },
    )
