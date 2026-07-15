from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffRole
from apps.issues.models import Issue, IssueCategory, IssueStatus, SlaPolicy
from apps.municipalities.models import (
    Department,
    Municipality,
    MunicipalityPublicNotice,
    NoticePublicationState,
    Settlement,
)


@pytest.fixture
def municipal_data():
    municipality = Municipality.objects.create(name="Општина Тест", slug="test")
    settlement = Settlement.objects.create(municipality=municipality, name="Центар")
    department = Department.objects.create(municipality=municipality, name="Комунално")
    category = IssueCategory.objects.create(
        municipality=municipality,
        name="Осветлување",
        default_department=department,
    )
    return municipality, settlement, category, department


def make_issue(municipality, settlement, category, **kwargs):
    values = {
        "municipality": municipality,
        "settlement": settlement,
        "category": category,
        "title": "Проблем со осветлување",
        "description": "Опис на проблемот",
        "location_text": "Главна улица",
    }
    values.update(kwargs)
    return Issue.objects.create(**values)


@pytest.mark.django_db
def test_branding_validation_and_published_notice_visibility(client, municipal_data):
    municipality, *_ = municipal_data
    municipality.public_accent_color = "green"
    with pytest.raises(ValidationError):
        municipality.full_clean()
    municipality.public_accent_color = "#126E52"
    municipality.full_clean()
    municipality.save()

    user = get_user_model().objects.create_user(username="author")
    MunicipalityPublicNotice.objects.create(
        municipality=municipality,
        title="Нацрт",
        summary="Не е јавно",
        body="Не е јавно тело",
        publication_state=NoticePublicationState.DRAFT,
        author=user,
    )
    published = MunicipalityPublicNotice.objects.create(
        municipality=municipality,
        title="Јавно известување",
        summary="Јавно резиме",
        body="Јавно тело",
        publication_state=NoticePublicationState.PUBLISHED,
        published_at=timezone.now() - timedelta(hours=1),
        author=user,
    )
    MunicipalityPublicNotice.objects.create(
        municipality=municipality,
        title="Закажано",
        summary="Идно",
        body="Идно тело",
        publication_state=NoticePublicationState.PUBLISHED,
        published_at=timezone.now() + timedelta(days=1),
        author=user,
    )

    payload = client.get(f"/api/municipalities/{municipality.slug}/").json()["data"]
    assert payload["public_accent_color"] == "#126E52"
    assert payload["official_coat_of_arms_url"] is None
    assert payload["latest_public_notice"]["id"] == published.id
    assert "Не е јавно" not in str(payload)
    assert "Закажано" not in str(payload)


@pytest.mark.django_db
def test_tracking_code_normalizes_spaces_and_hyphens(client, municipal_data):
    issue = make_issue(*municipal_data[:3])
    decorated = (
        f" {issue.tracking_code[:3]}-{issue.tracking_code[3:6]} {issue.tracking_code[6:].lower()} "
    )
    response = client.get(
        f"/api/municipalities/{issue.municipality.slug}/track/",
        {"code": decorated},
    )
    assert response.status_code == 200
    assert response.json()["data"]["tracking_code"] == issue.tracking_code


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_receipt_opt_in_and_email_failure_are_non_fatal(client, municipal_data):
    municipality, settlement, category, _ = municipal_data
    payload = {
        "settlement": settlement.id,
        "category": category.id,
        "title": "Проблем",
        "description": "Опис",
        "location_text": "Центар",
        "citizen_email": "citizen@example.com",
        "send_receipt": "on",
        "consent": "on",
        "website": "",
    }
    response = client.post(f"/api/municipalities/{municipality.slug}/issues/", payload)
    assert response.status_code == 201
    assert response.json()["data"]["receipt_delivery"] == "sent"
    assert response.json()["data"]["tracking_code"] in mail.outbox[0].body

    with patch("apps.api.views.send_mail", side_effect=RuntimeError("mail unavailable")):
        failed = client.post(
            f"/api/municipalities/{municipality.slug}/issues/",
            {**payload, "title": "Втор проблем", "location_text": "Друга локација"},
            REMOTE_ADDR="198.51.100.22",
        )
    assert failed.status_code == 201
    assert failed.json()["data"]["receipt_delivery"] == "failed"
    assert Issue.objects.filter(title="Втор проблем").exists()


