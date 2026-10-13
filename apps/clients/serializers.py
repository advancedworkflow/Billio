"""
Serializers for clients app.
"""
from rest_framework import serializers
from .models import Client, ClientContact


class ClientSerializer(serializers.ModelSerializer):
    """Serializer for Client model."""
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Client
        fields = [
            'id', 'organization', 'organization_name', 'name', 'email', 'phone',
            'address', 'city', 'postal_code', 'country', 'company_name',
            'tax_id', 'registration_number', 'contact_person', 'contact_phone',
            'notes', 'payment_terms', 'is_active', 'total_invoiced',
            'total_paid', 'outstanding_balance', 'created_at'
        ]
        read_only_fields = [
            'id', 'created_at', 'total_invoiced', 'total_paid', 'outstanding_balance'
        ]


class ClientContactSerializer(serializers.ModelSerializer):
    """Serializer for ClientContact model."""
    client_name = serializers.CharField(source='client.name', read_only=True)

    class Meta:
        model = ClientContact
        fields = [
            'id', 'client', 'client_name', 'name', 'email', 'phone',
            'position', 'is_primary', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


