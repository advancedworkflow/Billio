"""
Serializers for templates_app.
"""
from rest_framework import serializers
from .models import InvoiceTemplate


class InvoiceTemplateSerializer(serializers.ModelSerializer):
    """Serializer for InvoiceTemplate model."""

    class Meta:
        model = InvoiceTemplate
        fields = [
            'id', 'organization', 'name',
            'html_structure', 'css_styles',
            'layout_config', 'style_config',
            'is_default', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
