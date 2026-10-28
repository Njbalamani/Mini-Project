"""Signal handlers creating the supporting rows every user needs."""
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserPreference, UserProfile
from .services import record_login


@receiver(post_save, sender=User)
def ensure_account_support_rows(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
        UserPreference.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    if user and user.is_email_verified is False and user.is_superuser:
        pass
    record_login(user.email, request, "success", user=user)
