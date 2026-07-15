from django.urls import path

from apps.issues import views_public

urlpatterns = [
    path("", views_public.sredi_home, name="sredi_home"),
    path("statistika/", views_public.public_dashboard, name="public_dashboard"),
    path("dashboard/", views_public.public_dashboard, name="public_dashboard_legacy"),
    path("prijavi/", views_public.submit_issue, name="submit_issue"),
    path("sledi/", views_public.track_issue, name="track_issue"),
]
