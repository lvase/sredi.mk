from django.urls import path

from apps.issues import views_staff

urlpatterns = [
    path("", views_staff.staff_dashboard, name="staff_dashboard"),
    path("users/new/", views_staff.staff_create_user, name="staff_create_user"),
    path("issues/<int:pk>/", views_staff.staff_issue_detail, name="staff_issue_detail"),
    path("issues/<int:pk>/status/", views_staff.staff_change_status, name="staff_change_status"),
    path("issues/<int:pk>/update/", views_staff.staff_update_issue, name="staff_update_issue"),
    path("issues/<int:pk>/comments/", views_staff.staff_add_comment, name="staff_add_comment"),
]
