from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.issues.image_processing import (
    PROCESSING_VERSION,
    IssueImageValidationError,
    prepare_issue_images,
    process_issue_image,
)
from apps.issues.models import Issue, IssueAttachment, IssueCategory
from apps.municipalities.models import Municipality, Settlement


def image_upload(
    name="photo.jpg",
    *,
    size=(320, 240),
    image_format="JPEG",
    mode="RGB",
    color=(30, 90, 150),
    exif=None,
):
    image = Image.new(mode, size, color)
    output = BytesIO()
    save_kwargs = {"format": image_format}
    if exif is not None:
        save_kwargs["exif"] = exif
    image.save(output, **save_kwargs)
    image.close()
    content_types = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_types[image_format])


def animated_webp_upload():
    first = Image.new("RGB", (32, 32), "red")
    second = Image.new("RGB", (32, 32), "blue")
    output = BytesIO()
    first.save(output, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
    first.close()
    second.close()
    return SimpleUploadedFile("animated.webp", output.getvalue(), content_type="image/webp")


@pytest.fixture
def issue_form_data():
    municipality = Municipality.objects.create(name="Општина Конче", slug="image-konce")
    settlement = Settlement.objects.create(municipality=municipality, name="Конче")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    return municipality, {
        "settlement": settlement.pk,
        "category": category.pk,
        "title": "Пријава со фотографија",
        "description": "Опис на проблемот",
        "location_text": "Центар",
        "consent": "on",
        "website": "",
    }


def make_issue():
    municipality = Municipality.objects.create(name="Општина Радовиш", slug="image-radovis")
    settlement = Settlement.objects.create(municipality=municipality, name="Радовиш")
    category = IssueCategory.objects.create(municipality=municipality, name="Комунално")
    return Issue.objects.create(
        municipality=municipality,
        settlement=settlement,
        category=category,
        title="Legacy image",
        description="Опис",
        location_text="Центар",
    )


def test_processing_normalizes_resizes_and_strips_metadata():
    exif = Image.Exif()
    exif[270] = "private description"
    upload = image_upload(size=(3000, 1200), exif=exif)

    processed = process_issue_image(upload)

    assert processed.stored_format == "WEBP"
    assert processed.width == 2048
    assert processed.height == 819
    assert processed.stored_size_bytes <= 800 * 1024
    with Image.open(BytesIO(processed.content)) as stored:
        assert stored.format == "WEBP"
        assert "exif" not in stored.info
        assert "xmp" not in stored.info


def test_processing_applies_exif_orientation_without_upscaling():
    exif = Image.Exif()
    exif[274] = 6
    processed = process_issue_image(image_upload(size=(80, 40), exif=exif))

    assert (processed.width, processed.height) == (40, 80)


def test_processing_preserves_transparency():
    processed = process_issue_image(
        image_upload(
            "transparent.png",
            image_format="PNG",
            mode="RGBA",
            color=(20, 40, 60, 0),
        )
    )

    with Image.open(BytesIO(processed.content)) as stored:
        assert stored.mode == "RGBA"
        assert stored.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize(
    ("name", "image_format", "mode"),
    [
        ("photo.jpg", "JPEG", "CMYK"),
        ("photo.png", "PNG", "L"),
        ("photo.webp", "WEBP", "RGB"),
    ],
)
def test_processing_accepts_supported_formats_and_color_modes(name, image_format, mode):
    color = 80 if mode == "L" else ((10, 20, 30, 40) if mode == "CMYK" else (10, 20, 30))
    processed = process_issue_image(
        image_upload(name, image_format=image_format, mode=mode, color=color)
    )

    with Image.open(BytesIO(processed.content)) as stored:
        assert stored.format == "WEBP"
        assert stored.mode == "RGB"


@pytest.mark.parametrize(
    ("upload", "message"),
    [
        (
            SimpleUploadedFile("broken.jpg", b"not an image", content_type="image/jpeg"),
            "валидна слика",
        ),
        (animated_webp_upload(), "Анимирани"),
        (image_upload("spoof.png", image_format="JPEG"), "Наставката"),
    ],
)
def test_processing_rejects_corrupt_animated_and_spoofed_images(upload, message):
    with pytest.raises(IssueImageValidationError, match=message):
        process_issue_image(upload)


@override_settings(ISSUE_IMAGE_MAX_PIXEL_COUNT=100)
def test_processing_rejects_images_over_pixel_limit():
    with pytest.raises(IssueImageValidationError, match="24 мегапиксели"):
        process_issue_image(image_upload(size=(11, 10)))


@override_settings(ISSUE_IMAGE_MAX_OUTPUT_SIZE_BYTES=1500, ISSUE_IMAGE_MIN_LONG_EDGE=64)
def test_processing_dimension_and_quality_fallback_honors_output_limit():
    image = Image.effect_noise((512, 512), 100).convert("RGB")
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    upload = SimpleUploadedFile("noise.png", output.getvalue(), content_type="image/png")

    processed = process_issue_image(upload)

    assert processed.stored_size_bytes <= 1500
    assert max(processed.width, processed.height) < 512


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["api", "legacy"])
def test_submission_paths_store_only_processed_webp(client, tmp_path, issue_form_data, endpoint):
    municipality, payload = issue_form_data
    url = (
        f"/api/municipalities/{municipality.slug}/issues/"
        if endpoint == "api"
        else reverse("submit_issue", args=[municipality.slug])
    )
    payload = {**payload, "photos": image_upload(size=(2400, 1200))}

    with override_settings(MEDIA_ROOT=tmp_path):
        response = client.post(url, payload)

        assert response.status_code in {200, 201}
        attachment = IssueAttachment.objects.get()
        assert attachment.image.name.endswith(".webp")
        assert attachment.original_size_bytes
        assert attachment.stored_size_bytes == Path(attachment.image.path).stat().st_size
        assert attachment.processed_width == 2048
        assert attachment.processed_height == 1024
        assert attachment.stored_format == "WEBP"
        assert attachment.processing_version == PROCESSING_VERSION
        with Image.open(attachment.image.path) as stored:
            assert stored.format == "WEBP"


