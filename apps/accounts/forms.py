"""
Forms for accounts app.
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import UserProfile

User = get_user_model()


class RegisterForm(UserCreationForm):
    """Form for user registration."""
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'Votre prénom'
        })
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'input-focus block w-full px-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'Votre nom'
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'votre@email.com'
        })
    )

    company_name = forms.CharField(max_length=200, required=False)
    trade = forms.ChoiceField(required=True, error_messages={'required': 'Choisissez votre métier.'})

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organizations.trade_packs import TRADE_CHOICES
        self.fields['trade'].choices = TRADE_CHOICES
        self.fields['password1'].widget.attrs.update({
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'Minimum 8 caractères'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'Répétez votre mot de passe'
        })

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.username:
            base = (self.cleaned_data.get('email') or '').split('@')[0] or 'user'
            username = base
            suffix = 1
            while User.objects.filter(username=username).exclude(pk=user.pk).exists():
                suffix += 1
                username = f"{base}{suffix}"
            user.username = username
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """Form for user login."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'votre@email.com'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'input-focus block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white/50 backdrop-blur-sm',
            'placeholder': 'Votre mot de passe'
        })
    )

    class Meta:
        model = User
        fields = ('email', 'password')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove the default username field and use email instead
        del self.fields['username']
        self.fields['email'].required = True
