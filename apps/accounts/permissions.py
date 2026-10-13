"""
Custom permissions for accounts app.
"""
from rest_framework import permissions


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or admins to access it.
    """

    def has_object_permission(self, request, view, obj):
        # Admin users can do anything
        if request.user and request.user.is_staff:
            return True

        # Check if user owns the object
        return obj.user == request.user


class IsOrganizationMember(permissions.BasePermission):
    """
    Permission to check if user is a member of the organization.
    """

    def has_object_permission(self, request, view, obj):
        # Admin users can do anything
        if request.user and request.user.is_staff:
            return True

        # Check if user is a member of the organization
        if hasattr(obj, 'organization'):
            return obj.organization.members.filter(user=request.user).exists()

        return False


class CanManageOrganization(permissions.BasePermission):
    """
    Permission to check if user can manage the organization.
    """

    def has_object_permission(self, request, view, obj):
        # Admin users can do anything
        if request.user and request.user.is_staff:
            return True

        # Check if user can manage the organization
        if hasattr(obj, 'organization'):
            membership = obj.organization.members.filter(user=request.user).first()
            if membership:
                return membership.role in ['owner', 'admin']

        return False


