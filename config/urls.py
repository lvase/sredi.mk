from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.permissions import authentication_complete, frontend_login
from config import health


def superuser_admin_permission(request):
    return (
        request.user.is_superuser
        and authentication_complete(request.user)
    )


admin.site.has_permission = superuser_admin_permission
admin.site.login = frontend_login

urlpatterns = [
    path("health/live/", health.live, name="health_live"),
    path("health/ready/", health.ready, name="health_ready"),
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    path(
        "login/",
        frontend_login,
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.dashboard.urls")),
    path("sredi/", RedirectView.as_view(pattern_name="home", permanent=False), name="sredi_legacy"),
    path("staff/", include("apps.issues.urls_staff")),
    path("<slug:municipality_slug>/", include("apps.issues.urls_public")),
]
