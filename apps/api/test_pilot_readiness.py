import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import StaffProfile, StaffRole
from apps.issues.models import AuditLog, Issue, IssueCategory, IssueStatus
from apps.municipalities.models import Municipality, Settlement


def issue_for(municipality, settlement, category, title="Приватен наслов"):
    return Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title=title,
        description="Приватен опис",
        location_text="Приватна локација",
    )


@pytest.mark.django_db
def test_title_moderation_permissions_isolation_audit_and_revocation(client):
    municipality = Municipality.objects.create(name="Општина А", slug="a")
    other = Municipality.objects.create(name="Општина Б", slug="b")
    settlement = Settlement.objects.create(municipality=municipality, name="Центар")
    category = IssueCategory.objects.create(municipality=municipality, name="Осветлување")
    issue = issue_for(municipality, settlement, category)
    coordinator = get_user_model().objects.create_user(username="coord", password="testpass")
    StaffProfile.objects.create(
        user=coordinator, municipality=municipality, role=StaffRole.COORDINATOR
    )
    outsider = get_user_model().objects.create_user(username="outside", password="testpass")
    StaffProfile.objects.create(user=outsider, municipality=other, role=StaffRole.COORDINATOR)

    client.force_login(outsider)
    assert client.post(
        f"/api/staff/issues/{issue.pk}/public-title/approve/",
        {"public_title": "Безбеден јавен наслов"},
    ).status_code == 404

    client.force_login(coordinator)
    approved = client.post(
        f"/api/staff/issues/{issue.pk}/public-title/approve/",
        {"public_title": "Безбеден јавен наслов"},
    )
    assert approved.status_code == 200
    issue.refresh_from_db()
    assert issue.title == "Приватен наслов"
    assert issue.public_title == "Безбеден јавен наслов"
    assert issue.public_title_approved_by == coordinator
    assert AuditLog.objects.filter(action="issue_public_title_approved", object_id=str(issue.pk)).exists()

    public = client.get(f"/api/municipalities/{municipality.slug}/statistics/?period=all").json()["data"]
    assert public["recent_reports"][0]["title"] == "Безбеден јавен наслов"
    assert "Приватен наслов" not in str(public["recent_reports"])
    assert "Приватен опис" not in str(public)
    assert "Приватна локација" not in str(public)

    revoked = client.post(f"/api/staff/issues/{issue.pk}/public-title/revoke/", {})
    assert revoked.status_code == 200
    assert client.get(
        f"/api/municipalities/{municipality.slug}/statistics/?period=all"
    ).json()["data"]["recent_reports"] == []
    assert AuditLog.objects.filter(action="issue_public_title_revoked", object_id=str(issue.pk)).exists()


@pytest.mark.django_db
def test_viewer_cannot_moderate_and_spam_never_appears(client):
    municipality = Municipality.objects.create(name="Општина А", slug="a")
    settlement = Settlement.objects.create(municipality=municipality, name="Центар")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    issue = issue_for(municipality, settlement, category)
    viewer = get_user_model().objects.create_user(username="viewer", password="testpass")
    StaffProfile.objects.create(user=viewer, municipality=municipality, role=StaffRole.VIEWER)
    client.force_login(viewer)
    assert client.post(
        f"/api/staff/issues/{issue.pk}/public-title/approve/",
        {"public_title": "Не смее да биде јавно"},
    ).status_code == 403

    issue.public_title = "Спам наслов"
    issue.public_title_approved_at = issue.submitted_at
    issue.status = IssueStatus.REJECTED_SPAM
    issue.save()
    payload = client.get(
        f"/api/municipalities/{municipality.slug}/statistics/?period=all"
    ).json()["data"]
    assert payload["recent_reports"] == []
    assert payload["stats"]["total"] == 0


@pytest.mark.django_db
def test_health_checks_and_public_crest_do_not_expose_private_media(client):
    municipality = Municipality.objects.create(
        name="Општина А",
        slug="a",
        official_coat_of_arms=SimpleUploadedFile(
            "crest.png",
            b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
        ),
    )
    assert client.get("/health/live/").json() == {"status": "ok"}
    assert client.get("/health/ready/").json() == {"status": "ready"}
    detail = client.get(f"/api/municipalities/{municipality.slug}/").json()["data"]
    assert detail["official_coat_of_arms_url"].endswith(
        f"/api/municipalities/{municipality.slug}/crest/"
    )
    assert client.get(detail["official_coat_of_arms_url"]).status_code == 200
    assert client.get(municipality.official_coat_of_arms.url).status_code == 404
