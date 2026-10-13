"""
Serializers for dashboard app.
"""
from rest_framework import serializers
from .models import DashboardMetric, Report, Notification


class DashboardMetricSerializer(serializers.ModelSerializer):
    """Serializer for DashboardMetric model."""

    class Meta:
        model = DashboardMetric
        fields = [
            'id', 'organization', 'metric_type', 'value', 'period', 'calculated_at'
        ]
        read_only_fields = ['id', 'calculated_at']


class ReportSerializer(serializers.ModelSerializer):
    """Serializer for Report model."""

    class Meta:
        model = Report
        fields = [
            'id', 'organization', 'report_type', 'title', 'description',
            'start_date', 'end_date', 'status', 'file', 'parameters',
            'created_by', 'created_at', 'completed_at'
        ]
        read_only_fields = ['id', 'created_at', 'completed_at']


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'notification_type', 'title', 'message', 'priority',
            'related_invoice', 'related_payment', 'is_read', 'is_archived',
            'actions', 'created_at', 'read_at'
        ]
        read_only_fields = ['id', 'created_at', 'read_at']


