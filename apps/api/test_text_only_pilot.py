import json
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.issues.models import Issue, IssueAttachment, IssueCategory, SubmissionRateLimit
from apps.municipalities.models import Municipality, Settlement

pytestmark = pytest.mark.django_db


@pytest.fixture
def pilot():
    municipality = Municipality.objects.create(name="Пилот", slug="pilot")
    settlement = Settlement.objects.create(municipality=municipality, name="Центар")
    category = IssueCategory.objects.create(municipality=municipality, name="Друго")
    return municipality, {
        "settlement": settlement.pk,
        "category": category.pk,
        "title": "Не работи светилка",
        "description": "Уличната светилка не работи од вчера.",
        "location_text": "До училиштето",
        "consent": "on",
    }


def submission_url(municipality, endpoint):
    if endpoint == "api":
        return f"/api/municipalities/{municipality.slug}/issues/"
    return reverse("submit_issue", args=[municipality.slug])


@pytest.mark.parametrize("endpoint", ["api", "legacy"])
def test_text_only_submission_creates_trackable_report_without_media(client, settings, tmp_path, pilot, endpoint):
    settings.MEDIA_ROOT = tmp_path
    municipality, payload = pilot
    assert municipality.photo_uploads_enabled is False
    response = client.post(submission_url(municipality, endpoint), payload)
    assert response.status_code == (201 if endpoint == "api" else 200)
    issue = Issue.objects.get()
    assert issue.title == payload["title"]
    assert IssueAttachment.objects.count() == 0
    assert not list(tmp_path.rglob("*"))
    tracked = client.get(f"/api/municipalities/{municipality.slug}/track/", {"code": issue.tracking_code})
    assert tracked.status_code == 200


@pytest.mark.parametrize("endpoint", ["api", "legacy"])
@pytest.mark.parametrize("file_field", ["photos", "attachment"])
def test_disabled_uploads_are_rejected_before_processing_or_saving(client, settings, tmp_path, pilot, endpoint, file_field):
    settings.MEDIA_ROOT = tmp_path
    municipality, payload = pilot
    payload[file_field] = SimpleUploadedFile("photo.png", b"unexpected-image", content_type="image/png")
    module = "apps.api.views" if endpoint == "api" else "apps.issues.views_public"
    with patch(f"{module}.prepare_issue_images") as process:
        response = client.post(submission_url(municipality, endpoint), payload)
    assert response.status_code == (400 if endpoint == "api" else 200)
    if endpoint == "api":
        assert "не е достапно" in response.json()["errors"]["__all__"][0]
    else:
        assert "не е достапно" in response.content.decode()
    process.assert_not_called()
    assert Issue.objects.count() == 0
    assert IssueAttachment.objects.count() == 0
    assert SubmissionRateLimit.objects.count() == 0
    assert not list(tmp_path.rglob("*"))


def test_json_report_and_receipt_work_without_multipart(client, pilot):
    municipality, payload = pilot
    payload.update(citizen_email="citizen@example.com", send_receipt="on")
    with patch("apps.api.views.queue_receipt_delivery") as queue:
        response = client.post(submission_url(municipality, "api"), json.dumps(payload), content_type="application/json")
    assert response.status_code == 201
    assert response.json()["data"]["receipt_delivery"] == "queued"
    queue.assert_called_once_with(Issue.objects.get())


def test_json_encoded_photo_payload_is_not_silently_accepted(client, pilot):
    municipality, payload = pilot
    payload["photos"] = ["data:image/png;base64,unexpected"]
    response = client.post(submission_url(municipality, "api"), json.dumps(payload), content_type="application/json")
    assert response.status_code == 400
    assert Issue.objects.count() == 0


def test_photo_feature_is_municipality_scoped_and_controls_legacy_form(client, pilot):
    municipality, _ = pilot
    other = Municipality.objects.create(name="Друга", slug="other")
    options_url = f"/api/municipalities/{municipality.slug}/form-options/"
    assert client.get(options_url).json()["data"]["municipality"]["photo_uploads_enabled"] is False
    form = client.get(submission_url(municipality, "legacy")).content.decode()
    assert 'name="photos"' not in form
    municipality.photo_uploads_enabled = True
    municipality.save(update_fields=["photo_uploads_enabled"])
    assert client.get(options_url).json()["data"]["municipality"]["photo_uploads_enabled"] is True
    form = client.get(submission_url(municipality, "legacy")).content.decode()
    assert 'name="photos"' in form
    assert client.get(f"/api/municipalities/{other.slug}/form-options/").json()["data"]["municipality"]["photo_uploads_enabled"] is False
