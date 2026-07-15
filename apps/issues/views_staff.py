from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import StaffUserCreateForm
from apps.issues.forms import IssueCommentForm, StaffIssueUpdateForm
from apps.issues.models import AuditLog, Issue, IssueCategory, IssuePriority, IssueStatus
from apps.issues.services import (
    apply_default_department,
    can_add_issue_comment,
    can_change_issue_status,
    can_staff_access_issue,
    can_update_issue_assignment,
    is_issue_overdue,
    publish_resolution_note_update,
    status_requires_note,
    write_audit_log,
)
from apps.municipalities.models import Department, Municipality, Settlement


def staff_issue_queryset(user):
    qs = Issue.objects.select_related(
        "municipality", "settlement", "category", "assigned_department", "assigned_to"
    )
    if user.is_superuser:
        return qs
    profile = getattr(user, "staffprofile", None)
    if not profile or not profile.municipality_id:
        return Issue.objects.none()
    return qs.filter(municipality_id=profile.municipality_id)


def quick_status_actions(user, issue):
    candidates = [
        IssueStatus.ACCEPTED,
        IssueStatus.ASSIGNED,
        IssueStatus.IN_PROGRESS,
    ]
    return [
        (status, IssueStatus(status).label)
        for status in candidates
        if status != issue.status and can_change_issue_status(user, issue, status)
    ]


@login_required
def staff_dashboard(request):
    issues = staff_issue_queryset(request.user)
    municipality = request.GET.get("municipality")
    status = request.GET.get("status")
    settlement = request.GET.get("settlement")
    category = request.GET.get("category")
    priority = request.GET.get("priority")
    department = request.GET.get("department")
    assigned_to = request.GET.get("assigned_to")
    mine = request.GET.get("mine")
    overdue = request.GET.get("overdue")
    if municipality:
        issues = issues.filter(municipality_id=municipality)
    if status:
        issues = issues.filter(status=status)
    if settlement:
        issues = issues.filter(settlement_id=settlement)
    if category:
        issues = issues.filter(category_id=category)
    if priority:
        issues = issues.filter(priority=priority)
    if department:
        issues = issues.filter(assigned_department_id=department)
    if assigned_to:
        issues = issues.filter(assigned_to_id=assigned_to)
    if mine:
        issues = issues.filter(assigned_to=request.user)

    base = staff_issue_queryset(request.user)
    stats = base.values("status").annotate(total=Count("id"))
    municipalities = Municipality.objects.none()
    settlements = Settlement.objects.none()
    categories = IssueCategory.objects.none()
    departments = []
    assignees = get_user_model().objects.none()
    profile = getattr(request.user, "staffprofile", None)
    if request.user.is_superuser:
        municipalities = Municipality.objects.all()
        settlements = Settlement.objects.filter(is_active=True)
        categories = IssueCategory.objects.filter(is_active=True)
        departments = Department.objects.filter(is_active=True)
        assignees = get_user_model().objects.filter(staffprofile__isnull=False, is_active=True)
    elif profile and profile.municipality_id:
        municipalities = Municipality.objects.filter(pk=profile.municipality_id)
        settlements = Settlement.objects.filter(
            municipality_id=profile.municipality_id,
            is_active=True,
        )
        categories = IssueCategory.objects.filter(
            municipality_id=profile.municipality_id,
            is_active=True,
        )
        departments = Department.objects.filter(
            municipality_id=profile.municipality_id,
            is_active=True,
        )
        assignees = get_user_model().objects.filter(
            staffprofile__municipality_id=profile.municipality_id,
            is_active=True,
        )
    issue_rows = []
    for issue in issues[:100]:
        issue_overdue = is_issue_overdue(issue)
        issue_rows.append(
            {
                "issue": issue,
                "is_overdue": issue_overdue,
                "can_change_status": can_change_issue_status(request.user, issue),
                "quick_status_actions": quick_status_actions(request.user, issue),
            }
        )
    if overdue == "1":
        issue_rows = [row for row in issue_rows if row["is_overdue"]]
    base_sample = list(base[:100])
    dashboard_metrics = {
        "total": base.count(),
        "pending": base.filter(status=IssueStatus.PENDING_TRIAGE).count(),
        "open": base.exclude(status__in=[IssueStatus.RESOLVED, IssueStatus.CLOSED]).count(),
        "my": base.filter(assigned_to=request.user).count(),
        "overdue": sum(1 for issue in base_sample if is_issue_overdue(issue)),
    }

    return render(
        request,
        "issues/staff/dashboard.html",
        {
            "issue_rows": issue_rows,
            "status_choices": IssueStatus.choices,
            "priority_choices": IssuePriority.choices,
            "stats": stats,
            "municipalities": municipalities,
            "settlements": settlements,
            "categories": categories,
            "departments": departments,
            "assignees": assignees,
            "dashboard_metrics": dashboard_metrics,
            "selected_municipality": municipality or "",
            "selected_status": status or "",
            "selected_settlement": settlement or "",
            "selected_category": category or "",
            "selected_priority": priority or "",
            "selected_department": department or "",
            "selected_assigned_to": assigned_to or "",
            "selected_mine": mine or "",
            "selected_overdue": overdue or "",
        },
    )


