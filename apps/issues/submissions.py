"""Submission retry identity; keys never grant access to a different payload."""
import hashlib
import json
import uuid

from apps.issues.models import Issue


class SubmissionConflict(ValueError):
    pass


def submission_identity(request, data, files):
    raw_key = request.headers.get("Idempotency-Key") or data.get("submission_key")
    if not raw_key:
        return None, ""
    try:
        key = uuid.UUID(str(raw_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Невалиден идентификатор на пријавата.") from exc
    fields = ["settlement", "category", "title", "description", "location_text",
              "citizen_name", "citizen_email", "citizen_phone", "consent", "website", "send_receipt"]
    content = {name: str(data.get(name, "")) for name in fields}
    photo_hashes = []
    for upload in files:
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        photo_hashes.append(digest.hexdigest())
    content["photos"] = photo_hashes
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    return key, digest


def existing_submission(municipality, key, digest):
    if key is None:
        return None
    issue = Issue.objects.filter(municipality=municipality, submission_key=key).first()
    if issue and issue.submission_digest != digest:
        raise SubmissionConflict("Оваа пријава веќе е испратена со различни податоци. Започнете нова пријава.")
    return issue
