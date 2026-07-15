from django.conf import settings
from django.shortcuts import render

from apps.municipalities.models import Municipality


def home(request):
    municipalities = Municipality.objects.filter(is_active=True).order_by("name")
    return render(request, "dashboard/home.html", {"municipalities": municipalities})


def legal_context():
    return {
        "platform_operator_name": settings.PLATFORM_OPERATOR_NAME,
        "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
    }


def privacy_policy(request):
    return render(request, "dashboard/privacy.html", legal_context())


def terms_of_use(request):
    return render(request, "dashboard/terms.html", legal_context())
