import logging
import secrets

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.issues.image_processing import (
    PROCESSING_VERSION,
    IssueImageValidationError,
    process_issue_image,
)
from apps.issues.models import AttachmentDeletionState, IssueAttachment
from apps.issues.storage import attachment_writes_enabled
from apps.municipalities.models import Municipality

logger = logging.getLogger(__name__)


def _delete_file_safely(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.exception("issue_image_migration_delete_failed")


class Command(BaseCommand):
    help = "Safely reprocess legacy issue attachments into normalized WebP files."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--municipality", default="", metavar="SLUG")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--resume-from", type=int, default=0, metavar="ATTACHMENT_ID")

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        maintenance_lock_acquired = False
        if options["apply"]:
            if not attachment_writes_enabled():
                raise CommandError("Attachment writes are disabled because storage is critical")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(%s)", [settings.MEDIA_MAINTENANCE_LOCK_ID]
                )
                maintenance_lock_acquired = cursor.fetchone()[0]
            if not maintenance_lock_acquired:
                raise CommandError("Backup or another media-maintenance operation is running")

        queryset = (
            IssueAttachment.objects.exclude(processing_version=PROCESSING_VERSION)
            .filter(deletion_state=AttachmentDeletionState.ACTIVE)
            .filter(pk__gt=options["resume_from"])
            .select_related("issue", "issue__municipality")
            .order_by("pk")
        )
        municipality_slug = options["municipality"]
        if municipality_slug:
            if not Municipality.objects.filter(slug=municipality_slug).exists():
                raise CommandError(f"Unknown municipality: {municipality_slug}")
            queryset = queryset.filter(issue__municipality__slug=municipality_slug)

        attachment_ids = list(queryset.values_list("pk", flat=True)[: options["batch_size"]])
        processed_count = 0
        invalid_count = 0
        skipped_count = 0
        last_id = options["resume_from"]

        for attachment_id in attachment_ids:
            last_id = attachment_id
            attachment = queryset.get(pk=attachment_id)
            try:
                attachment.image.open("rb")
                processed = process_issue_image(attachment.image)
            except (IssueImageValidationError, OSError) as exc:
                invalid_count += 1
                message = exc.errors[0] if isinstance(exc, IssueImageValidationError) else str(exc)
                self.stderr.write(f"attachment {attachment_id}: invalid ({message})")
                continue
            finally:
                try:
                    attachment.image.close()
                except Exception:
                    pass

            if options["dry_run"]:
                processed_count += 1
                self.stdout.write(
                    f"attachment {attachment_id}: would store {processed.stored_size_bytes} bytes "
                    f"at {processed.width}x{processed.height}"
                )
                continue

            old_name = attachment.image.name
            storage = attachment.image.storage
            generated_name = attachment.image.field.generate_filename(
                attachment, f"{secrets.token_hex(16)}.webp"
            )
            new_name = None
            try:
                new_name = storage.save(generated_name, ContentFile(processed.content))
                with transaction.atomic():
                    locked = IssueAttachment.objects.select_for_update().get(pk=attachment_id)
                    if (
                        locked.processing_version == PROCESSING_VERSION
                        or locked.image.name != old_name
                        or locked.deletion_state != AttachmentDeletionState.ACTIVE
                    ):
                        skipped_count += 1
                        transaction.on_commit(
                            lambda storage=storage, name=new_name: _delete_file_safely(storage, name)
                        )
                        continue
                    locked.image.name = new_name
                    locked.original_size_bytes = processed.original_size_bytes
                    locked.stored_size_bytes = processed.stored_size_bytes
                    locked.processed_width = processed.width
                    locked.processed_height = processed.height
                    locked.stored_format = processed.stored_format
                    locked.processing_version = processed.processing_version
                    locked.save(
                        update_fields=[
                            "image",
                            "original_size_bytes",
                            "stored_size_bytes",
                            "processed_width",
                            "processed_height",
                            "stored_format",
                            "processing_version",
                        ]
                    )
                    transaction.on_commit(
                        lambda storage=storage, name=old_name: _delete_file_safely(storage, name)
                    )
                processed_count += 1
                logger.info(
                    "legacy_issue_image_processed",
                    extra={
                        "issue_attachment_id": attachment_id,
                        "municipality_id": attachment.issue.municipality_id,
                        "original_size_bytes": processed.original_size_bytes,
                        "stored_size_bytes": processed.stored_size_bytes,
                        "reduction_ratio": round(
                            1 - (processed.stored_size_bytes / processed.original_size_bytes), 4
                        ),
                        "processed_width": processed.width,
                        "processed_height": processed.height,
                        "processing_version": processed.processing_version,
                    },
                )
            except Exception:
                if new_name:
                    _delete_file_safely(storage, new_name)
                raise

        remaining = queryset.filter(pk__gt=last_id).exists()
        mode = "dry-run" if options["dry_run"] else "apply"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: processed={processed_count} invalid={invalid_count} "
                f"skipped={skipped_count} last_id={last_id} remaining={'yes' if remaining else 'no'}"
            )
        )
        if remaining:
            self.stdout.write(f"Resume with --resume-from {last_id}")
        if maintenance_lock_acquired:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(%s)", [settings.MEDIA_MAINTENANCE_LOCK_ID]
                )
