from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.forms import BootstrapAuthenticationForm
from config import health


def superuser_admin_permission(request):
    return (
        request.user.is_active
        and request.user.is_superuser
        and callable(getattr(request.user, "is_verified", None))
        and request.user.is_verified()
    )


admin.site.has_permission = superuser_admin_permission

urlpatterns = [
    path("health/live/", health.live, name="health_live"),
    path("health/ready/", health.ready, name="health_ready"),
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    path(
        "login/",
        auth_views.LoginView.as_view(
            authentication_form=BootstrapAuthenticationForm,
            template_name="registration/login.html",
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.dashboard.urls")),
    path("sredi/", RedirectView.as_view(pattern_name="home", permanent=False), name="sredi_legacy"),
    path("staff/", include("apps.issues.urls_staff")),
    path("<slug:municipality_slug>/", include("apps.issues.urls_public")),
]
