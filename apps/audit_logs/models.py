"""Audit trail models.

These records are append-only through normal application interfaces. They are
NOT cryptographically tamper-evident; treat this as an application audit log,
not a tamper-proof ledger.
"""
from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    OUTCOME_CHOICES = [
        ("success", "Success"),
        ("failure", "Failure"),
        ("denied", "Denied"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_logs",
    )
    action = models.CharField(max_length=120, db_index=True)
    resource_type = models.CharField(max_length=80, blank=True)
    resource_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, default="success")
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["actor", "-timestamp"]),
            models.Index(fields=["action", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_id} ({self.outcome})"
