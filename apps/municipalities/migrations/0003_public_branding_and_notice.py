import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.municipalities.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("municipalities", "0002_configuration_verification"),
    ]

    operations = [
        migrations.AddField(
            model_name="municipality",
            name="official_coat_of_arms",
            field=models.ImageField(
                blank=True,
                help_text="Поставете само официјално доставен и одобрен општински грб.",
                upload_to=apps.municipalities.models.municipality_crest_path,
            ),
        ),
        migrations.AddField(
            model_name="municipality",
            name="public_accent_color",
            field=models.CharField(
                blank=True,
                help_text="Одобрена јавна акцентна боја во формат #RRGGBB.",
                max_length=7,
                validators=[apps.municipalities.models.validate_hex_color],
            ),
        ),
        migrations.CreateModel(
            name="MunicipalityPublicNotice",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("title", models.CharField(max_length=180)),
                ("summary", models.CharField(max_length=320)),
                ("body", models.TextField()),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                (
                    "publication_state",
                    models.CharField(
                        choices=[("draft", "Нацрт"), ("published", "Објавено")],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "author",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="municipality_public_notices",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "municipality",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="public_notices",
                        to="municipalities.municipality",
                    ),
                ),
            ],
            options={"ordering": ["-published_at", "-created_at"]},
        ),
    ]
