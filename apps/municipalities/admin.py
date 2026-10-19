import json

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.issues.models import DataRetentionPolicy
from apps.issues.retention import preview_retention
from apps.issues.tasks import run_attachment_retention
from apps.municipalities.configuration import (
    apply_configuration,
    validate_configuration_payload,
    validate_municipality_configuration,
    verify_stored_configuration,
)
from apps.municipalities.forms import (
    MunicipalityConfigurationImportForm,
    MunicipalityConfigurationVerifyForm,
)
from apps.municipalities.models import (
    Department,
    Municipality,
    MunicipalityPublicNotice,
    Settlement,
)


class DataRetentionPolicyInline(admin.StackedInline):
    model = DataRetentionPolicy
    extra = 0
    max_num = 1


@admin.action(description="Прегледај и примени политика за задржување")
def apply_data_retention(modeladmin, request, queryset):
    if not request.user.is_superuser:
        modeladmin.message_user(
            request,
            "Само superuser може да ја примени политиката.",
            messages.ERROR,
        )
        return None
    if request.POST.get("apply_retention") == "1":
        try:
            run_attachment_retention.delay(list(queryset.values_list("pk", flat=True)))
        except Exception:
            modeladmin.message_user(
                request,
                "Задачата не може да се стави во редица. Обиди се повторно.",
                messages.ERROR,
            )
        else:
            modeladmin.message_user(
                request,
                "Задачата за задржување е ставена во редица (до 100 прилози по пакет).",
                messages.SUCCESS,
            )
        return None
    return TemplateResponse(
        request,
        "admin/issues/retention_confirmation.html",
        {
            **modeladmin.admin_site.each_context(request),
            "title": "Преглед на политика за задржување",
            "municipalities": queryset,
            "previews": preview_retention(queryset),
        },
    )


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    change_list_template = "admin/municipalities/municipality/change_list.html"
    list_display = [
        "name",
        "slug",
        "is_active",
        "photo_uploads_enabled",
        "configuration_status",
        "configuration_verified_at",
    ]
    readonly_fields = [
        "configuration_status",
        "configuration_source",
        "configuration_verified_at",
        "configuration_verified_by",
    ]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]
    fieldsets = [
        (None, {"fields": ("name", "slug", "is_active")}),
        ("Функции", {"fields": ("photo_uploads_enabled",)}),
        (
            "Одобрено јавно брендирање",
            {
                "fields": ("public_accent_color", "official_coat_of_arms"),
                "description": "Не додавајте генерирани или неофицијални општински грбови.",
            },
        ),
        (
            "Конфигурација",
            {
                "fields": (
                    "configuration_status",
                    "configuration_source",
                    "configuration_verified_at",
                    "configuration_verified_by",
                )
            },
        ),
    ]
    inlines = [DataRetentionPolicyInline]
    actions = [apply_data_retention, "verify_configuration"]

    def get_urls(self):
        return [
            path(
                "import-configuration/",
                self.admin_site.admin_view(self.import_configuration_view),
                name="municipalities_municipality_import_configuration",
            )
        ] + super().get_urls()

    def import_configuration_view(self, request):
        preview = None
        errors = []
        if request.method == "POST" and request.POST.get("apply_preview") == "1":
            stored = request.session.get("municipality_configuration_preview")
            if not stored:
                self.message_user(
                    request,
                    "Прегледот истече. Прикачете ја датотеката повторно.",
                    messages.ERROR,
                )
            else:
                try:
                    municipality = apply_configuration(
                        stored["data"],
                        stored["source_reference"],
                        actor=request.user,
                        verify=stored["verify"],
                    )
                except ValueError as error:
                    self.message_user(request, str(error), messages.ERROR)
                else:
                    request.session.pop("municipality_configuration_preview", None)
                    self.message_user(
                        request,
                        f"Увезена е конфигурацијата за {municipality.name}.",
                        messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse("admin:municipalities_municipality_changelist")
                    )
            form = MunicipalityConfigurationImportForm()
        elif request.method == "POST":
            form = MunicipalityConfigurationImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    data = json.load(form.cleaned_data["configuration_file"])
                except (TypeError, ValueError, UnicodeDecodeError):
                    errors = ["Датотеката не е валиден UTF-8 JSON."]
                else:
                    errors = validate_configuration_payload(data)
                    if not errors:
                        preview = {
                            "name": data["name"],
                            "slug": data["slug"],
                            "settlement_count": len(data["settlements"]),
                            "department_count": len(data["departments"]),
                            "category_count": len(data["categories"]),
                            "source_reference": form.cleaned_data["source_reference"],
                            "verify": form.cleaned_data["verify"],
                        }
                        request.session["municipality_configuration_preview"] = {
                            "data": data,
                            "source_reference": form.cleaned_data["source_reference"],
                            "verify": form.cleaned_data["verify"],
                        }
        else:
            form = MunicipalityConfigurationImportForm()
        return TemplateResponse(
            request,
            "admin/municipalities/municipality/import_configuration.html",
            {
                **self.admin_site.each_context(request),
                "title": "Увоз на општинска конфигурација",
                "form": form,
                "preview": preview,
                "errors": errors,
            },
        )

    @admin.action(description="Верификувај избрана конфигурација")
    def verify_configuration(self, request, queryset):
        if request.POST.get("confirm_verification") == "1":
            form = MunicipalityConfigurationVerifyForm(request.POST)
            if form.is_valid():
                verified = 0
                for municipality in queryset:
                    try:
                        verify_stored_configuration(
                            municipality,
                            request.user,
                            form.cleaned_data["source_reference"],
                        )
                    except ValueError as error:
                        self.message_user(request, f"{municipality.name}: {error}", messages.ERROR)
                    else:
                        verified += 1
                if verified:
                    self.message_user(
                        request,
                        f"Верификувани конфигурации: {verified}.",
                        messages.SUCCESS,
                    )
                return None
        else:
            form = MunicipalityConfigurationVerifyForm()
        validation = [
            {"municipality": item, "errors": validate_municipality_configuration(item)}
            for item in queryset
        ]
        return TemplateResponse(
            request,
            "admin/municipalities/municipality/verify_configuration.html",
            {
                **self.admin_site.each_context(request),
                "title": "Верификација на општинска конфигурација",
                "municipalities": queryset,
                "validation": validation,
                "form": form,
            },
        )


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ["name", "municipality", "is_active"]
    list_filter = ["municipality", "is_active"]
    search_fields = ["name"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "municipality", "email", "is_active"]
    list_filter = ["municipality", "is_active"]
    search_fields = ["name", "email"]


@admin.register(MunicipalityPublicNotice)
class MunicipalityPublicNoticeAdmin(admin.ModelAdmin):
    list_display = ["title", "municipality", "publication_state", "published_at", "author"]
    list_filter = ["municipality", "publication_state"]
    search_fields = ["title", "summary", "body"]
    autocomplete_fields = ["author"]

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)
