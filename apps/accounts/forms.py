"""
Forms for accounts app.
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import get_user_model
from .models import UserProfile

User = get_user_model()


class RegisterForm(forms.Form):
    """
    Inscription : nom, email, mot de passe, pays, téléphone, activité.
    Le nom de l'entreprise reprend le nom saisi ; il se change ensuite dans Paramètres.
    """
    name = forms.CharField(max_length=60, error_messages={'required': 'Indiquez votre nom.'})
    email = forms.EmailField(error_messages={'required': 'Indiquez votre email.', 'invalid': 'Cette adresse email ne semble pas valide.'})
    password = forms.CharField(strip=False, error_messages={'required': 'Choisissez un mot de passe.'})
    country = forms.ChoiceField(error_messages={'required': 'Choisissez votre pays.'})
    phone = forms.CharField(max_length=30, error_messages={'required': 'Indiquez votre numéro de téléphone.'})
    trade = forms.ChoiceField(error_messages={'required': 'Choisissez votre activité.'})
    accept_terms = forms.BooleanField(error_messages={
        'required': "Cochez la case pour accepter les conditions d'utilisation."})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organizations.trade_packs import TRADE_CHOICES
        self.fields['trade'].choices = TRADE_CHOICES
        from .countries import COUNTRIES
        self.fields['country'].choices = [(code, name) for code, name, _ in COUNTRIES]

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Un compte existe déjà avec cet email. Connectez-vous ou utilisez « Mot de passe oublié ».')
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('phone') and cleaned.get('country'):
            from .countries import normalize_phone
            phone = normalize_phone(cleaned['phone'], cleaned['country'])
            if phone:
                cleaned['phone'] = phone
            else:
                self.add_error('phone', "Ce numéro de téléphone ne semble pas valide.")
        password = cleaned.get('password')
        if password:
            from django.contrib.auth.password_validation import validate_password
            first, _, last = (cleaned.get('name') or '').strip().partition(' ')
            try:
                validate_password(password, User(email=cleaned.get('email', ''), first_name=first, last_name=last))
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned

    def save(self):
        first, _, last = self.cleaned_data['name'].strip().partition(' ')
        email = self.cleaned_data['email']
        base = email.split('@')[0] or 'user'
        username, suffix = base, 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base}{suffix}"
        return User.objects.create_user(username=username, email=email, password=self.cleaned_data['password'],
                                         first_name=first[:30], last_name=last.strip()[:30],
                                         phone=self.cleaned_data['phone'])


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
