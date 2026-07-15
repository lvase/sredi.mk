from django.urls import path

from apps.dashboard.views import home, privacy_policy, terms_of_use

urlpatterns = [
    path("", home, name="home"),
    path("privatnost/", privacy_policy, name="privacy_policy"),
    path("uslovi/", terms_of_use, name="terms_of_use"),
]
