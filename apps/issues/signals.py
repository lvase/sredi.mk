from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import StaffProfile
from apps.issues.models import Issue, IssueCategory
from apps.municipalities.models import Department, Municipality


def _bump_choices_version():
    try:
        if not cache.add("staff-choices:version", 2, timeout=None):
            cache.incr("staff-choices:version")
    except Exception:
        pass


def _increment_statistics_version(municipality_id):
    if municipality_id:
        Municipality.objects.filter(pk=municipality_id).update(
            statistics_version=F("statistics_version") + 1
        )


@receiver(post_save, sender=Issue)
def issue_saved(sender, instance, **kwargs):
    transaction.on_commit(lambda: _increment_statistics_version(instance.municipality_id))
    transaction.on_commit(_bump_choices_version)


@receiver(post_delete, sender=Issue)
def issue_deleted(sender, instance, **kwargs):
    transaction.on_commit(lambda: _increment_statistics_version(instance.municipality_id))
    transaction.on_commit(_bump_choices_version)


@receiver(post_save, sender=StaffProfile)
@receiver(post_delete, sender=StaffProfile)
@receiver(post_save, sender=Department)
@receiver(post_delete, sender=Department)
@receiver(post_save, sender=Municipality)
@receiver(post_delete, sender=Municipality)
@receiver(post_save, sender=IssueCategory)
@receiver(post_delete, sender=IssueCategory)
@receiver(post_save, sender=get_user_model())
@receiver(post_delete, sender=get_user_model())
@receiver(post_save, sender=TOTPDevice)
@receiver(post_delete, sender=TOTPDevice)
def staff_choices_configuration_changed(sender, instance, **kwargs):
    transaction.on_commit(_bump_choices_version)