@login_required
def staff_issue_detail(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    if not can_staff_access_issue(request.user, issue):
        return HttpResponseForbidden("Немате пристап до оваа пријава.")
    return render(
        request,
        "issues/staff/issue_detail.html",
        {
            "issue": issue,
            "status_choices": IssueStatus.choices,
            "update_form": StaffIssueUpdateForm(instance=issue, issue=issue),
            "comment_form": IssueCommentForm(initial={"is_internal": True}),
            "can_update_issue": can_update_issue_assignment(request.user, issue),
            "can_change_status": can_change_issue_status(request.user, issue),
            "can_add_comment": can_add_issue_comment(request.user, issue),
            "audit_logs": AuditLog.objects.filter(
                object_type="Issue",
                object_id=str(issue.pk),
            )[:20],
        },
    )


@login_required
def staff_change_status(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    if request.method != "POST":
        return redirect("staff_issue_detail", pk=issue.pk)
    new_status = request.POST.get("status")
    note = request.POST.get("note", "")
    if not can_change_issue_status(request.user, issue, new_status):
        return HttpResponseForbidden("Немате дозвола да го промените статусот.")
    valid = {choice[0] for choice in IssueStatus.choices}
    if new_status not in valid:
        messages.error(request, "Невалиден статус.")
        return redirect("staff_issue_detail", pk=issue.pk)
    if status_requires_note(new_status) and not note.strip():
        messages.error(request, "За овој статус мора да внесете белешка.")
        return redirect("staff_issue_detail", pk=issue.pk)
    old_status = issue.status
    old_department_id = issue.assigned_department_id
    apply_default_department(issue, new_status)
    issue.mark_status(new_status, user=request.user, note=note)
    write_audit_log(
        request.user,
        "issue_status_changed",
        issue=issue,
        metadata={
            "from_status": old_status,
            "to_status": new_status,
            "note": note,
            "default_department_applied": bool(
                not old_department_id and issue.assigned_department_id
            ),
        },
    )
    messages.success(request, "Статусот е ажуриран.")
    return redirect("staff_issue_detail", pk=issue.pk)


@login_required
def staff_update_issue(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    if request.method != "POST":
        return redirect("staff_issue_detail", pk=issue.pk)
    if not can_update_issue_assignment(request.user, issue):
        return HttpResponseForbidden("Немате дозвола да ја ажурирате пријавата.")
    old_values = {
        "priority": issue.priority,
        "assigned_department_id": issue.assigned_department_id,
        "assigned_to_id": issue.assigned_to_id,
        "internal_note": issue.internal_note,
        "public_resolution_note": issue.public_resolution_note,
    }
    form = StaffIssueUpdateForm(request.POST, instance=issue, issue=issue)
    if form.is_valid():
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
        messages.success(request, "Пријавата е ажурирана.")
    else:
        messages.error(request, "Проверете ги полињата за ажурирање.")
    return redirect("staff_issue_detail", pk=issue.pk)


@login_required
def staff_add_comment(request, pk):
    issue = get_object_or_404(staff_issue_queryset(request.user), pk=pk)
    if request.method != "POST":
        return redirect("staff_issue_detail", pk=issue.pk)
    if not can_add_issue_comment(request.user, issue):
        return HttpResponseForbidden("Немате дозвола да додадете коментар.")
    form = IssueCommentForm(request.POST)
    if form.is_valid():
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
        messages.success(request, "Коментарот е додаден.")
    else:
        messages.error(request, "Коментарот не е зачуван.")
    return redirect("staff_issue_detail", pk=issue.pk)


@login_required
def staff_create_user(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Само администратор на платформата може да креира службени корисници.")
    if request.method == "POST":
        form = StaffUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
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
            messages.success(request, "Службениот корисник е креиран.")
            return redirect("staff_dashboard")
    else:
        form = StaffUserCreateForm()
    return render(request, "issues/staff/create_user.html", {"form": form})
