import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import OperationalError, close_old_connections, connection
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import StaffProfile, StaffRole
from apps.api.views import StatisticsBusy, build_public_statistics
from apps.issues.image_processing import ProcessedIssueImage, save_issue_with_attachments
from apps.issues.models import Issue, IssueCategory, ReceiptDelivery
from apps.issues.operations import receipt_queue_state
from apps.issues.tasks import (
    dispatch_receipt_deliveries,
    monitor_delivery_queue,
    send_receipt_email,
)
from apps.municipalities.models import Municipality, Settlement


@pytest.fixture
def reporting():
    municipality = Municipality.objects.create(name="Recovery", slug="recovery")
    settlement = Settlement.objects.create(municipality=municipality, name="Center")
    category = IssueCategory.objects.create(municipality=municipality, name="Roads")
    payload = dict(settlement=settlement.pk, category=category.pk, title="Road repair",
                   description="Repair needed", location_text="Center", consent="on")
    return municipality, payload


@pytest.mark.django_db
@pytest.mark.parametrize("superuser", [False, True])
def test_password_only_session_cannot_access_staff_or_reset_factors(client, superuser):
    user = get_user_model().objects.create_user(username="factor", password="password", is_staff=True, is_superuser=superuser)
    TOTPDevice.objects.create(user=user, confirmed=True)
    # Simulate an old password-only session, including sessions minted before this fix.
    client.force_login(user)
    assert client.get("/api/staff/issues/").status_code == 403
    assert client.post("/api/auth/security/totp/setup/").status_code == 401
    assert client.get("/staff/").status_code == 302
    assert client.get("/api/auth/session/").json()["data"]["isAuthenticated"] is False


@pytest.mark.django_db
def test_alternate_logins_never_create_password_only_session(client):
    get_user_model().objects.create_superuser(username="owner", password="password")
    for path in ("/admin/login/", "/login/"):
        response = client.post(path, {"username": "owner", "password": "password"})
        assert response.status_code == 302
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_forced_password_change_blocks_existing_session(client):
    user = get_user_model().objects.create_user(username="temporary")
    StaffProfile.objects.create(user=user, must_change_password=True)
    client.force_login(user)
    assert client.get("/api/staff/issues/").status_code == 403


