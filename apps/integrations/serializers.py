"""
Serializers for integrations app.
"""
from rest_framework import serializers

from .models import Connector, ConnectionInstance, WebhookLog


class ConnectorSerializer(serializers.ModelSerializer):
    """Serializer for Connector model."""

    class Meta:
        model = Connector
        fields = [
            'id', 'key', 'name', 'category', 'description', 'icon',
            'is_active', 'requires_oauth', 'order'
        ]
        read_only_fields = ['id']


class ConnectionInstanceSerializer(serializers.ModelSerializer):
    """
    Serializer for ConnectionInstance model.
    La configuration contient des secrets (jetons, mots de passe) : elle n'est exposée que
    masquée et ne se modifie pas par l'API (page Intégrations, avec contrôle des droits).
    """
    connector_key = serializers.CharField(source='connector.key', read_only=True)
    connector_name = serializers.CharField(source='connector.name', read_only=True)
    config = serializers.SerializerMethodField()

    def get_config(self, obj):
        from .providers import mask_config
        return mask_config(obj.connector.key, obj.config)

    class Meta:
        model = ConnectionInstance
        fields = [
            'id', 'organization', 'connector', 'connector_key', 'connector_name',
            'status', 'config', 'connected_by', 'connected_at', 'disconnected_at',
            'last_error', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'status', 'config', 'connected_by', 'connected_at', 'disconnected_at', 'last_error', 'created_at', 'updated_at'
        ]


class WebhookLogSerializer(serializers.ModelSerializer):
    """Serializer for WebhookLog model."""

    class Meta:
        model = WebhookLog
        fields = [
            'id', 'connection_instance', 'event_type', 'payload',
            'success', 'error_message', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
