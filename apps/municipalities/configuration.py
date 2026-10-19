import json
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.issues.models import AuditLog, IssueCategory, ResponseTarget
from apps.municipalities.models import (
    ConfigurationStatus,
    Department,
    Municipality,
    Settlement,
)


def load_configuration(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_configuration_payload(data):
    errors = []
    for key in [
        "name",
        "slug",
        "settlements",
        "departments",
        "categories",
        "response_targets",
    ]:
        if key not in data:
            errors.append(f"Недостасува поле: {key}.")
    if errors:
        return errors
    department_names = {item.get("name", "").strip() for item in data["departments"]}
    if not data["settlements"]:
        errors.append("Потребно е најмалку едно населено место.")
    if not department_names or "" in department_names:
        errors.append("Секое одделение мора да има име.")
    if not data["categories"]:
        errors.append("Потребна е најмалку една категорија.")
    for category in data["categories"]:
        if not category.get("name", "").strip():
            errors.append("Секоја категорија мора да има име.")
        if category.get("default_department") not in department_names:
            errors.append(
                f"Категоријата {category.get('name', '-')} упатува на непостоечко одделение."
            )
    for field in ["review_hours", "resolution_hours"]:
        if (
            not isinstance(data["response_targets"].get(field), int)
            or data["response_targets"].get(field, 0) <= 0
        ):
            errors.append(
                f"Полето за рок на одговор {field} мора да биде позитивен цел број."
            )
    return errors


@transaction.atomic
def apply_configuration(data, source_reference, actor=None, verify=False):
    errors = validate_configuration_payload(data)
    if errors:
        raise ValueError(" ".join(errors))
    if verify and (not actor or not actor.is_superuser or not source_reference.strip()):
        raise ValueError("Верификацијата бара superuser и извор.")

    municipality, _ = Municipality.objects.get_or_create(
        slug=data["slug"],
        defaults={"name": data["name"]},
    )
    municipality.name = data["name"]
    municipality.configuration_source = source_reference
    if verify:
        municipality.configuration_status = ConfigurationStatus.VERIFIED
        municipality.configuration_verified_at = timezone.now()
        municipality.configuration_verified_by = actor
    else:
        municipality.configuration_status = ConfigurationStatus.UNVERIFIED
        municipality.configuration_verified_at = None
        municipality.configuration_verified_by = None
    municipality.save()

    ResponseTarget.objects.update_or_create(
        municipality=municipality,
        defaults=data["response_targets"],
    )

    settlement_names = {name.strip() for name in data["settlements"] if name.strip()}
    for name in settlement_names:
        Settlement.objects.update_or_create(
            municipality=municipality,
            name=name,
            defaults={"is_active": True},
        )
    Settlement.objects.filter(municipality=municipality).exclude(name__in=settlement_names).update(
        is_active=False
    )

    department_names = {item["name"].strip() for item in data["departments"]}
    department_map = {}
    for item in data["departments"]:
        department, _ = Department.objects.update_or_create(
            municipality=municipality,
            name=item["name"].strip(),
            defaults={"email": item.get("email", ""), "is_active": True},
        )
        department_map[department.name] = department
    Department.objects.filter(municipality=municipality).exclude(name__in=department_names).update(
        is_active=False
    )

    category_names = {item["name"].strip() for item in data["categories"]}
    for item in data["categories"]:
        category, _ = IssueCategory.objects.update_or_create(
            municipality=municipality,
            name=item["name"].strip(),
            defaults={
                "default_department": department_map[item["default_department"]],
                "description": item.get("description", ""),
                "is_active": True,
            },
        )
    IssueCategory.objects.filter(municipality=municipality).exclude(name__in=category_names).update(
        is_active=False
    )

    AuditLog.objects.create(
        municipality=municipality,
        actor=actor,
        action="municipality_configuration_imported",
        object_type="Municipality",
        object_id=str(municipality.pk),
        metadata={
            "source_reference": source_reference,
            "verified": verify,
            "settlement_count": len(settlement_names),
            "department_count": len(department_names),
            "category_count": len(category_names),
        },
    )
    return municipality


def validate_municipality_configuration(municipality):
    errors = []
    if not municipality.settlements.filter(is_active=True).exists():
        errors.append("Нема активно населено место.")
    if not municipality.departments.filter(is_active=True).exists():
        errors.append("Нема активно одделение.")
    categories = IssueCategory.objects.filter(municipality=municipality, is_active=True)
    if not categories.exists():
        errors.append("Нема активна категорија.")
    for category in categories.select_related("default_department"):
        if not category.default_department:
            errors.append(f"Категоријата {category.name} нема основно одделение.")
        elif category.default_department.municipality_id != municipality.id:
            errors.append(f"Категоријата {category.name} упатува на друга општина.")
    if not ResponseTarget.objects.filter(municipality=municipality).exists():
        errors.append("Општината нема поставени рокови за одговор.")
    profiles = StaffProfile.objects.filter(municipality=municipality).select_related(
        "department"
    )
    for profile in profiles:
        if profile.department_id and profile.department.municipality_id != municipality.id:
            errors.append(f"Корисникот {profile.user_id} има одделение од друга општина.")
    return errors


@transaction.atomic
def verify_stored_configuration(municipality, actor, source_reference):
    if not actor.is_superuser or not source_reference.strip():
        raise ValueError("Верификацијата бара superuser и извор.")
    errors = validate_municipality_configuration(municipality)
    if errors:
        raise ValueError(" ".join(errors))
    municipality.configuration_status = ConfigurationStatus.VERIFIED
    municipality.configuration_source = source_reference.strip()
    municipality.configuration_verified_at = timezone.now()
    municipality.configuration_verified_by = actor
    municipality.save(
        update_fields=[
            "configuration_status",
            "configuration_source",
            "configuration_verified_at",
            "configuration_verified_by",
            "updated_at",
        ]
    )
    AuditLog.objects.create(
        municipality=municipality,
        actor=actor,
        action="municipality_configuration_verified",
        object_type="Municipality",
        object_id=str(municipality.pk),
        metadata={"source_reference": source_reference.strip()},
    )