@pytest.mark.django_db
def test_forced_password_change_blocks_verified_admin_session(client):
    user = get_user_model().objects.create_superuser(username="temporary-admin")
    StaffProfile.objects.create(user=user, must_change_password=True)
    device = TOTPDevice.objects.create(user=user, confirmed=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    assert client.get("/admin/").status_code == 302


@pytest.mark.django_db
def test_existing_incomplete_session_can_restart_password_change(client):
    user = get_user_model().objects.create_user(username="restart", password="old-test-password")
    StaffProfile.objects.create(user=user, must_change_password=True)
    client.force_login(user)
    response = client.post("/api/auth/login/", {"username": "restart", "password": "old-test-password"})
    assert response.json()["data"]["next_step"] == "change_password"
    assert "_auth_user_id" not in client.session
    response = client.post("/api/auth/security/password/", {
        "current_password": "old-test-password", "new_password": "new-unique-test-password-852",
    })
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_existing_incomplete_session_can_restart_second_factor(client):
    from apps.accounts.tests import current_token

    user = get_user_model().objects.create_user(username="restart-otp", password="old-test-password")
    StaffProfile.objects.create(user=user)
    device = TOTPDevice.objects.create(user=user, confirmed=True)
    client.force_login(user)
    response = client.post("/api/auth/login/", {"username": "restart-otp", "password": "old-test-password"})
    assert response.json()["data"]["next_step"] == "verify_2fa"
    assert "_auth_user_id" not in client.session
    response = client.post("/api/auth/2fa/verify/", {"token": current_token(device)})
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("superuser", [False, True])
def test_pending_second_factor_cannot_replace_existing_authenticator(client, superuser):
    from apps.accounts.tests import current_token

    user = get_user_model().objects.create_user(username="enrollment-bypass", password="test-password", is_superuser=superuser)
    original = TOTPDevice.objects.create(user=user, confirmed=True)
    incomplete = TOTPDevice.objects.create(user=user, confirmed=False)
    response = client.post("/api/auth/login/", {"username": user.username, "password": "test-password"})
    assert response.json()["data"]["next_step"] == "verify_2fa"
    assert client.post("/api/auth/security/totp/setup/").status_code == 403
    assert client.post("/api/auth/security/totp/confirm/", {"token": current_token(incomplete)}).status_code == 403
    assert "_auth_user_id" not in client.session
    assert TOTPDevice.objects.filter(pk=original.pk, confirmed=True).exists()
    assert client.post("/api/auth/2fa/verify/", {"token": current_token(original)}).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("enrolled", [False, True])
def test_pending_password_change_cannot_skip_to_second_factor(client, enrolled):
    from apps.accounts.tests import current_token

    user = get_user_model().objects.create_superuser(username="password-bypass", password="test-password")
    StaffProfile.objects.create(user=user, must_change_password=True)
    device = TOTPDevice.objects.create(user=user, confirmed=enrolled)
    response = client.post("/api/auth/login/", {"username": user.username, "password": "test-password"})
    assert response.json()["data"]["next_step"] == "change_password"
    assert client.post("/api/auth/security/totp/setup/").status_code == 403
    assert client.post("/api/auth/security/totp/confirm/", {"token": current_token(device)}).status_code == 403
    assert client.post("/api/auth/2fa/verify/", {"token": current_token(device)}).status_code == 403
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db(transaction=True)
def test_statistics_callback_failure_preserves_committed_issue_and_media(reporting, tmp_path):
    municipality, payload = reporting
    issue = Issue(municipality=municipality, settlement_id=payload["settlement"], category_id=payload["category"], title="Saved", description="Saved", location_text="Saved")
    photo = ProcessedIssueImage(content=b"processed-photo", original_size_bytes=100, width=1, height=1)
    with override_settings(MEDIA_ROOT=tmp_path), patch("apps.issues.signals._increment_statistics_version", side_effect=OperationalError("temporary")):
        save_issue_with_attachments(issue, [photo])
        assert Issue.objects.filter(pk=issue.pk).exists()
        attachment = issue.attachments.get()
        assert attachment.image.storage.exists(attachment.image.name)


@pytest.mark.django_db
def test_retry_returns_original_and_changed_payload_conflicts(client, reporting):
    municipality, payload = reporting
    path = f"/api/municipalities/{municipality.slug}/issues/"
    key = str(uuid.uuid4())
    payload.update(citizen_email="review@example.com", send_receipt="on")
    first = client.post(path, payload, HTTP_IDEMPOTENCY_KEY=key)
    for _ in range(4):
        retried = client.post(path, payload, HTTP_IDEMPOTENCY_KEY=key)
        assert retried.status_code == 201
        assert retried.json() == first.json()
    assert Issue.objects.count() == ReceiptDelivery.objects.count() == 1
    assert client.post(path, {**payload, "title": "Different"}, HTTP_IDEMPOTENCY_KEY=key).status_code == 409
    assert client.post(path, payload, HTTP_IDEMPOTENCY_KEY="invalid").status_code == 400


@pytest.mark.django_db
def test_legacy_form_retries_keep_original_report_and_receipt(client, reporting):
    municipality, payload = reporting
    path = reverse("submit_issue", args=[municipality.slug])
    page = client.get(path)
    key = page.context["form"]["submission_key"].value()
    assert key
    payload.update(submission_key=str(key), citizen_email="legacy@example.com", send_receipt="on")
    first = client.post(path, payload)
    assert first.status_code == 200
    assert client.post(path, payload).context["issue"].pk == first.context["issue"].pk
    assert Issue.objects.count() == ReceiptDelivery.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_create_one_report_and_outbox_row(reporting):
    municipality, payload = reporting
    payload.update(submission_key=str(uuid.uuid4()), citizen_email="review@example.com", send_receipt="on")
    path = f"/api/municipalities/{municipality.slug}/issues/"
    def submit(_):
        close_old_connections()
        try:
            response = Client().post(path, payload)
            return response.status_code, response.json()
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    assert results[0][0] == 201
    assert Issue.objects.count() == ReceiptDelivery.objects.count() == 1


@pytest.mark.django_db
def test_receipt_record_failure_rolls_back_submission(client, reporting):
    municipality, payload = reporting
    with patch("apps.issues.delivery.queue_receipt_delivery", side_effect=OperationalError("database unavailable")), pytest.raises(OperationalError):
        client.post(f"/api/municipalities/{municipality.slug}/issues/", {**payload, "citizen_email": "test@example.com", "send_receipt": "on"})
    assert Issue.objects.count() == 0


@pytest.fixture
def delivery(reporting):
    municipality, payload = reporting
    issue = Issue.objects.create(municipality=municipality, settlement_id=payload["settlement"], category_id=payload["category"], title="Mail", description="Mail", location_text="Mail")
    return ReceiptDelivery.objects.create(issue=issue, recipient="review@example.com")


@pytest.mark.django_db
def test_failed_publish_remains_durable_then_recovers(delivery):
    with patch("apps.issues.tasks.send_receipt_email.apply_async", side_effect=ConnectionError):
        assert dispatch_receipt_deliveries.run()["deferred"] == 1
    delivery.refresh_from_db()
    assert delivery.state == "queued"
    assert delivery.dispatched_at is None
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    with patch("apps.issues.tasks.send_receipt_email.apply_async") as publish:
        assert dispatch_receipt_deliveries.run()["published"] == 1
        publish.assert_called_once()
        assert dispatch_receipt_deliveries.run()["published"] == 0
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(dispatched_at=timezone.now() - timedelta(minutes=6))
    with patch("apps.issues.tasks.send_receipt_email.apply_async"):
        assert dispatch_receipt_deliveries.run()["published"] == 1


@pytest.mark.django_db
def test_delivery_lease_prevents_duplicates_and_recovers_abandoned_worker(delivery):
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(lease_until=timezone.now() + timedelta(minutes=1))
    with patch("apps.issues.tasks.send_mail", return_value=1) as send:
        assert send_receipt_email.run(delivery.pk) == "deferred"
        send.assert_not_called()
        ReceiptDelivery.objects.filter(pk=delivery.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        assert send_receipt_email.run(delivery.pk) == "sent"
        assert send_receipt_email.run(delivery.pk) == "already_sent"
        send.assert_called_once()


@pytest.mark.django_db
def test_smtp_failure_backoff_and_final_failure_are_persistent(delivery):
    with patch("apps.issues.tasks.send_mail", side_effect=OSError):
        assert send_receipt_email.run(delivery.pk) == "retry_pending"
        assert send_receipt_email.run(delivery.pk) == "deferred"
        ReceiptDelivery.objects.filter(pk=delivery.pk).update(attempt_count=5, next_attempt_at=timezone.now())
        assert send_receipt_email.run(delivery.pk) == "failed"
    delivery.refresh_from_db()
    assert delivery.failed_at and not delivery.lease_until


@pytest.mark.django_db
def test_cold_statistics_waits_without_duplicate_computation(reporting):
    municipality, _ = reporting
    request = RequestFactory().get("/")
    request.query_params = {}
    with patch("apps.api.views.cache.get", return_value=None), patch("apps.api.views.cache.add", return_value=False), patch("apps.api.views.time.sleep"), patch("apps.api.views._compute_public_statistics") as compute:
        with pytest.raises(StatisticsBusy):
            build_public_statistics(request, municipality)
        compute.assert_not_called()


@pytest.mark.django_db
def test_statistics_failure_releases_lock(reporting):
    municipality, _ = reporting
    request = RequestFactory().get("/")
    request.query_params = {}
    with patch("apps.api.views._compute_public_statistics", side_effect=RuntimeError), pytest.raises(RuntimeError):
        build_public_statistics(request, municipality)
    with patch("apps.api.views._compute_public_statistics", return_value={"ok": True}):
        assert build_public_statistics(request, municipality) == {"ok": True}


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["settlement=undefined", "category=-1", "municipality=1.5", "assigned_to=" + "9" * 100, "status=invalid", "priority=invalid", "mine=maybe"])
def test_invalid_staff_filters_are_400(client, reporting, query):
    municipality, _ = reporting
    user = get_user_model().objects.create_user(username="filter")
    StaffProfile.objects.create(user=user, municipality=municipality, role=StaffRole.COORDINATOR)
    client.force_login(user)
    assert client.get(f"/api/staff/issues/?{query}").status_code == 400


@pytest.mark.django_db
def test_global_categories_are_offered_and_accepted(client, reporting):
    municipality, payload = reporting
    category = IssueCategory.objects.create(name="Global", municipality=None)
    options = client.get(f"/api/municipalities/{municipality.slug}/form-options/").json()["data"]
    assert category.pk in [row["id"] for row in options["categories"]]
    assert client.post(f"/api/municipalities/{municipality.slug}/issues/", {**payload, "category": category.pk}).status_code == 201


@pytest.mark.django_db
def test_shared_ip_allows_distinct_browsers_but_limits_each_browser(reporting):
    municipality, payload = reporting
    path = f"/api/municipalities/{municipality.slug}/issues/"
    clients = [Client() for _ in range(4)]
    for client in clients:
        client.get("/api/auth/csrf/")
        assert client.post(path, payload).status_code == 201
    for _ in range(2):
        assert clients[0].post(path, payload).status_code == 201
    assert clients[0].post(path, payload).status_code == 429


@pytest.mark.django_db
def test_network_quota_still_limits_cookie_rotation(reporting):
    municipality, payload = reporting
    with override_settings(ISSUE_NETWORK_RATE_LIMIT_HOURLY=2):
        statuses = []
        for _ in range(3):
            client = Client()
            client.get("/api/auth/csrf/")
            statuses.append(client.post(f"/api/municipalities/{municipality.slug}/issues/", payload).status_code)
    assert statuses == [201, 201, 429]


@pytest.mark.django_db
def test_search_indexes_match_upper_expressions():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname IN ('iss_upper_title_trgm_idx', 'iss_upper_location_trgm_idx')")
        indexes = [row[0].lower() for row in cursor.fetchall()]
    assert len(indexes) == 2
    assert all("upper(" in index and "gin_trgm_ops" in index for index in indexes)


@pytest.mark.django_db(transaction=True)
def test_issue_saves_do_not_invalidate_staff_configuration_cache(reporting):
    municipality, payload = reporting
    before = cache.get("staff-choices:version")
    Issue.objects.create(municipality=municipality, settlement_id=payload["settlement"], category_id=payload["category"], title="New", description="New", location_text="New")
    assert cache.get("staff-choices:version") == before


@pytest.mark.django_db
def test_delayed_queue_is_visible_without_disabling_report_acceptance(client, delivery):
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(queued_at=timezone.now() - timedelta(minutes=11))
    state = receipt_queue_state()
    assert state["pending"] == 1 and state["status"] == "warning"
    response = client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json()["dependencies"]["receipts"]["status"] == "warning"


@pytest.mark.django_db
@override_settings(REDIS_URL="redis://redis:6379/0", OPERATIONS_ALERT_EMAILS=["ops@example.com"])
def test_redis_memory_warning_alert_is_throttled():
    with patch("django_redis.get_redis_connection") as redis, patch("apps.issues.tasks.send_mail") as mail:
        redis.return_value.info.return_value = {"used_memory": 75, "maxmemory": 100, "used_memory_rss": 90}
        assert monitor_delivery_queue.run()["status"] == "warning"
        assert monitor_delivery_queue.run()["redis_used_percent"] == 75
        mail.assert_called_once()


@pytest.mark.django_db
def test_admin_requeues_failed_receipts_without_resending_sent_messages(delivery):
    from apps.issues.admin import retry_failed_receipts
    from apps.issues.models import AuditLog

    request = RequestFactory().post("/admin/")
    request.user = get_user_model().objects.create_superuser(username="recovery-admin")
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(state="sent")
    retry_failed_receipts(Mock(), request, ReceiptDelivery.objects.all())
    delivery.refresh_from_db()
    assert delivery.state == "sent"
    ReceiptDelivery.objects.filter(pk=delivery.pk).update(state="failed", attempt_count=6, failed_at=timezone.now())
    retry_failed_receipts(Mock(), request, ReceiptDelivery.objects.all())
    delivery.refresh_from_db()
    assert delivery.state == "queued" and delivery.attempt_count == 0
    assert delivery.failed_at is None
    assert AuditLog.objects.filter(action="receipt_deliveries_requeued", metadata__count=1).exists()
