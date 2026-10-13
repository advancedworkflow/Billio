"""
Serializers for organizations app.
"""
from rest_framework import serializers
from .models import Organization, OrganizationMember


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for Organization model."""
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'type', 'email', 'phone', 'website', 'address',
            'city', 'postal_code', 'country', 'tax_id', 'registration_number',
            'logo', 'primary_color', 'secondary_color', 'default_currency',
            'default_language', 'timezone', 'invoice_prefix', 'next_invoice_number',
            'default_payment_terms', 'preferred_payment_method',
            'bank_name', 'iban', 'bic_swift',
            'payment_instructions', 'is_active', 'member_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'member_count']

    def get_member_count(self, obj):
        return obj.members.count()


class OrganizationMemberSerializer(serializers.ModelSerializer):
    """Serializer for OrganizationMember model."""
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMember
        fields = [
            'id', 'organization', 'user', 'user_email', 'user_name', 'role',
            'can_create_invoices', 'can_edit_organization', 'can_manage_members',
            'can_view_financials', 'invited_at', 'joined_at'
        ]
        read_only_fields = ['id', 'invited_at', 'joined_at', 'user_email', 'user_name']

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email


