from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


def validate_hex_color(value):
    if value and (
        len(value) != 7
        or not value.startswith("#")
        or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
    ):
        raise ValidationError("Внесете боја во формат #RRGGBB.")


def municipality_crest_path(instance, filename):
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return f"municipalities/{instance.slug}/official-crest.{suffix}"


class ConfigurationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    VERIFIED = "verified", "Verified"


class Municipality(models.Model):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    is_active = models.BooleanField(default=True)
    photo_uploads_enabled = models.BooleanField(
        default=False,
        verbose_name="Овозможи фотографии во пријави",
        help_text="Исклучено за пилотот. Постоечките прилози се зачувуваат.",
    )
    public_accent_color = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_color],
        help_text="Одобрена јавна акцентна боја во формат #RRGGBB.",
    )
    official_coat_of_arms = models.ImageField(
        upload_to=municipality_crest_path,
        blank=True,
        help_text="Поставете само официјално доставен и одобрен општински грб.",
    )
    configuration_status = models.CharField(
        max_length=20,
        choices=ConfigurationStatus.choices,
        default=ConfigurationStatus.UNVERIFIED,
    )
    configuration_source = models.CharField(max_length=255, blank=True)
    configuration_verified_at = models.DateTimeField(null=True, blank=True)
    configuration_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="verified_municipality_configurations",
        on_delete=models.SET_NULL,
    )
    statistics_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "municipalities"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class NoticePublicationState(models.TextChoices):
    DRAFT = "draft", "Нацрт"
    PUBLISHED = "published", "Објавено"


class MunicipalityPublicNotice(models.Model):
    municipality = models.ForeignKey(
        Municipality,
        related_name="public_notices",
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=320)
    body = models.TextField()
    published_at = models.DateTimeField(null=True, blank=True)
    publication_state = models.CharField(
        max_length=16,
        choices=NoticePublicationState.choices,
        default=NoticePublicationState.DRAFT,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="municipality_public_notices",
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return f"{self.municipality.name} — {self.title}"

    def clean(self):
        super().clean()
        if self.publication_state == NoticePublicationState.PUBLISHED and not self.published_at:
            raise ValidationError({"published_at": "Објавеното известување мора да има датум."})


class Settlement(models.Model):
    municipality = models.ForeignKey(
        Municipality, related_name="settlements", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["municipality__name", "name"]
        unique_together = [("municipality", "name")]

    def __str__(self):
        return f"{self.name} ({self.municipality.name})"


class Department(models.Model):
    municipality = models.ForeignKey(
        Municipality, related_name="departments", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["municipality__name", "name"]
        unique_together = [("municipality", "name")]

    def __str__(self):
        return f"{self.name} ({self.municipality.name})"