@pytest.mark.django_db
def test_statistics_are_aggregate_suppressed_filtered_and_privacy_safe(client, municipal_data):
    municipality, settlement, category, _ = municipal_data
    now = timezone.now()
    SlaPolicy.objects.create(municipality=municipality, resolution_hours=72)
    for index in range(6):
        issue = make_issue(
            municipality,
            settlement,
            category,
            title=f"Приватен наслов {index}",
            public_title=f"Одобрен јавен наслов {index}",
            public_title_approved_at=now,
            location_text=f"Приватна локација {index}",
            status=IssueStatus.RESOLVED,
        )
        submitted = now - timedelta(hours=48 + index)
        Issue.objects.filter(pk=issue.pk).update(
            submitted_at=submitted,
            triaged_at=submitted + timedelta(hours=4),
            resolved_at=submitted + timedelta(hours=60),
        )

    tiny_settlement = Settlement.objects.create(municipality=municipality, name="Мала група")
    make_issue(
        municipality,
        tiny_settlement,
        category,
        title="Приватен мал наслов",
        public_title="Не прикажувај група",
        public_title_approved_at=now,
    )

    response = client.get(
        f"/api/municipalities/{municipality.slug}/statistics/",
        {"period": "90", "category": category.id},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["recent_reports"]) == 7
    assert data["recent_reports"][0]["title"] == "Не прикажувај група"
    assert set(data["recent_reports"][0]) == {
        "title",
        "submitted_at",
        "status",
        "status_label",
    }
    assert data["performance"] == {
        "median_first_response_hours": 4.0,
        "median_resolution_hours": 60.0,
        "resolved_within_sla_percent": 100.0,
    }
    assert data["by_settlement"] == [{"label": "Центар", "total": 6, "suppressed": False}]
    assert data["suppression"]["suppressed_settlement_groups"] == 1
    assert "Приватна локација" not in str(data)
    assert "tracking_code" not in str(data)

    csv_response = client.get(
        f"/api/municipalities/{municipality.slug}/statistics.csv/",
        {"period": "90", "category": category.id},
    )
    body = csv_response.content.decode("utf-8")
    assert csv_response.status_code == 200
    assert "Приватен наслов" not in body
    assert "Приватна локација" not in body
    assert "<5" in body


@pytest.mark.django_db
def test_statistics_recent_reports_are_capped_at_twenty(client, municipal_data):
    municipality, settlement, category, _ = municipal_data
    for index in range(23):
        make_issue(
            municipality,
            settlement,
            category,
            title=f"Јавен наслов {index:02d}",
            public_title=f"Јавен наслов {index:02d}",
            public_title_approved_at=timezone.now(),
            location_text=f"Приватна локација {index:02d}",
        )

    response = client.get(
        f"/api/municipalities/{municipality.slug}/statistics/",
        {"period": "all"},
    )
    assert response.status_code == 200
    rows = response.json()["data"]["recent_reports"]
    assert len(rows) == 20
    assert rows[0]["title"] == "Јавен наслов 22"
    assert rows[-1]["title"] == "Јавен наслов 03"
    assert "Приватна локација" not in str(rows)


@pytest.mark.django_db
def test_staff_search_sort_pagination_and_exact_sla_metrics(client, municipal_data):
    municipality, settlement, category, _ = municipal_data
    user = get_user_model().objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(
        user=user,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    SlaPolicy.objects.create(
        municipality=municipality,
        category=category,
        triage_hours=1,
        resolution_hours=10,
    )
    for index in range(31):
        issue = make_issue(
            municipality,
            settlement,
            category,
            title=f"Улично светло {index:02d}",
            location_text=f"Улица {index:02d}",
        )
        if index < 28:
            Issue.objects.filter(pk=issue.pk).update(
                submitted_at=timezone.now() - timedelta(hours=3)
            )
    assert client.login(username="coordinator", password="testpass")

    response = client.get(
        "/api/staff/issues/",
        {"search": "Улица 30", "sort": "title", "page_size": 25},
    )
    data = response.json()["data"]
    assert response.status_code == 200
    assert set(data) == {"metrics", "items", "pagination"}
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Улично светло 30"
    assert data["metrics"]["overdue"] == 28
    assert data["metrics"]["unassigned"] == 31

    paginated = client.get("/api/staff/issues/", {"page": 2, "page_size": 25}).json()["data"]
    assert len(paginated["items"]) == 6
    assert paginated["pagination"]["total_items"] == 31
    assert paginated["pagination"]["total_pages"] == 2


@pytest.mark.django_db
def test_bulk_assignment_is_atomic_and_municipality_isolated(client, municipal_data):
    municipality, settlement, category, department = municipal_data
    other = Municipality.objects.create(name="Друга општина", slug="other")
    other_settlement = Settlement.objects.create(municipality=other, name="Друго")
    other_department = Department.objects.create(municipality=other, name="Друго одделение")
    other_category = IssueCategory.objects.create(municipality=other, name="Друго")
    local_issue = make_issue(municipality, settlement, category)
    foreign_issue = make_issue(other, other_settlement, other_category)
    coordinator = get_user_model().objects.create_user(username="coordinator", password="testpass")
    assignee = get_user_model().objects.create_user(username="worker", password="testpass")
    StaffProfile.objects.create(
        user=coordinator,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    StaffProfile.objects.create(
        user=assignee,
        municipality=municipality,
        role=StaffRole.FIELD_WORKER,
    )
    assert client.login(username="coordinator", password="testpass")

    rejected = client.post(
        "/api/staff/issues/bulk-assign/",
        {
            "issue_ids": [local_issue.id, foreign_issue.id],
            "department_id": department.id,
            "assignee_id": assignee.id,
        },
        content_type="application/json",
    )
    assert rejected.status_code == 403
    local_issue.refresh_from_db()
    assert local_issue.assigned_to_id is None

    second_local = make_issue(municipality, settlement, category, title="Втора локална")
    accepted = client.post(
        "/api/staff/issues/bulk-assign/",
        {
            "issue_ids": [local_issue.id, second_local.id],
            "department_id": department.id,
            "assignee_id": assignee.id,
        },
        content_type="application/json",
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["updated"] == 2
    assert set(
        Issue.objects.filter(pk__in=[local_issue.id, second_local.id]).values_list(
            "assigned_to_id", flat=True
        )
    ) == {assignee.id}
    assert other_department.id != department.id
