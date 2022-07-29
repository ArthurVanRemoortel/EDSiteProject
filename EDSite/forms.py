from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.forms import ModelForm
from django.forms.widgets import NumberInput, PasswordInput
from django.core.validators import MaxValueValidator, MinValueValidator

YES_NO_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No')
]

LANDING_PAD_CHOICES = [
    ('S', 'S'),
    ('M', 'M'),
    ('L', 'L'),
]


class CommodityForm(forms.Form):

    reference_system = forms.CharField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=False,
    )

    buy_or_sell = forms.ChoiceField(
        required=False,
        choices=[('buy', 'Buy'), ('sell', 'Sell')],
    )

    include_odyssey = forms.ChoiceField(
        widget=forms.Select(
            attrs={
                # 'style': 'width: 100%'
            }
        ),
        required=False,
        choices=YES_NO_CHOICES,
    )

    include_fleet_carriers = forms.ChoiceField(
        required=False,
        choices=YES_NO_CHOICES,
    )

    include_planetary = forms.ChoiceField(
        required=False,
        choices=YES_NO_CHOICES,
    )

    landing_pad_size = forms.ChoiceField(
        required=False,
        choices=LANDING_PAD_CHOICES,
    )

    minimum_units = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'class': 'input',
                'placeholder': '0'
            },
        ),
        required=False,
    )


class SignupForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    email = forms.EmailField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    password1 = forms.CharField(
        widget=PasswordInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    password2 = forms.CharField(
        widget=PasswordInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super(SignupForm, self).save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class SignupForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    email = forms.EmailField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    password1 = forms.CharField(
        widget=PasswordInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    password2 = forms.CharField(
        widget=PasswordInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super(UserCreationForm, self).save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    email = forms.EmailField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=False,
    )
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={'class': 'input'}
        ),
        required=True,
    )
    password = forms.CharField(
        widget=PasswordInput(
            attrs={'class': 'input', "autocomplete": "current-password"}
        ),
        required=True,
    )

    class Meta:
        model = User
        fields = ("email", "username", "password")
