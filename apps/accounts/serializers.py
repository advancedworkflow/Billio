"""
Serializers for accounts app.
"""
from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from .models import User, UserProfile


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name', 'full_name',
            'role', 'phone', 'avatar', 'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.email


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for UserProfile model."""
    user = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'company_name', 'address', 'city', 'postal_code',
            'country', 'tax_id', 'business_type', 'industry',
            'invoice_prefix', 'default_payment_terms'
        ]


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            'email', 'username', 'first_name', 'last_name',
            'password', 'password_confirm', 'role'
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError(
                {"password_confirm": _("Password fields didn't match.")}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(
                request=self.context.get('request'),
                username=email,  # Django uses username for auth, but we use email
                password=password
            )

            if not user:
                # Try with email as username
                try:
                    user_obj = User.objects.get(email=email)
                    user = authenticate(
                        username=user_obj.username,
                        password=password
                    )
                except User.DoesNotExist:
                    pass

            if not user:
                raise serializers.ValidationError(
                    _("Unable to log in with provided credentials.")
                )
        else:
            raise serializers.ValidationError(
                _("Must include 'email' and 'password'.")
            )

        attrs['user'] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password."""
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {"new_password_confirm": _("Password fields didn't match.")}
            )
        return attrs


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile."""

    class Meta:
        model = UserProfile
        fields = [
            'company_name', 'address', 'city', 'postal_code', 'country',
            'tax_id', 'business_type', 'industry', 'default_currency',
            'language', 'timezone', 'invoice_prefix', 'default_payment_terms'
        ]


