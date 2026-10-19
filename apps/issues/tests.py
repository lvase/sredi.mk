from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffRole
from apps.issues.admin import anonymize_citizen_contact, export_issues_csv
from apps.issues.models import (
    AttachmentDeletionState,
    AuditLog,
    DataRetentionPolicy,
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueComment,
    IssueStatus,
    ResponseTarget,
    SubmissionRateLimit,
)
from apps.issues.retention import apply_retention, preview_retention
from apps.issues.services import consume_submission_rate_limit, get_client_ip
from apps.municipalities.configuration import (
    apply_configuration,
    load_configuration,
    validate_municipality_configuration,
    verify_stored_configuration,
)
from apps.municipalities.models import ConfigurationStatus, Department, Municipality, Settlement


@pytest.mark.django_db
def test_citizen_can_submit_anonymous_issue(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")

    response = client.post(
        reverse("submit_issue", args=[municipality.slug]),
        {
            "settlement": settlement.id,
            "category": category.id,
            "title": "Проблем со осветлување",
            "description": "Не работи светилка во центарот на селото.",
            "location_text": "Центар",
            "citizen_name": "",
            "citizen_email": "",
            "citizen_phone": "",
            "consent": "on",
            "website": "",
        },
    )

    assert response.status_code == 200
    issue = Issue.objects.get()
    assert issue.status == IssueStatus.PENDING_TRIAGE
    assert issue.is_anonymous is True
    assert issue.tracking_code


@pytest.mark.django_db
def test_public_submission_rate_limit_blocks_fourth_hourly_submission(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    payload = {
        "settlement": settlement.id,
        "category": category.id,
        "title": "Проблем со осветлување",
        "description": "Не работи светилка.",
        "location_text": "Центар",
        "citizen_name": "",
        "citizen_email": "",
        "citizen_phone": "",
        "consent": "on",
        "website": "",
    }

    for index in range(3):
        submission_payload = {
            **payload,
            "title": f"Проблем со осветлување {index}",
            "description": f"Не работи светилка {index}.",
            "location_text": f"Центар {index}",
        }
        response = client.post(reverse("submit_issue", args=[municipality.slug]), submission_payload)
        assert response.status_code == 200
    blocked_response = client.post(reverse("submit_issue", args=[municipality.slug]), payload)

    assert Issue.objects.count() == 3
    assert sorted(Issue.objects.values_list("suspicious_score", flat=True)) == [0, 10, 20]
    assert "Испратени се премногу пријави" in blocked_response.content.decode()


@pytest.mark.django_db
def test_suspicious_assessment_records_explainable_reasons(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    payload = {
        "settlement": settlement.id,
        "category": category.id,
        "title": "Ист проблем",
        "description": "Истиот опис на проблемот.",
        "location_text": "Иста локација",
        "citizen_name": "",
        "citizen_email": "",
        "citizen_phone": "",
        "consent": "on",
        "website": "",
    }

    for _ in range(3):
        response = client.post(reverse("submit_issue", args=[municipality.slug]), payload)
        assert response.status_code == 200

    latest_issue = Issue.objects.order_by("-pk").first()
    reason_codes = {reason["code"] for reason in latest_issue.suspicious_reasons}

    assert latest_issue.suspicious_score == 60
    assert reason_codes == {
        "rapid_submissions",
        "repeated_description",
        "repeated_location",
    }

    staff = get_user_model().objects.create_user(username="risk-reviewer", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)
    api_detail = client.get(f"/api/staff/issues/{latest_issue.pk}/")
    html_detail = client.get(reverse("staff_issue_detail", args=[latest_issue.pk]))

    assert api_detail.status_code == 200
    assert {reason["code"] for reason in api_detail.json()["data"]["suspicious_reasons"]} == reason_codes
    assert "Причини за означување" in html_detail.content.decode()
    assert "Истиот опис веќе е испратен" in html_detail.content.decode()


@pytest.mark.django_db(transaction=True)
def test_rate_limit_consumption_is_atomic_under_concurrent_requests():
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    municipality_id = municipality.pk

    def consume_slot(_):
        close_old_connections()
        try:
            thread_municipality = Municipality.objects.get(pk=municipality_id)
            return consume_submission_rate_limit(thread_municipality, "concurrent-ip-hash")[0]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(consume_slot, range(6)))

    assert results.count(True) == 3
    assert results.count(False) == 3


def test_client_ip_ignores_forwarded_header_from_untrusted_source():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="198.51.100.20",
        HTTP_X_FORWARDED_FOR="203.0.113.10",
    )

    assert get_client_ip(request) == "198.51.100.20"


@override_settings(TRUSTED_PROXY_IPS=["10.0.0.0/8"])
def test_client_ip_uses_rightmost_untrusted_address_behind_trusted_proxies():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="10.0.0.2",
        HTTP_X_FORWARDED_FOR="192.0.2.99, 203.0.113.10, 10.0.0.3",
    )

    assert get_client_ip(request) == "203.0.113.10"


