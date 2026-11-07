import csv

from django.contrib import admin
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from apps.issues.models import (
    AuditLog,
    DataRetentionPolicy,
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueComment,
    IssueDuplicateLink,
    IssueStatusEvent,
    ReceiptDelivery,
    ResponseTarget,
)


@admin.action(description="Повторно испрати избрани неуспешни потврди")
def retry_failed_receipts(modeladmin, request, queryset):
    with transaction.atomic():
        updated = queryset.filter(state="failed").exclude(recipient="").update(
            state="queued", attempt_count=0, next_attempt_at=timezone.now(),
            dispatched_at=None, lease_until=None, failed_at=None, last_error="",
        )
        AuditLog.objects.create(actor=request.user, action="receipt_deliveries_requeued",
                                object_type="ReceiptDelivery", metadata={"count": updated})
    modeladmin.message_user(request, f"Потврди ставени во редица: {updated}")


@admin.register(ReceiptDelivery)
class ReceiptDeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "issue", "state", "attempt_count", "queued_at", "last_attempt_at", "last_error"]
    list_filter = ["state"]
    actions = [retry_failed_receipts]
    readonly_fields = [field.name for field in ReceiptDelivery._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Export selected issues as CSV")
def export_issues_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="issues.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "tracking_code",
            "municipality",
            "settlement",
            "category",
            "status",
            "priority",
            "submitted_at",
            "is_anonymous",
        ]
    )
    for issue in queryset.select_related("municipality", "settlement", "category"):
        writer.writerow(
            [
                issue.tracking_code,
                issue.municipality.name,
                issue.settlement.name,
                issue.category.name,
                issue.status,
                issue.priority,
                issue.submitted_at.isoformat(),
                issue.is_anonymous,
            ]
        )
    AuditLog.objects.create(
        actor=request.user,
        action="admin_issues_exported",
        object_type="Issue",
        metadata={"issue_ids": list(queryset.values_list("id", flat=True))},
    )
    return response


@admin.action(description="Anonymize selected citizen contact fields")
def anonymize_citizen_contact(modeladmin, request, queryset):
    issue_ids = list(queryset.values_list("id", flat=True))
    queryset.update(citizen_name="", citizen_email="", citizen_phone="", is_anonymous=True)
    AuditLog.objects.create(
        actor=request.user,
        action="admin_issue_contacts_anonymized",
        object_type="Issue",
        metadata={"issue_ids": issue_ids},
    )


class IssueAttachmentInline(admin.TabularInline):
    model = IssueAttachment
    extra = 0


class IssueStatusEventInline(admin.TabularInline):
    model = IssueStatusEvent
    extra = 0
    readonly_fields = ["from_status", "to_status", "changed_by", "note", "created_at"]
    can_delete = False


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["tracking_code", "title", "municipality", "settlement", "category", "status", "submitted_at"]
    list_filter = ["municipality", "settlement", "category", "status", "priority", "is_anonymous"]
    search_fields = ["tracking_code", "title", "description", "location_text"]
    readonly_fields = ["tracking_code", "submitted_at", "updated_at"]
    inlines = [IssueAttachmentInline, IssueStatusEventInline]
    actions = [export_issues_csv, anonymize_citizen_contact]


@admin.register(IssueCategory)
class IssueCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "municipality", "default_department", "is_active"]
    list_filter = ["municipality", "is_active"]
    search_fields = ["name"]


admin.site.register(IssueAttachment)
admin.site.register(IssueStatusEvent)
admin.site.register(IssueComment)
admin.site.register(IssueDuplicateLink)
@admin.register(ResponseTarget)
class ResponseTargetAdmin(admin.ModelAdmin):
    list_display = ["municipality", "review_hours", "resolution_hours"]
    list_select_related = ["municipality"]


admin.site.register(AuditLog)
admin.site.register(DataRetentionPolicy)
