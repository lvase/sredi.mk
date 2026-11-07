"""Internal HTTP/load probe for test_production_startup.py's disposable database only."""
import argparse
import io
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["load", "outage"])
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    if os.environ.get("STARTUP_SMOKE_TEST") != "1" or os.environ.get("POSTGRES_DB") != "sredi_startup_test":
        raise RuntimeError("This probe only runs in the isolated startup test database")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test import Client

    from apps.accounts.models import StaffProfile, StaffRole
    from apps.issues.models import Issue, IssueCategory, ReceiptDelivery
    from apps.issues.tasks import dispatch_receipt_deliveries
    from apps.municipalities.models import Municipality, Settlement

    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original_getaddrinfo("nginx" if host == args.domain else host, *a, **kw)
    context = ssl.create_default_context(cafile="/tmp/startup-ca.pem")
    base = f"https://{args.domain}"

    def opener():
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(path, payload=None, cookie=None, browser=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = f"sessionid={cookie}"
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        started = time.perf_counter()
        try:
            response = (browser or opener()).open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = json.load(response)
            return response.status, body, time.perf_counter() - started

    if args.stage == "outage":
        municipality = Municipality.objects.get(slug="startup-load")
        payload = dict(settlement=municipality.settlements.first().pk, category=municipality.issue_categories.first().pk,
                       title="Outage", description="Outage", location_text="Center", consent="on")
        before = Issue.objects.count()
        code, _, _ = request("/api/municipalities/startup-load/issues/", payload)
        assert code == 503, code
        assert Issue.objects.count() == before
        code, body, _ = request("/health/ready/")
        assert code == 503 and body["dependencies"]["redis"] == "unavailable"
        print("Redis outage: submission rejected safely, no report created, readiness 503", flush=True)
        return

    municipality = Municipality.objects.create(name="Startup load", slug="startup-load")
    settlement = Settlement.objects.create(municipality=municipality, name="Center")
    category = IssueCategory.objects.create(municipality=municipality, name="Roads")
    call_command("seed_load_profile", municipality=municipality.slug, reports=78000,
                 confirm="SEED-startup-load-78000", stdout=io.StringIO())
    user = get_user_model().objects.create_user(username="startup-load-staff")
    StaffProfile.objects.create(user=user, municipality=municipality, role=StaffRole.COORDINATOR)
    client = Client()
    client.force_login(user)
    session = client.cookies["sessionid"].value
    for mode in ("cold", "warm"):
        barrier = threading.Barrier(100)
        def read(index, barrier=barrier):
            path = ("/api/municipalities/startup-load/" if index < 60 else
                    "/api/municipalities/startup-load/statistics/?period=all" if index < 80 else
                    "/api/staff/issues/?page_size=25")
            browser = opener()
            barrier.wait()
            return request(path, cookie=session if index >= 80 else None, browser=browser)
        with ThreadPoolExecutor(max_workers=100) as pool:
            responses = list(pool.map(read, range(100)))
        statuses = [code for code, _, _ in responses]
        assert all(code == 200 for code in statuses), statuses
        durations = sorted(elapsed for _, _, elapsed in responses)
        assert durations[94] < 5, durations[94]
        print(f"HTTPS + Redis, 78k reports, 100 simultaneous {mode} reads: 100/100 successful; p95={durations[94]:.3f}s", flush=True)

    barrier = threading.Barrier(20)
    def submit(index):
        browser = opener()
        assert request("/api/auth/csrf/", browser=browser)[0] == 200
        payload = dict(settlement=settlement.pk, category=category.pk, title=f"Load {index}",
                       description="Controlled test", location_text="Center", consent="on",
                       citizen_email="receipt@test.invalid", send_receipt="on", submission_key=str(uuid.uuid4()))
        barrier.wait()
        first = request("/api/municipalities/startup-load/issues/", payload, browser=browser)
        second = request("/api/municipalities/startup-load/issues/", payload, browser=browser)
        assert first[0] == second[0] == 201, (first, second)
        assert first[1]["data"]["tracking_code"] == second[1]["data"]["tracking_code"]
        return first[2]
    with ThreadPoolExecutor(max_workers=20) as pool:
        submission_times = list(pool.map(submit, range(20)))
    assert Issue.objects.count() == 78020
    assert ReceiptDelivery.objects.count() == 20
    print(f"20 simultaneous submissions from shared IP + retries: exactly 20 reports/outbox rows; max={max(submission_times):.3f}s", flush=True)
    dispatch_receipt_deliveries.run()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and ReceiptDelivery.objects.filter(state="queued").exists():
        time.sleep(0.2)
    assert ReceiptDelivery.objects.filter(state="sent").count() == 20
    print("Real Redis/Celery worker delivered all 20 receipts using test-only in-memory mail backend", flush=True)


if __name__ == "__main__":
    main()
