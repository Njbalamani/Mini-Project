"""Reusable API permissions enforcing object-level ownership."""
from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Object read/write is restricted to the owner field."""

    owner_field = "owner"

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, self.owner_field, None)
        if hasattr(owner, "pk"):
            owner = owner.pk
        return owner == request.user.pk or request.user.is_staff


class IsOwnerThroughWorkflow(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.workflow.owner_id == request.user.pk or request.user.is_staff


class IsOwnerThroughTask(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.task.owner_id == request.user.pk or request.user.is_staff
