from django.apps import AppConfig


class IssuesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.issues"

    def ready(self):
        from apps.issues import signals  # noqa: F401
