from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import StaffProfile, StaffRole
from apps.accounts.security import confirmed_totp_device
from apps.issues.models import (
    AuditLog,
    Issue,
    IssueCategory,
    IssueComment,
    IssuePriority,
    IssueStatus,
)
from apps.issues.public_updates import build_public_updates
from apps.issues.services import public_status_label
from apps.municipalities.models import (
    Department,
    Municipality,
    MunicipalityPublicNotice,
    NoticePublicationState,
    Settlement,
)


class ChoiceSerializerMixin:
    @staticmethod
    def choices_payload(choices):
        return [{"value": value, "label": label} for value, label in choices]


class MunicipalityPublicNoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MunicipalityPublicNotice
        fields = ["id", "title", "summary", "body", "published_at"]


class MunicipalitySerializer(serializers.ModelSerializer):
    active_report_count = serializers.SerializerMethodField()
    latest_public_notice = serializers.SerializerMethodField()
    official_coat_of_arms_url = serializers.SerializerMethodField()

    class Meta:
        model = Municipality
        fields = [
            "id",
            "name",
            "slug",
            "configuration_status",
            "public_accent_color",
            "official_coat_of_arms_url",
            "active_report_count",
            "latest_public_notice",
        ]

    def get_active_report_count(self, municipality):
        return municipality.issues.exclude(
            status__in=[
                IssueStatus.RESOLVED,
                IssueStatus.CLOSED,
                IssueStatus.DUPLICATE,
                IssueStatus.REJECTED_SPAM,
                IssueStatus.NOT_JURISDICTION,
            ]
        ).count()

    def get_latest_public_notice(self, municipality):
        notice = municipality.public_notices.filter(
            publication_state=NoticePublicationState.PUBLISHED,
            published_at__isnull=False,
            published_at__lte=timezone.now(),
        ).first()
        return MunicipalityPublicNoticeSerializer(notice).data if notice else None

    def get_official_coat_of_arms_url(self, municipality):
        if not municipality.official_coat_of_arms:
            return None
        request = self.context.get("request")
        url = reverse("api_municipality_crest", args=[municipality.slug])
        return request.build_absolute_uri(url) if request else url


class SettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settlement
        fields = ["id", "name"]


class DepartmentSerializer(serializers.ModelSerializer):
    municipality = MunicipalitySerializer(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "municipality"]


class IssueCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueCategory
        fields = ["id", "name", "description", "default_department"]


class UserSummarySerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="staffprofile.role", read_only=True)
    municipality = MunicipalitySerializer(source="staffprofile.municipality", read_only=True)
    department = DepartmentSerializer(source="staffprofile.department", read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    two_factor_enabled = serializers.SerializerMethodField()
    must_change_password = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "username",
            "email",
            "is_superuser",
            "role",
            "municipality",
            "department",
            "two_factor_enabled",
            "must_change_password",
        ]

    def get_two_factor_enabled(self, user):
        return bool(confirmed_totp_device(user))

    def get_must_change_password(self, user):
        profile = getattr(user, "staffprofile", None)
        return bool(profile and profile.must_change_password)


class PublicIssueRowSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="public_title")
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = ["title", "submitted_at", "status", "status_label"]

    def get_status_label(self, issue):
        return public_status_label(issue.status)


class PublicCommentSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source="author.get_username")

    class Meta:
        model = IssueComment
        fields = ["id", "body", "author", "created_at"]


class PublicUpdateSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["submitted", "comment", "status", "note"])
    title = serializers.CharField()
    body = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    status_label = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class TrackedIssueSerializer(serializers.ModelSerializer):
    settlement = serializers.CharField(source="settlement.name")
    category = serializers.CharField(source="category.name")
    status_label = serializers.SerializerMethodField()
    public_comments = serializers.SerializerMethodField()
    public_updates = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            "id",
            "tracking_code",
            "title",
            "settlement",
            "category",
            "status",
            "status_label",
            "submitted_at",
            "updated_at",
            "public_comments",
            "public_updates",
        ]

    def get_public_comments(self, issue):
        comments = getattr(issue, "public_comments", None)
        if comments is None:
            comments = issue.comments.filter(is_internal=False).select_related("author")
        return PublicCommentSerializer(comments, many=True).data

    def get_status_label(self, issue):
        return public_status_label(issue.status)

    def get_public_updates(self, issue):
        return PublicUpdateSerializer(build_public_updates(issue), many=True).data


class IssueAttachmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.SerializerMethodField()
    uploaded_at = serializers.DateTimeField()

    def get_url(self, attachment):
        return reverse("api_staff_attachment", args=[attachment.pk])


class IssueCommentSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source="author.get_username")

    class Meta:
        model = IssueComment
        fields = ["id", "body", "is_internal", "author", "created_at"]


class IssueStatusEventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    to_status_label = serializers.CharField(source="get_to_status_display")
    changed_by = serializers.CharField(source="changed_by.get_username", allow_null=True)
    note = serializers.CharField()
    created_at = serializers.DateTimeField()


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", allow_null=True)

    class Meta:
        model = AuditLog
        fields = ["id", "action", "actor", "metadata", "created_at"]


class StaffIssueListSerializer(serializers.ModelSerializer):
    municipality = serializers.CharField(source="municipality.name")
    municipality_id = serializers.IntegerField(read_only=True)
    settlement = serializers.CharField(source="settlement.name")
    category = serializers.CharField(source="category.name")
    assigned_department = serializers.CharField(source="assigned_department.name", allow_null=True)
    assigned_department_id = serializers.IntegerField(read_only=True)
    assigned_to = serializers.CharField(source="assigned_to.get_username", allow_null=True)
    assigned_to_id = serializers.IntegerField(read_only=True)
    status_label = serializers.CharField(source="get_status_display")
    priority_label = serializers.CharField(source="get_priority_display")
    is_overdue = serializers.BooleanField(read_only=True)
    is_due_soon = serializers.BooleanField(read_only=True)
    quick_status_actions = serializers.ListField(read_only=True)
    public_title = serializers.CharField()
    public_title_approved_at = serializers.DateTimeField(allow_null=True)

    class Meta:
        model = Issue
        fields = [
            "id",
            "tracking_code",
            "title",
            "public_title",
            "public_title_approved_at",
            "municipality",
            "municipality_id",
            "settlement",
            "category",
            "location_text",
            "status",
            "status_label",
            "priority",
            "priority_label",
            "assigned_department",
            "assigned_department_id",
            "assigned_to",
            "assigned_to_id",
            "submitted_at",
            "updated_at",
            "is_overdue",
            "is_due_soon",
            "quick_status_actions",
        ]


class StaffIssueDetailSerializer(StaffIssueListSerializer):
    description = serializers.CharField()
    citizen_name = serializers.CharField()
    citizen_email = serializers.EmailField()
    citizen_phone = serializers.CharField()
    is_anonymous = serializers.BooleanField()
    suspicious_score = serializers.IntegerField()
    suspicious_reasons = serializers.ListField(child=serializers.DictField(), read_only=True)
    public_resolution_note = serializers.CharField()
    internal_note = serializers.CharField()
    attachments = IssueAttachmentSerializer(many=True)
    comments = IssueCommentSerializer(many=True)
    status_events = IssueStatusEventSerializer(many=True)
    audit_logs = serializers.SerializerMethodField()
    permissions = serializers.DictField(read_only=True)
    public_title_approved_by = serializers.CharField(
        source="public_title_approved_by.get_username", allow_null=True
    )

    class Meta(StaffIssueListSerializer.Meta):
        fields = StaffIssueListSerializer.Meta.fields + [
            "description",
            "citizen_name",
            "citizen_email",
            "citizen_phone",
            "is_anonymous",
            "suspicious_score",
            "suspicious_reasons",
            "public_resolution_note",
            "internal_note",
            "attachments",
            "comments",
            "status_events",
            "audit_logs",
            "permissions",
            "public_title_approved_by",
        ]

    def get_audit_logs(self, issue):
        logs = AuditLog.objects.filter(object_type="Issue", object_id=str(issue.pk))[:20]
        return AuditLogSerializer(logs, many=True).data


class StaffUserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    municipality = serializers.PrimaryKeyRelatedField(
        queryset=Municipality.objects.filter(is_active=True)
    )
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    role = serializers.ChoiceField(choices=StaffRole.choices)

    def validate_username(self, username):
        if get_user_model().objects.filter(username=username).exists():
            raise serializers.ValidationError("Веќе постои корисник со ова корисничко име.")
        return username

    def validate(self, attrs):
        department = attrs.get("department")
        municipality = attrs.get("municipality")
        if department and department.municipality_id != municipality.id:
            raise serializers.ValidationError(
                {"department": "Одделението не припаѓа на избраната општина."}
            )
        return attrs

    def create(self, validated_data):
        user = get_user_model().objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )
        StaffProfile.objects.create(
            user=user,
            municipality=validated_data["municipality"],
            department=validated_data.get("department"),
            role=validated_data["role"],
            must_change_password=True,
        )
        return user


class StaffChoicesSerializer(ChoiceSerializerMixin, serializers.Serializer):
    status_choices = serializers.SerializerMethodField()
    priority_choices = serializers.SerializerMethodField()
    role_choices = serializers.SerializerMethodField()

    def get_status_choices(self, _):
        return self.choices_payload(IssueStatus.choices)

    def get_priority_choices(self, _):
        return self.choices_payload(IssuePriority.choices)

    def get_role_choices(self, _):
        return self.choices_payload(StaffRole.choices)