@pytest.mark.django_db
def test_attachment_save_failure_rolls_back_issue_rows_and_files(
    client, tmp_path, issue_form_data
):
    municipality, payload = issue_form_data
    client.raise_request_exception = False

    with (
        override_settings(MEDIA_ROOT=tmp_path),
        patch("apps.issues.image_processing.IssueAttachment.save", side_effect=RuntimeError("db")),
    ):
        response = client.post(
            f"/api/municipalities/{municipality.slug}/issues/",
            {**payload, "photos": image_upload()},
        )

    assert response.status_code == 500
    assert Issue.objects.count() == 0
    assert IssueAttachment.objects.count() == 0
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.django_db
def test_storage_failure_after_write_rolls_back_issue_and_orphan_file(
    client, tmp_path, issue_form_data
):
    municipality, payload = issue_form_data
    client.raise_request_exception = False
    original_save = FileSystemStorage._save

    def fail_after_write(storage, name, content):
        original_save(storage, name, content)
        raise RuntimeError("storage unavailable")

    with (
        override_settings(MEDIA_ROOT=tmp_path),
        patch.object(FileSystemStorage, "_save", new=fail_after_write),
    ):
        response = client.post(
            f"/api/municipalities/{municipality.slug}/issues/",
            {**payload, "photos": image_upload()},
        )

    assert response.status_code == 500
    assert Issue.objects.count() == 0
    assert IssueAttachment.objects.count() == 0
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.django_db
def test_api_submission_still_accepts_five_images(client, tmp_path, issue_form_data):
    municipality, payload = issue_form_data

    with override_settings(MEDIA_ROOT=tmp_path):
        response = client.post(
            f"/api/municipalities/{municipality.slug}/issues/",
            {**payload, "photos": [image_upload() for _ in range(5)]},
        )

    assert response.status_code == 201
    assert Issue.objects.count() == 1
    assert IssueAttachment.objects.count() == 5


@pytest.mark.django_db(transaction=True)
def test_reprocess_command_dry_run_apply_and_repeat_are_safe(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        issue = make_issue()
        attachment = IssueAttachment.objects.create(issue=issue, image=image_upload())
        old_name = attachment.image.name
        old_path = Path(attachment.image.path)

        dry_output = StringIO()
        call_command("reprocess_issue_attachments", "--dry-run", stdout=dry_output)
        attachment.refresh_from_db()
        assert attachment.image.name == old_name
        assert attachment.processing_version is None
        assert old_path.exists()

        apply_output = StringIO()
        call_command("reprocess_issue_attachments", "--apply", stdout=apply_output)
        attachment.refresh_from_db()
        assert attachment.image.name != old_name
        assert attachment.image.name.endswith(".webp")
        assert attachment.processing_version == PROCESSING_VERSION
        assert not old_path.exists()
        assert Path(attachment.image.path).exists()

        repeated_output = StringIO()
        call_command("reprocess_issue_attachments", "--apply", stdout=repeated_output)
        attachment.refresh_from_db()
        assert "processed=0" in repeated_output.getvalue()


@pytest.mark.django_db(transaction=True)
def test_reprocess_command_database_failure_keeps_original_and_removes_new_file(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        issue = make_issue()
        attachment = IssueAttachment.objects.create(issue=issue, image=image_upload())
        old_name = attachment.image.name
        old_path = Path(attachment.image.path)

        with (
            patch.object(IssueAttachment, "save", side_effect=RuntimeError("database failure")),
            pytest.raises(RuntimeError, match="database failure"),
        ):
            call_command("reprocess_issue_attachments", "--apply")

        attachment.refresh_from_db()
        assert attachment.image.name == old_name
        assert old_path.exists()
        assert [path for path in tmp_path.rglob("*") if path.is_file()] == [old_path]


@pytest.mark.django_db
def test_media_usage_command_reports_totals_without_writes(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        issue = make_issue()
        attachment = IssueAttachment.objects.create(issue=issue, image=image_upload())
        before = (attachment.image.name, attachment.processing_version)
        output = StringIO()

        call_command("media_usage", stdout=output)
        attachment.refresh_from_db()

        assert "attachment_count=1" in output.getvalue()
        assert "municipality=image-radovis" in output.getvalue()
        assert (attachment.image.name, attachment.processing_version) == before


def test_prepare_rejects_more_than_five_images():
    with pytest.raises(IssueImageValidationError, match="најмногу 5"):
        prepare_issue_images([image_upload() for _ in range(6)])
