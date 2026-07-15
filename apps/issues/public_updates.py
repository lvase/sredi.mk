from apps.issues.models import AuditLog, IssueStatus
from apps.issues.services import public_status_label


def build_public_updates(issue):
    """Build a chronological, privacy-safe timeline for citizen tracking."""
    updates = [
        {
            "id": f"submitted-{issue.pk}",
            "kind": "submitted",
            "title": "Пријавата е примена",
            "body": "Пријавата е успешно примена и испратена до општината за обработка.",
            "status": IssueStatus.PENDING_TRIAGE,
            "status_label": public_status_label(IssueStatus.PENDING_TRIAGE),
            "created_at": issue.submitted_at,
        }
    ]

    comments = getattr(issue, "public_comments", None)
    if comments is None:
        comments = issue.comments.filter(is_internal=False)
    comments = list(comments)
    for comment in comments:
        updates.append(
            {
                "id": f"comment-{comment.pk}",
                "kind": "comment",
                "title": "Јавно ажурирање од општината",
                "body": comment.body,
                "status": "",
                "status_label": "",
                "created_at": comment.created_at,
            }
        )

    status_events = getattr(issue, "public_status_events", None)
    if status_events is None:
        status_events = issue.status_events.all()
    for event in status_events:
        label = public_status_label(event.to_status)
        updates.append(
            {
                "id": f"status-{event.pk}",
                "kind": "status",
                "title": "Статусот е ажуриран",
                "body": f"Статусот е променет во „{label}“.",
                "status": event.to_status,
                "status_label": label,
                "created_at": event.created_at,
            }
        )

    public_note = issue.public_resolution_note.strip()
    if public_note and not any(comment.body.strip() == public_note for comment in comments):
        note_log = next(
            (
                log
                for log in AuditLog.objects.filter(
                    object_type="Issue",
                    object_id=str(issue.pk),
                    action="issue_updated",
                ).order_by("-created_at")
                if "public_resolution_note" in log.metadata
            ),
            None,
        )
        updates.append(
            {
                "id": f"resolution-note-{issue.pk}",
                "kind": "note",
                "title": "Јавна белешка од општината",
                "body": public_note,
                "status": "",
                "status_label": "",
                "created_at": note_log.created_at if note_log else issue.updated_at,
            }
        )

    return sorted(updates, key=lambda update: (update["created_at"], update["id"]))