@pytest.mark.django_db
def test_public_submission_rejects_invalid_upload_type(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce", photo_uploads_enabled=True)
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    upload = SimpleUploadedFile("note.txt", b"not an image", content_type="text/plain")

    response = client.post(
        reverse("submit_issue", args=[municipality.slug]),
        {
            "settlement": settlement.id,
            "category": category.id,
            "title": "Проблем со осветлување",
            "description": "Не работи светилка.",
            "location_text": "Центар",
            "citizen_name": "",
            "citizen_email": "",
            "citizen_phone": "",
            "consent": "on",
            "website": "",
            "photos": upload,
        },
    )

    assert response.status_code == 200
    assert Issue.objects.count() == 0
    assert "Дозволени се само JPG, PNG или WEBP фотографии." in response.content.decode()


@pytest.mark.django_db
def test_public_submission_rejects_corrupt_image_file(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce", photo_uploads_enabled=True)
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    upload = SimpleUploadedFile("photo.jpg", b"not a real image", content_type="image/jpeg")

    response = client.post(
        reverse("submit_issue", args=[municipality.slug]),
        {
            "settlement": settlement.id,
            "category": category.id,
            "title": "Проблем со осветлување",
            "description": "Не работи светилка.",
            "location_text": "Центар",
            "citizen_name": "",
            "citizen_email": "",
            "citizen_phone": "",
            "consent": "on",
            "website": "",
            "photos": upload,
        },
    )

    assert response.status_code == 200
    assert Issue.objects.count() == 0
    assert "не може да се прочита како валидна слика" in response.content.decode()


@pytest.mark.django_db
def test_public_dashboard_aggregates_without_exposing_issue_details(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Private title should not be listed",
        description="Private description",
        location_text="Private place",
    )

    response = client.get(reverse("public_dashboard", args=[municipality.slug]))

    assert response.status_code == 200
    assert "Private title should not be listed" not in response.content.decode()
    assert "Private description" not in response.content.decode()
    assert "Private place" not in response.content.decode()
    assert "Чека проверка" in response.content.decode()
    assert "Конче" in response.content.decode()


@pytest.mark.django_db
def test_home_page_lists_active_municipalities(client):
    Municipality.objects.create(name="Општина Конче", slug="konce")
    Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    Municipality.objects.create(name="Неактивна општина", slug="inactive", is_active=False)

    response = client.get(reverse("home"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Почетна" not in body
    assert "Општина Конче" in body
    assert "Општина Радовиш" in body
    assert "Неактивна општина" not in body


@pytest.mark.django_db
def test_municipality_landing_pages_show_home_navigation_button(client):
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")

    konce_response = client.get(reverse("sredi_home", args=[konce.slug]))
    radovis_response = client.get(reverse("sredi_home", args=[radovis.slug]))

    assert "Почетна" in konce_response.content.decode()
    assert "Почетна" in radovis_response.content.decode()


@pytest.mark.django_db
def test_legal_pages_render(client):
    privacy_response = client.get(reverse("privacy_policy"))
    terms_response = client.get(reverse("terms_of_use"))
    privacy_api_response = client.get("/api/legal/privacy/")
    terms_api_response = client.get("/api/legal/terms/")

    assert privacy_response.status_code == 200
    assert "Политика за приватност" in privacy_response.content.decode()
    assert "Нацрт за MVP" in privacy_response.content.decode()
    assert terms_response.status_code == 200
    assert "Услови за користење" in terms_response.content.decode()
    assert "Нацрт за MVP" in terms_response.content.decode()
    assert "Намерно лажни, измамнички или манипулирани пријави" in terms_response.content.decode()
    assert privacy_api_response.status_code == 200
    assert privacy_api_response.json()["data"] == {
        "title": "Политика за приватност",
        "updated_at": "19.10.2026",
        "notice": "Овој текст е работна верзија и треба да биде проверен од правник и од секоја општина пред јавно пуштање во употреба.",
        "platform_operator_name": settings.PLATFORM_OPERATOR_NAME,
        "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
    }
    assert terms_api_response.status_code == 200
    assert terms_api_response.json()["data"]["updated_at"] == "19.10.2026"
    assert terms_api_response.json()["data"]["platform_operator_name"] == settings.PLATFORM_OPERATOR_NAME


@pytest.mark.django_db
def test_municipality_form_only_shows_selected_municipality_data(client):
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    Settlement.objects.create(municipality=konce, name="Конче")
    Settlement.objects.create(municipality=radovis, name="Радовиш")
    IssueCategory.objects.create(municipality=konce, name="Комунално Конче")
    IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")

    response = client.get(reverse("submit_issue", args=[konce.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Конче" in body
    assert "Комунално Конче" in body
    assert "Радовиш" not in body
    assert "Комунално Радовиш" not in body
    assert reverse("privacy_policy") in body
    assert reverse("terms_of_use") in body


@pytest.mark.django_db
def test_footer_links_to_legal_pages(client):
    response = client.get(reverse("home"))
    body = response.content.decode()

    assert reverse("privacy_policy") in body
    assert reverse("terms_of_use") in body


@pytest.mark.django_db
def test_public_dashboard_is_scoped_to_selected_municipality(client):
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    konce_settlement = Settlement.objects.create(municipality=konce, name="Конче")
    radovis_settlement = Settlement.objects.create(municipality=radovis, name="Радовиш")
    konce_category = IssueCategory.objects.create(municipality=konce, name="Комунално Конче")
    radovis_category = IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")
    Issue.objects.create(
        municipality=konce,
        settlement=konce_settlement,
        category=konce_category,
        title="Конче проблем",
        description="Опис",
        location_text="Локација",
    )
    Issue.objects.create(
        municipality=radovis,
        settlement=radovis_settlement,
        category=radovis_category,
        title="Радовиш проблем",
        description="Опис",
        location_text="Локација",
    )

    response = client.get(reverse("public_dashboard", args=[radovis.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Радовиш" in body
    assert "Комунално Радовиш" in body
    assert "Чека проверка" in body
    assert "Конче проблем" not in body
    assert "Комунално Конче" not in body


@pytest.mark.django_db
def test_tracking_is_scoped_to_selected_municipality(client):
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    konce_settlement = Settlement.objects.create(municipality=konce, name="Конче")
    Settlement.objects.create(municipality=radovis, name="Радовиш")
    category = IssueCategory.objects.create(municipality=konce, name="Комунално")
    issue = Issue.objects.create(
        municipality=konce,
        settlement=konce_settlement,
        category=category,
        title="Пријава за Конче",
        description="Опис",
        location_text="Локација",
    )

    response = client.get(
        reverse("track_issue", args=[radovis.slug]),
        {"code": issue.tracking_code},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Пријава за Конче" not in body
    assert "Не е пронајдена пријава со тој код." in body


@pytest.mark.django_db
def test_tracking_shows_public_comments_only(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Пријава за Конче",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="staff", password="testpass")
    IssueComment.objects.create(
        issue=issue,
        author=staff,
        body="Јавна информација за граѓанинот.",
        is_internal=False,
    )
    IssueComment.objects.create(
        issue=issue,
        author=staff,
        body="Интерна белешка за службеници.",
        is_internal=True,
    )
    issue.public_resolution_note = "Екипата ќе пристигне утре."
    issue.internal_note = "Внатрешна проценка на трошоци."
    issue.save()
    issue.mark_status(
        IssueStatus.ACCEPTED,
        user=staff,
        note="Внатрешно образложение за статусот.",
    )

    response = client.get(
        reverse("track_issue", args=[municipality.slug]),
        {"code": issue.tracking_code},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Јавна информација за граѓанинот." in body
    assert "Пријавата е примена" in body
    assert "Статусот е променет во „Прифатена“." in body
    assert "Екипата ќе пристигне утре." in body
    assert "Последно јавно ажурирање:" in body
    assert "Интерна белешка за службеници." not in body
    assert "Внатрешна проценка на трошоци." not in body
    assert "Внатрешно образложение за статусот." not in body


@pytest.mark.django_db
def test_api_tracking_returns_privacy_safe_public_timeline(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Проблем со улица",
        description="Опис",
        location_text="Центар",
        internal_note="Не смее да биде јавно.",
    )
    staff = user_model.objects.create_user(username="timeline-staff", password="testpass")
    IssueComment.objects.create(
        issue=issue,
        author=staff,
        body="Јавен коментар од општината.",
        is_internal=False,
    )
    IssueComment.objects.create(
        issue=issue,
        author=staff,
        body="Интерен коментар.",
        is_internal=True,
    )
    issue.mark_status(
        IssueStatus.IN_PROGRESS,
        user=staff,
        note="Интерна статусна белешка.",
    )

    response = client.get(
        f"/api/municipalities/{municipality.slug}/track/",
        {"code": issue.tracking_code},
    )

    assert response.status_code == 200
    updates = response.json()["data"]["public_updates"]
    assert [update["kind"] for update in updates] == ["submitted", "comment", "status"]
    serialized_updates = str(updates)
    assert "Јавен коментар од општината." in serialized_updates
    assert "Статусот е променет во „Во тек“." in serialized_updates
    assert "Интерен коментар." not in serialized_updates
    assert "Интерна статусна белешка." not in serialized_updates
    assert "timeline-staff" not in serialized_updates


@pytest.mark.django_db
def test_admin_privacy_actions_export_and_anonymize_issue_contact():
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Пријава",
        description="Опис",
        location_text="Локација",
        citizen_name="Test Citizen",
        citizen_email="citizen@example.com",
        citizen_phone="070000000",
    )
    superuser = user_model.objects.create_superuser(
        username="owner",
        email="owner@example.com",
        password="testpass",
    )
    request = RequestFactory().post("/admin/")
    request.user = superuser

    response = export_issues_csv(None, request, Issue.objects.filter(pk=issue.pk))
    anonymize_citizen_contact(None, request, Issue.objects.filter(pk=issue.pk))

    issue.refresh_from_db()
    assert response.status_code == 200
    assert issue.citizen_name == ""
    assert issue.citizen_email == ""
    assert issue.citizen_phone == ""
    assert issue.is_anonymous is True
    assert AuditLog.objects.filter(action="admin_issues_exported", actor=superuser).exists()
    assert AuditLog.objects.filter(action="admin_issue_contacts_anonymized", actor=superuser).exists()


@pytest.mark.django_db
def test_staff_can_update_issue_assignment_and_notes(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    department = Department.objects.create(municipality=municipality, name="Комунални работи")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Има оштетување на улицата.",
        location_text="Главна улица",
    )
    staff = user_model.objects.create_user(username="staff", password="testpass")
    assignee = user_model.objects.create_user(username="worker", password="testpass")
    StaffProfile.objects.create(
        user=staff,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    StaffProfile.objects.create(user=assignee, municipality=municipality)
    client.force_login(staff)

    response = client.post(
        reverse("staff_update_issue", args=[issue.pk]),
        {
            "priority": "high",
            "assigned_department": department.pk,
            "assigned_to": assignee.pk,
            "internal_note": "Потребна е проверка на терен.",
            "public_resolution_note": "Екипа ќе ја провери локацијата.",
        },
    )

    assert response.status_code == 302
    issue.refresh_from_db()
    assert issue.priority == "high"
    assert issue.assigned_department == department
    assert issue.assigned_to == assignee
    assert issue.internal_note == "Потребна е проверка на терен."
    assert issue.public_resolution_note == "Екипа ќе ја провери локацијата."
    public_update = issue.comments.get(is_internal=False)
    assert public_update.body == "Екипа ќе ја провери локацијата."
    assert public_update.author == staff


@pytest.mark.django_db
def test_staff_update_rejects_assignment_outside_issue_municipality(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    other_municipality = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    other_department = Department.objects.create(
        municipality=other_municipality,
        name="Друго одделение",
    )
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Има оштетување на улицата.",
        location_text="Главна улица",
    )
    staff = user_model.objects.create_user(username="staff", password="testpass")
    other_staff = user_model.objects.create_user(username="other", password="testpass")
    StaffProfile.objects.create(
        user=staff,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    StaffProfile.objects.create(user=other_staff, municipality=other_municipality)
    client.force_login(staff)

    response = client.post(
        reverse("staff_update_issue", args=[issue.pk]),
        {
            "priority": "urgent",
            "assigned_department": other_department.pk,
            "assigned_to": other_staff.pk,
            "internal_note": "Не треба да се зачува.",
            "public_resolution_note": "",
        },
    )

    assert response.status_code == 302
    issue.refresh_from_db()
    assert issue.priority == "normal"
    assert issue.assigned_department is None
    assert issue.assigned_to is None
    assert issue.internal_note == ""


@pytest.mark.django_db
def test_staff_can_add_internal_comment(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Има оштетување на улицата.",
        location_text="Главна улица",
    )
    staff = user_model.objects.create_user(username="staff", password="testpass")
    issue.assigned_to = staff
    issue.save()
    StaffProfile.objects.create(
        user=staff,
        municipality=municipality,
        role=StaffRole.FIELD_WORKER,
    )
    client.force_login(staff)

    response = client.post(
        reverse("staff_add_comment", args=[issue.pk]),
        {"body": "Пратено до теренска екипа.", "is_internal": "on"},
    )

    assert response.status_code == 302
    comment = issue.comments.get()
    assert comment.author == staff
    assert comment.body == "Пратено до теренска екипа."
    assert comment.is_internal is True


@pytest.mark.django_db
def test_staff_dashboard_only_shows_own_municipality_issues(client):
    user_model = get_user_model()
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    konce_settlement = Settlement.objects.create(municipality=konce, name="Конче")
    radovis_settlement = Settlement.objects.create(municipality=radovis, name="Радовиш")
    konce_category = IssueCategory.objects.create(municipality=konce, name="Комунално Конче")
    radovis_category = IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")
    Issue.objects.create(
        municipality=konce,
        settlement=konce_settlement,
        category=konce_category,
        title="Конче пријава",
        description="Опис",
        location_text="Локација",
    )
    Issue.objects.create(
        municipality=radovis,
        settlement=radovis_settlement,
        category=radovis_category,
        title="Радовиш пријава",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="staff", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=konce)
    client.force_login(staff)

    response = client.get(reverse("staff_dashboard"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Конче пријава" in body
    assert "Радовиш пријава" not in body
    assert "Општина Конче" in body
    assert "Општина Радовиш" not in body


@pytest.mark.django_db
def test_staff_dashboard_filters_and_quick_status_action(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    roads = Department.objects.create(municipality=municipality, name="Патишта")
    lights = Department.objects.create(municipality=municipality, name="Јавно осветлување")
    roads_category = IssueCategory.objects.create(municipality=municipality, name="Улици")
    lights_category = IssueCategory.objects.create(municipality=municipality, name="Осветлување")
    staff = user_model.objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(
        user=staff,
        municipality=municipality,
        role=StaffRole.COORDINATOR,
    )
    target = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=roads_category,
        title="Патишта пријава",
        description="Опис",
        location_text="Локација",
        assigned_department=roads,
        assigned_to=staff,
    )
    Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=lights_category,
        title="Осветлување пријава",
        description="Опис",
        location_text="Локација",
        assigned_department=lights,
    )
    client.force_login(staff)

    response = client.get(
        reverse("staff_dashboard"),
        {"category": roads_category.pk, "department": roads.pk, "mine": "1"},
    )
    body = response.content.decode()
    status_response = client.post(
        reverse("staff_change_status", args=[target.pk]),
        {"status": IssueStatus.ACCEPTED},
    )

    assert response.status_code == 200
    assert "Патишта пријава" in body
    assert "Осветлување пријава" not in body
    assert "Прифатена" in body
    assert status_response.status_code == 302
    target.refresh_from_db()
    assert target.status == IssueStatus.ACCEPTED


@pytest.mark.django_db
def test_status_change_requires_note_for_sensitive_status(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)

    response = client.post(
        reverse("staff_change_status", args=[issue.pk]),
        {"status": IssueStatus.RESOLVED, "note": ""},
        follow=True,
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.status == IssueStatus.PENDING_TRIAGE
    assert "За овој статус мора да внесете белешка." in response.content.decode()


@pytest.mark.django_db
def test_status_change_applies_default_department_and_audit_log(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    department = Department.objects.create(municipality=municipality, name="Комунални работи")
    category = IssueCategory.objects.create(
        municipality=municipality,
        name="Комунално",
        default_department=department,
    )
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)

    response = client.post(
        reverse("staff_change_status", args=[issue.pk]),
        {"status": IssueStatus.ACCEPTED, "note": "Прифатено за обработка."},
    )

    assert response.status_code == 302
    issue.refresh_from_db()
    assert issue.status == IssueStatus.ACCEPTED
    assert issue.assigned_department == department
    audit = AuditLog.objects.get(action="issue_status_changed")
    assert audit.actor == staff
    assert audit.metadata["default_department_applied"] is True


@pytest.mark.django_db
def test_staff_update_and_comment_create_audit_logs(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)

    client.post(
        reverse("staff_update_issue", args=[issue.pk]),
        {
            "priority": "high",
            "assigned_department": "",
            "assigned_to": "",
            "internal_note": "Проверка.",
            "public_resolution_note": "",
        },
    )
    client.post(
        reverse("staff_add_comment", args=[issue.pk]),
        {"body": "Коментар.", "is_internal": "on"},
    )

    assert AuditLog.objects.filter(action="issue_updated", actor=staff).exists()
    assert AuditLog.objects.filter(action="issue_comment_added", actor=staff).exists()


@pytest.mark.django_db
def test_staff_dashboard_uses_response_target_for_overdue_filter(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    ResponseTarget.objects.create(municipality=municipality, review_hours=1)
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Задоцнета пријава",
        description="Опис",
        location_text="Локација",
    )
    Issue.objects.filter(pk=issue.pk).update(submitted_at=timezone.now() - timedelta(hours=2))
    staff = user_model.objects.create_user(username="coordinator", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)

    response = client.get(reverse("staff_dashboard"), {"overdue": "1"})

    assert response.status_code == 200
    assert "Задоцнета пријава" in response.content.decode()
    assert "Задоцнета" in response.content.decode()


@pytest.mark.django_db
def test_superuser_can_create_staff_user(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    department = Department.objects.create(municipality=municipality, name="Патишта")
    superuser = user_model.objects.create_superuser(
        username="owner",
        email="owner@example.com",
        password="testpass",
    )
    client.force_login(superuser)

    response = client.post(
        reverse("staff_create_user"),
        {
            "username": "new-staff",
            "email": "staff@example.com",
            "password": "temporary-pass-123",
            "municipality": municipality.pk,
            "department": department.pk,
            "role": StaffRole.FIELD_WORKER,
        },
    )

    assert response.status_code == 302
    user = user_model.objects.get(username="new-staff")
    assert user.staffprofile.municipality == municipality
    assert user.staffprofile.department == department
    assert user.staffprofile.role == StaffRole.FIELD_WORKER
    assert user.staffprofile.must_change_password is True
    assert AuditLog.objects.filter(action="staff_user_created", actor=superuser).exists()


@pytest.mark.django_db
def test_staff_cannot_access_another_municipality_issue(client):
    user_model = get_user_model()
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    Settlement.objects.create(municipality=konce, name="Конче")
    radovis_settlement = Settlement.objects.create(municipality=radovis, name="Радовиш")
    radovis_category = IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")
    radovis_issue = Issue.objects.create(
        municipality=radovis,
        settlement=radovis_settlement,
        category=radovis_category,
        title="Радовиш пријава",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="konce-staff", password="testpass")
    StaffProfile.objects.create(
        user=staff,
        municipality=konce,
        role=StaffRole.COORDINATOR,
    )
    client.force_login(staff)

    response = client.get(reverse("staff_issue_detail", args=[radovis_issue.pk]))
    status_response = client.post(
        reverse("staff_change_status", args=[radovis_issue.pk]),
        {"status": IssueStatus.IN_PROGRESS, "note": ""},
    )

    assert response.status_code == 404
    assert status_response.status_code == 404
    radovis_issue.refresh_from_db()
    assert radovis_issue.status == IssueStatus.PENDING_TRIAGE


@pytest.mark.django_db
def test_viewer_role_is_read_only(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
    )
    viewer = user_model.objects.create_user(username="viewer", password="testpass")
    StaffProfile.objects.create(
        user=viewer,
        municipality=municipality,
        role=StaffRole.VIEWER,
    )
    client.force_login(viewer)

    detail_response = client.get(reverse("staff_issue_detail", args=[issue.pk]))
    update_response = client.post(
        reverse("staff_update_issue", args=[issue.pk]),
        {
            "priority": "urgent",
            "assigned_department": "",
            "assigned_to": "",
            "internal_note": "Не треба да се зачува.",
            "public_resolution_note": "",
        },
    )
    status_response = client.post(
        reverse("staff_change_status", args=[issue.pk]),
        {"status": IssueStatus.IN_PROGRESS, "note": ""},
    )
    comment_response = client.post(
        reverse("staff_add_comment", args=[issue.pk]),
        {"body": "Не треба да се зачува.", "is_internal": "on"},
    )

    assert detail_response.status_code == 200
    assert update_response.status_code == 403
    assert status_response.status_code == 403
    assert comment_response.status_code == 403
    issue.refresh_from_db()
    assert issue.priority == "normal"
    assert issue.status == IssueStatus.PENDING_TRIAGE
    assert issue.comments.count() == 0


@pytest.mark.django_db
def test_field_worker_can_only_update_allowed_statuses_and_comments(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    worker = user_model.objects.create_user(username="worker", password="testpass")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
        assigned_to=worker,
    )
    StaffProfile.objects.create(
        user=worker,
        municipality=municipality,
        role=StaffRole.FIELD_WORKER,
    )
    client.force_login(worker)

    update_response = client.post(
        reverse("staff_update_issue", args=[issue.pk]),
        {
            "priority": "urgent",
            "assigned_department": "",
            "assigned_to": worker.pk,
            "internal_note": "Не треба да се зачува.",
            "public_resolution_note": "",
        },
    )
    rejected_status_response = client.post(
        reverse("staff_change_status", args=[issue.pk]),
        {"status": IssueStatus.ACCEPTED, "note": ""},
    )
    allowed_status_response = client.post(
        reverse("staff_change_status", args=[issue.pk]),
        {"status": IssueStatus.IN_PROGRESS, "note": "Започната работа."},
    )
    comment_response = client.post(
        reverse("staff_add_comment", args=[issue.pk]),
        {"body": "Работата е започната.", "is_internal": "on"},
    )

    assert update_response.status_code == 403
    assert rejected_status_response.status_code == 403
    assert allowed_status_response.status_code == 302
    assert comment_response.status_code == 302
    issue.refresh_from_db()
    assert issue.priority == "normal"
    assert issue.status == IssueStatus.IN_PROGRESS
    assert issue.comments.get().body == "Работата е започната."


@pytest.mark.django_db
def test_department_manager_reads_all_but_only_updates_department_issues(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    roads = Department.objects.create(municipality=municipality, name="Патишта")
    lights = Department.objects.create(municipality=municipality, name="Јавно осветлување")
    roads_issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Патишта пријава",
        description="Опис",
        location_text="Локација",
        assigned_department=roads,
    )
    lights_issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Осветлување пријава",
        description="Опис",
        location_text="Локација",
        assigned_department=lights,
    )
    manager = user_model.objects.create_user(username="manager", password="testpass")
    StaffProfile.objects.create(
        user=manager,
        municipality=municipality,
        department=roads,
        role=StaffRole.DEPARTMENT_MANAGER,
    )
    client.force_login(manager)

    dashboard_response = client.get(reverse("staff_dashboard"))
    own_status_response = client.post(
        reverse("staff_change_status", args=[roads_issue.pk]),
        {"status": IssueStatus.IN_PROGRESS, "note": ""},
    )
    other_detail_response = client.get(reverse("staff_issue_detail", args=[lights_issue.pk]))
    other_status_response = client.post(
        reverse("staff_change_status", args=[lights_issue.pk]),
        {"status": IssueStatus.IN_PROGRESS, "note": ""},
    )

    body = dashboard_response.content.decode()
    assert dashboard_response.status_code == 200
    assert "Патишта пријава" in body
    assert "Осветлување пријава" in body
    assert own_status_response.status_code == 302
    assert other_detail_response.status_code == 200
    assert other_status_response.status_code == 403
    roads_issue.refresh_from_db()
    assert roads_issue.status == IssueStatus.IN_PROGRESS


@pytest.mark.django_db
def test_superuser_can_access_all_staff_issues(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    settlement = Settlement.objects.create(municipality=municipality, name="Радовиш")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Радовиш пријава",
        description="Опис",
        location_text="Локација",
    )
    superuser = user_model.objects.create_superuser(
        username="owner",
        email="owner@example.com",
        password="testpass",
    )
    client.force_login(superuser)

    response = client.get(reverse("staff_issue_detail", args=[issue.pk]))

    assert response.status_code == 200
    assert "Радовиш пријава" in response.content.decode()


@pytest.mark.django_db
def test_django_admin_rejects_staff_and_unverified_superusers(client):
    user_model = get_user_model()
    staff = user_model.objects.create_user(
        username="municipality-admin",
        password="testpass",
        is_staff=True,
    )
    StaffProfile.objects.create(user=staff, role=StaffRole.MUNICIPALITY_ADMIN)
    superuser = user_model.objects.create_superuser(
        username="owner",
        email="owner@example.com",
        password="testpass",
    )

    client.force_login(staff)
    staff_response = client.get(reverse("admin:index"))
    client.force_login(superuser)
    superuser_response = client.get(reverse("admin:index"))

    assert staff_response.status_code == 302
    assert superuser_response.status_code == 302


@pytest.mark.django_db
def test_api_public_submission_and_tracking(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")

    response = client.post(
        f"/api/municipalities/{municipality.slug}/issues/",
        {
            "settlement": settlement.id,
            "category": category.id,
            "title": "Проблем со осветлување",
            "description": "Не работи светилка.",
            "location_text": "Центар",
            "citizen_name": "",
            "citizen_email": "",
            "citizen_phone": "",
            "consent": "on",
            "website": "",
        },
    )

    assert response.status_code == 201
    tracking_code = response.json()["data"]["tracking_code"]
    track_response = client.get(
        f"/api/municipalities/{municipality.slug}/track/",
        {"code": tracking_code},
    )
    assert track_response.status_code == 200
    assert track_response.json()["data"]["tracking_code"] == tracking_code


@pytest.mark.django_db
def test_api_staff_dashboard_is_scoped_to_staff_municipality(client):
    user_model = get_user_model()
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    konce_settlement = Settlement.objects.create(municipality=konce, name="Конче")
    radovis_settlement = Settlement.objects.create(municipality=radovis, name="Радовиш")
    konce_category = IssueCategory.objects.create(municipality=konce, name="Комунално Конче")
    radovis_category = IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")
    Issue.objects.create(
        municipality=konce,
        settlement=konce_settlement,
        category=konce_category,
        title="Конче пријава",
        description="Опис",
        location_text="Локација",
    )
    radovis_issue = Issue.objects.create(
        municipality=radovis,
        settlement=radovis_settlement,
        category=radovis_category,
        title="Радовиш пријава",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="api-staff", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=konce)
    client.force_login(staff)

    response = client.get("/api/staff/issues/")
    filtered_response = client.get("/api/staff/issues/", {"municipality": radovis.pk})
    choices_response = client.get("/api/staff/choices/")
    detail_response = client.get(f"/api/staff/issues/{radovis_issue.pk}/")
    status_response = client.post(
        f"/api/staff/issues/{radovis_issue.pk}/status/",
        {"status": IssueStatus.IN_PROGRESS, "note": ""},
        content_type="application/json",
    )

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()["data"]["items"]]
    assert "Конче пријава" in titles
    assert "Радовиш пријава" not in titles
    filtered_titles = [row["title"] for row in filtered_response.json()["data"]["items"]]
    assert filtered_titles == []
    assert choices_response.status_code == 200
    municipality_choice = choices_response.json()["data"]["municipalities"][0]
    assert {
        key: municipality_choice[key]
        for key in ["id", "name", "slug", "configuration_status"]
    } == {
        "id": konce.pk,
        "name": konce.name,
        "slug": konce.slug,
        "configuration_status": ConfigurationStatus.UNVERIFIED,
    }
    assert detail_response.status_code == 404
    assert status_response.status_code == 404


@pytest.mark.django_db
def test_api_staff_account_switch_keeps_municipality_data_isolated(client):
    user_model = get_user_model()
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    konce_settlement = Settlement.objects.create(municipality=konce, name="Конче")
    radovis_settlement = Settlement.objects.create(municipality=radovis, name="Радовиш")
    konce_category = IssueCategory.objects.create(municipality=konce, name="Комунално Конче")
    radovis_category = IssueCategory.objects.create(municipality=radovis, name="Комунално Радовиш")
    konce_issue = Issue.objects.create(
        municipality=konce,
        settlement=konce_settlement,
        category=konce_category,
        title="Само Конче",
        description="Опис",
        location_text="Локација",
    )
    radovis_issue = Issue.objects.create(
        municipality=radovis,
        settlement=radovis_settlement,
        category=radovis_category,
        title="Само Радовиш",
        description="Опис",
        location_text="Локација",
    )
    konce_staff = user_model.objects.create_user(username="konce-session", password="testpass")
    radovis_staff = user_model.objects.create_user(username="radovis-session", password="testpass")
    StaffProfile.objects.create(user=konce_staff, municipality=konce, role=StaffRole.COORDINATOR)
    StaffProfile.objects.create(user=radovis_staff, municipality=radovis, role=StaffRole.COORDINATOR)

    assert client.post(
        "/api/auth/login/",
        {"username": "konce-session", "password": "testpass"},
        content_type="application/json",
    ).status_code == 200
    konce_rows = client.get("/api/staff/issues/").json()["data"]["items"]
    konce_choices = client.get("/api/staff/choices/").json()["data"]
    assert [row["title"] for row in konce_rows] == ["Само Конче"]
    assert [item["slug"] for item in konce_choices["municipalities"]] == ["konce"]
    assert client.get(f"/api/staff/issues/{radovis_issue.pk}/").status_code == 404
    assert client.get("/api/staff/issues/", {"municipality": radovis.pk}).json()["data"]["items"] == []
    assert client.post(
        f"/api/staff/issues/{radovis_issue.pk}/comments/",
        {"body": "Не смее", "is_internal": True},
        content_type="application/json",
    ).status_code == 404

    assert client.post("/api/auth/logout/").status_code == 200
    assert client.post(
        "/api/auth/login/",
        {"username": "radovis-session", "password": "testpass"},
        content_type="application/json",
    ).status_code == 200
    radovis_rows = client.get("/api/staff/issues/").json()["data"]["items"]
    radovis_choices = client.get("/api/staff/choices/").json()["data"]
    assert [row["title"] for row in radovis_rows] == ["Само Радовиш"]
    assert [item["slug"] for item in radovis_choices["municipalities"]] == ["radovis"]
    assert client.get(f"/api/staff/issues/{konce_issue.pk}/").status_code == 404


@pytest.mark.django_db
def test_api_rate_limit_returns_429_after_three_valid_submissions(client):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")

    responses = []
    for index in range(4):
        responses.append(
            client.post(
                f"/api/municipalities/{municipality.slug}/issues/",
                {
                    "settlement": settlement.pk,
                    "category": category.pk,
                    "title": f"Пријава {index}",
                    "description": f"Опис {index}",
                    "location_text": f"Локација {index}",
                    "consent": "on",
                    "website": "",
                },
            )
        )

    assert [response.status_code for response in responses] == [201, 201, 201, 429]
    assert Issue.objects.count() == 3
    payload = responses[-1].json()
    assert "Испратени се премногу пријави" in payload["errors"]["rate_limit"][0]
    assert payload["meta"]["retry_after_seconds"] > 0
    assert responses[-1]["Retry-After"] == str(payload["meta"]["retry_after_seconds"])


@pytest.mark.django_db
def test_staff_attachment_is_private_and_municipality_scoped(client, tmp_path):
    user_model = get_user_model()
    konce = Municipality.objects.create(name="Општина Конче", slug="konce")
    radovis = Municipality.objects.create(name="Општина Радовиш", slug="radovis")
    settlement = Settlement.objects.create(municipality=konce, name="Конче")
    category = IssueCategory.objects.create(municipality=konce, name="Комунално")
    issue = Issue.objects.create(
        municipality=konce,
        settlement=settlement,
        category=category,
        title="Пријава со фотографија",
        description="Опис",
        location_text="Локација",
    )
    konce_staff = user_model.objects.create_user(username="photo-konce", password="testpass")
    radovis_staff = user_model.objects.create_user(username="photo-radovis", password="testpass")
    StaffProfile.objects.create(user=konce_staff, municipality=konce)
    StaffProfile.objects.create(user=radovis_staff, municipality=radovis)

    with override_settings(MEDIA_ROOT=tmp_path):
        attachment = IssueAttachment.objects.create(
            issue=issue,
            image=SimpleUploadedFile("photo.jpg", b"private-photo", content_type="image/jpeg"),
        )
        protected_url = reverse("api_staff_attachment", args=[attachment.pk])
        public_media_url = attachment.image.url

        client.force_login(konce_staff)
        detail_response = client.get(f"/api/staff/issues/{issue.pk}/")
        own_response = client.get(protected_url)
        assert detail_response.json()["data"]["attachments"][0]["url"] == protected_url
        assert own_response.status_code == 200
        assert b"".join(own_response.streaming_content) == b"private-photo"
        assert own_response["Cache-Control"] == "private, no-store"

        client.force_login(radovis_staff)
        assert client.get(protected_url).status_code == 404
        assert client.get(public_media_url).status_code == 404

        client.logout()
        assert client.get(protected_url).status_code in {401, 403}


@pytest.mark.django_db
def test_retention_preview_apply_and_repeat_are_audited(client, tmp_path):
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    superuser = get_user_model().objects.create_superuser(
        username="retention-owner",
        email="owner@example.com",
        password="testpass",
    )
    DataRetentionPolicy.objects.create(
        municipality=municipality,
        contact_retention_days=365,
        attachment_retention_days=1825,
    )
    now = timezone.now()
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Стара затворена пријава",
        description="Опис",
        location_text="Локација",
        citizen_name="Име",
        citizen_email="citizen@example.com",
        citizen_phone="070000000",
        submitted_ip_hash="ip-hash",
        submitted_user_agent_hash="ua-hash",
        status=IssueStatus.CLOSED,
        closed_at=now - timedelta(days=1900),
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        attachment = IssueAttachment.objects.create(
            issue=issue,
            image=SimpleUploadedFile("old.jpg", b"old-photo", content_type="image/jpeg"),
        )
        attachment_path = Path(attachment.image.path)
        limit = SubmissionRateLimit.objects.create(
            municipality=municipality,
            ip_hash="expired-limit",
            window_start=now - timedelta(days=3),
        )
        SubmissionRateLimit.objects.filter(pk=limit.pk).update(updated_at=now - timedelta(days=3))

        preview = preview_retention([municipality], now=now)[0]
        assert preview["contact_count"] == 1
        assert preview["attachment_issue_count"] == 1
        assert preview["rate_limit_count"] == 1

        summary = apply_retention([municipality], superuser, now=now)[0]
        issue.refresh_from_db()
        assert summary["contact_count"] == 1
        assert summary["attachment_count"] == 1
        assert issue.is_anonymous is True
        assert issue.citizen_name == issue.citizen_email == issue.citizen_phone == ""
        assert issue.submitted_ip_hash == issue.submitted_user_agent_hash == ""
        assert issue.contact_anonymized_at == now
        assert issue.attachments_deleted_at == now
        assert not attachment_path.exists()
        attachment.refresh_from_db()
        assert attachment.deletion_state == AttachmentDeletionState.DELETED
        assert attachment.deleted_at == now
        assert not attachment.image.storage.exists(attachment.image.name)
        assert not SubmissionRateLimit.objects.filter(pk=limit.pk).exists()
        assert AuditLog.objects.filter(action="data_retention_applied", actor=superuser).exists()

        repeated = apply_retention([municipality], superuser, now=now)[0]
        assert repeated["contact_count"] == 0
        assert repeated["attachment_issue_count"] == 0


@pytest.mark.django_db
def test_declarative_municipality_configuration_stays_unverified_until_superuser_approval():
    path = Path(__file__).resolve().parents[1] / "municipalities" / "config" / "konce.json"
    data = load_configuration(path)
    municipality = apply_configuration(data, "Bundled starter")

    assert municipality.configuration_status == ConfigurationStatus.UNVERIFIED
    assert municipality.settlements.filter(is_active=True).count() == len(data["settlements"])
    assert municipality.departments.filter(is_active=True).count() == len(data["departments"])
    assert municipality.response_target.review_hours == data["response_targets"]["review_hours"]
    assert (
        municipality.response_target.resolution_hours
        == data["response_targets"]["resolution_hours"]
    )
    assert validate_municipality_configuration(municipality) == []

    superuser = get_user_model().objects.create_superuser(
        username="config-owner",
        email="owner@example.com",
        password="testpass",
    )
    verify_stored_configuration(municipality, superuser, "Municipal decision 01/2026")
    municipality.refresh_from_db()

    assert municipality.configuration_status == ConfigurationStatus.VERIFIED
    assert municipality.configuration_verified_by == superuser
    assert municipality.configuration_source == "Municipal decision 01/2026"
    assert AuditLog.objects.filter(
        action="municipality_configuration_verified",
        municipality=municipality,
        actor=superuser,
    ).exists()


@pytest.mark.django_db
def test_api_status_change_requires_sensitive_note(client):
    user_model = get_user_model()
    municipality = Municipality.objects.create(name="Општина Конче", slug="konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    issue = Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Дупка на пат",
        description="Опис",
        location_text="Локација",
    )
    staff = user_model.objects.create_user(username="api-coordinator", password="testpass")
    StaffProfile.objects.create(user=staff, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(staff)

    response = client.post(
        f"/api/staff/issues/{issue.pk}/status/",
        {"status": IssueStatus.RESOLVED, "note": ""},
        content_type="application/json",
    )

    assert response.status_code == 400
    issue.refresh_from_db()
    assert issue.status == IssueStatus.PENDING_TRIAGE
