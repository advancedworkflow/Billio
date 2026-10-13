"""
Serializers for payments app.
"""
from rest_framework import serializers
from .models import Payment, PaymentMethod, Transaction


class PaymentMethodSerializer(serializers.ModelSerializer):
    """Serializer for PaymentMethod model."""

    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'organization', 'name', 'method_type', 'bank_name',
            'account_holder', 'iban', 'bic', 'api_key', 'webhook_secret',
            'is_default', 'is_active', 'processing_fee', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model."""
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    client_name = serializers.CharField(source='invoice.client.name', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'transaction_id', 'invoice', 'invoice_number', 'client_name',
            'payment_method', 'amount', 'currency', 'status', 'provider',
            'provider_payment_id', 'processing_fee', 'payment_date',
            'processed_at', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'transaction_id', 'created_at', 'updated_at', 'processed_at'
        ]


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for Transaction model."""

    class Meta:
        model = Transaction
        fields = [
            'id', 'payment', 'transaction_type', 'amount', 'description',
            'provider_reference', 'success', 'error_message', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


