import logging
import mimetypes
import secrets
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.issues.models import IssueAttachment
from apps.issues.storage import attachment_writes_enabled

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FORMAT_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
EXTENSION_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}

PROCESSING_VERSION = 1
MAX_PIXEL_COUNT = 24_000_000
MAX_LONG_EDGE = 2048
MIN_LONG_EDGE = 1024
MAX_OUTPUT_SIZE_BYTES = 800 * 1024
WEBP_QUALITIES = (82, 76, 70, 65)


class IssueImageValidationError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class ProcessedIssueImage:
    content: bytes
    original_size_bytes: int
    width: int
    height: int
    stored_format: str = "WEBP"
    processing_version: int = PROCESSING_VERSION

    @property
    def stored_size_bytes(self):
        return len(self.content)

    @property
    def name(self):
        return f"{secrets.token_hex(16)}.webp"


def _configured(name, default):
    return getattr(settings, name, default)


def _read_upload(upload):
    maximum = _configured("MAX_ISSUE_IMAGE_SIZE_BYTES", 5 * 1024 * 1024)
    try:
        upload.seek(0)
        content = upload.read(maximum + 1)
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass
    if len(content) > maximum:
        raise IssueImageValidationError(["Секоја фотографија мора да биде помала од 5 MB."])
    return content


def _declared_type(upload):
    content_type = getattr(upload, "content_type", "") or ""
    if content_type:
        return content_type.split(";", 1)[0].strip().lower()
    guessed, _ = mimetypes.guess_type(getattr(upload, "name", ""))
    return guessed or ""


def _validate_declarations(upload):
    suffix = Path(getattr(upload, "name", "")).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise IssueImageValidationError(
            ["Дозволени се само JPG, PNG или WEBP фотографии."]
        )
    content_type = _declared_type(upload)
    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise IssueImageValidationError(["Фотографиите мора да бидат JPG, PNG или WEBP."])
    return suffix, content_type


def _fit_long_edge(image, maximum):
    if max(image.size) > maximum:
        image.thumbnail((maximum, maximum), Image.Resampling.LANCZOS, reducing_gap=3.0)
    return image


def _encode_webp(image, quality):
    output = BytesIO()
    image.save(output, format="WEBP", quality=quality, method=4, exact=True)
    return output.getvalue()


def _encode_with_limit(image):
    current = _fit_long_edge(image, _configured("ISSUE_IMAGE_MAX_LONG_EDGE", MAX_LONG_EDGE))
    minimum_edge = _configured("ISSUE_IMAGE_MIN_LONG_EDGE", MIN_LONG_EDGE)
    maximum_bytes = _configured("ISSUE_IMAGE_MAX_OUTPUT_SIZE_BYTES", MAX_OUTPUT_SIZE_BYTES)
    while True:
        for quality in WEBP_QUALITIES:
            content = _encode_webp(current, quality)
            if len(content) <= maximum_bytes:
                return content, current.size

        longest = max(current.size)
        if longest <= minimum_edge:
            break
        next_longest = max(minimum_edge, int(longest * 0.9))
        current.thumbnail(
            (next_longest, next_longest),
            Image.Resampling.LANCZOS,
            reducing_gap=3.0,
        )
    raise IssueImageValidationError(
        ["Фотографијата не може безбедно да се намали до дозволената големина."]
    )


def process_issue_image(upload):
    suffix, content_type = _validate_declarations(upload)
    content = _read_upload(upload)
    if not content:
        raise IssueImageValidationError(
            ["Една од фотографиите не може да се прочита како валидна слика."]
        )

    try:
        with Image.open(BytesIO(content)) as image:
            decoded_format = (image.format or "").upper()
            if decoded_format not in FORMAT_CONTENT_TYPES:
                raise IssueImageValidationError(
                    ["Дозволени се само JPG, PNG или WEBP фотографии."]
                )
            if EXTENSION_FORMATS[suffix] != decoded_format:
                raise IssueImageValidationError(
                    ["Наставката на фотографијата не одговара на нејзиниот формат."]
                )
            if content_type and FORMAT_CONTENT_TYPES[decoded_format] != content_type:
                raise IssueImageValidationError(
                    ["Типот на фотографијата не одговара на нејзиниот формат."]
                )
            if getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False):
                raise IssueImageValidationError(["Анимирани фотографии не се дозволени."])
            if image.width * image.height > _configured(
                "ISSUE_IMAGE_MAX_PIXEL_COUNT", MAX_PIXEL_COUNT
            ):
                raise IssueImageValidationError(
                    ["Фотографијата има преголема резолуција (најмногу 24 мегапиксели)."]
                )
            maximum_edge = _configured("ISSUE_IMAGE_MAX_LONG_EDGE", MAX_LONG_EDGE)
            if decoded_format == "JPEG" and max(image.size) > maximum_edge:
                image.draft("RGB", (maximum_edge, maximum_edge))
            image.load()
            ImageOps.exif_transpose(image, in_place=True)
            _fit_long_edge(image, maximum_edge)
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            target_mode = "RGBA" if has_alpha else "RGB"
            prepared = image if image.mode == target_mode else image.convert(target_mode)
            try:
                encoded, (width, height) = _encode_with_limit(prepared)
            finally:
                if prepared is not image:
                    prepared.close()
    except IssueImageValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise IssueImageValidationError(
            ["Една од фотографиите не може да се прочита како валидна слика."]
        ) from None

    return ProcessedIssueImage(
        content=encoded,
        original_size_bytes=len(content),
        width=width,
        height=height,
    )


def prepare_issue_images(files):
    maximum_count = _configured("MAX_ISSUE_PHOTOS", 5)
    if len(files) > maximum_count:
        raise IssueImageValidationError(["Може да прикачиш најмногу 5 фотографии."])
    if files and not attachment_writes_enabled():
        raise IssueImageValidationError(
            ["Фотографиите се привремено исклучени поради ограничен простор. Пријавата може да се испрати без фотографии."]
        )

    processed = []
    errors = []
    for upload in files:
        try:
            processed.append(process_issue_image(upload))
        except IssueImageValidationError as exc:
            errors.extend(exc.errors)
    if errors:
        raise IssueImageValidationError(errors)
    return processed


def save_issue_with_attachments(issue, processed_images):
    written_files = []
    try:
        with transaction.atomic():
            issue.save()
            for processed in processed_images:
                attachment = IssueAttachment(
                    issue=issue,
                    original_size_bytes=processed.original_size_bytes,
                    stored_size_bytes=processed.stored_size_bytes,
                    processed_width=processed.width,
                    processed_height=processed.height,
                    stored_format=processed.stored_format,
                    processing_version=processed.processing_version,
                )
                storage = attachment.image.storage
                candidate_name = attachment.image.field.generate_filename(
                    attachment, processed.name
                )
                written_files.append((storage, candidate_name))
                saved_name = storage.save(candidate_name, ContentFile(processed.content))
                written_files[-1] = (storage, saved_name)
                attachment.image.name = saved_name
                attachment.save()
                logger.info(
                    "issue_image_processed",
                    extra={
                        "issue_attachment_id": attachment.pk,
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
        for storage, name in written_files:
            try:
                storage.delete(name)
            except Exception:
                logger.exception("issue_image_rollback_delete_failed")
        raise
    return issue
