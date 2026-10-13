"""
Serializers for invoices app.
"""
from rest_framework import serializers
from .models import (
    Invoice, Quote, Tax, InvoiceItem, QuoteItem, QuotePaymentMilestone, QuoteAttachment,
)


class TaxSerializer(serializers.ModelSerializer):
    """Serializer for Tax model."""

    class Meta:
        model = Tax
        fields = [
            'id', 'organization', 'name', 'rate', 'is_default', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class InvoiceItemSerializer(serializers.ModelSerializer):
    """Serializer for InvoiceItem model."""

    class Meta:
        model = InvoiceItem
        fields = [
            'id', 'invoice', 'name', 'description', 'quantity', 'unit_price',
            'unit', 'tax_rate', 'total', 'order'
        ]
        read_only_fields = ['id', 'total']


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer for Invoice model."""
    items = InvoiceItemSerializer(many=True, read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'organization', 'organization_name', 'client',
            'client_name', 'title', 'description', 'issue_date', 'due_date',
            'subtotal', 'tax_amount', 'discount_amount', 'total_amount',
            'currency', 'status', 'payment_terms', 'notes', 'footer',
            'pdf_file', 'items', 'created_by', 'created_at', 'updated_at',
            'sent_at', 'paid_at'
        ]
        read_only_fields = [
            'id', 'invoice_number', 'created_at', 'updated_at', 'sent_at', 'paid_at'
        ]


class QuoteItemSerializer(serializers.ModelSerializer):
    """Serializer for QuoteItem model."""

    class Meta:
        model = QuoteItem
        fields = [
            'id', 'quote', 'product', 'name', 'description', 'quantity', 'unit_price',
            'unit', 'discount_percent', 'tax_rate', 'total', 'order'
        ]
        read_only_fields = ['id', 'total']


class QuotePaymentMilestoneSerializer(serializers.ModelSerializer):
    """Serializer for QuotePaymentMilestone model."""

    class Meta:
        model = QuotePaymentMilestone
        fields = [
            'id', 'quote', 'label', 'due_date', 'percentage', 'amount', 'status',
            'order', 'generated_invoice'
        ]
        read_only_fields = ['id', 'generated_invoice']


class QuoteAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for QuoteAttachment model."""

    class Meta:
        model = QuoteAttachment
        fields = ['id', 'quote', 'file', 'name', 'uploaded_by', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_by', 'uploaded_at']


class QuoteSerializer(serializers.ModelSerializer):
    """Serializer for Quote model."""
    items = QuoteItemSerializer(many=True, read_only=True)
    payment_milestones = QuotePaymentMilestoneSerializer(many=True, read_only=True)
    attachments = QuoteAttachmentSerializer(many=True, read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Quote
        fields = [
            'id', 'quote_number', 'organization', 'organization_name', 'client',
            'client_name', 'template', 'title', 'description',
            'project_reference', 'project_name', 'project_location',
            'project_start_date', 'project_delivery_date',
            'issue_date', 'expiry_date',
            'subtotal', 'tax_amount', 'discount_amount', 'total_amount',
            'currency', 'status', 'notes', 'payment_terms', 'delivery_terms',
            'terms_and_conditions', 'footer', 'pdf_file',
            'items', 'payment_milestones', 'attachments',
            'sent_at', 'viewed_at', 'accepted_at', 'accepted_by_name', 'accepted_by_email',
            'rejected_at', 'rejection_reason',
            'is_recurring', 'recurrence_interval', 'recurrence_count', 'recurrence_start_date',
            'converted_to_invoice',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'quote_number', 'created_at', 'updated_at', 'sent_at', 'viewed_at',
            'accepted_at', 'rejected_at', 'converted_to_invoice',
        ]


class PublicQuoteSerializer(serializers.ModelSerializer):
    """Serializer for public quote view (limited/safe fields)."""
    items = QuoteItemSerializer(many=True, read_only=True)
    payment_milestones = QuotePaymentMilestoneSerializer(many=True, read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)

    class Meta:
        model = Quote
        fields = [
            'id', 'quote_number', 'organization_name', 'client_name', 'title', 'description',
            'project_reference', 'project_name', 'project_location',
            'project_start_date', 'project_delivery_date',
            'issue_date', 'expiry_date', 'subtotal', 'tax_amount',
            'discount_amount', 'total_amount', 'currency', 'status',
            'payment_terms', 'delivery_terms', 'terms_and_conditions', 'footer',
            'items', 'payment_milestones', 'pdf_file',
        ]


class PublicInvoiceSerializer(serializers.ModelSerializer):
    """Serializer for public invoice view (limited fields)."""
    items = InvoiceItemSerializer(many=True, read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'organization_name', 'client_name', 'title',
            'description', 'issue_date', 'due_date', 'subtotal', 'tax_amount',
            'discount_amount', 'total_amount', 'currency', 'status',
            'payment_terms', 'notes', 'footer', 'items', 'pdf_file'
        ]


