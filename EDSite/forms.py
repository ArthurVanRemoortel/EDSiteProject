from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.forms import ModelForm
from django.forms.widgets import PasswordInput, NumberInput
from django.core.validators import MaxValueValidator, MinValueValidator

YES_NO_CHOICES = [("yes", "Yes"), ("no", "No")]

LANDING_PAD_CHOICES = [
    ("S", "S"),
    ("M", "M"),
    ("L", "L"),
]


class ChoiceFieldNoValidation(forms.ChoiceField):
    def validate(self, value):
        pass


class CommodityForm(forms.Form):
    reference_system = ChoiceFieldNoValidation(
        widget=forms.Select(attrs={"class": "input", "id": "referenceInput"}),
        required=False,
    )
    buy_or_sell = forms.ChoiceField(
        required=False,
        choices=[("buy", "Buy"), ("sell", "Sell")],
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
            attrs={"class": "input", "placeholder": "0"},
        ),
        required=False,
    )


class SystemsForm(forms.Form):
    search = forms.CharField(
        widget=forms.TextInput(attrs={"class": "input", "id": "searchInput"}),
        required=False,
    )
    reference_system = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "input", "id": "referenceInput"}),
        required=False,
    )
    only_populated = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "input"}),
        required=False,
        choices=YES_NO_CHOICES,
    )


class StationsForm(forms.Form):
    search = forms.CharField(
        widget=forms.TextInput(attrs={"class": "input", "id": "stationSearchInput"}),
        required=False,
    )
    reference_system = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "input", "id": "referenceInput"}),
        required=False,
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
    star_distance = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input"},
        ),
        required=False,
    )
    system_distance = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input"},
        ),
        required=False,
    )


class CarrierMissionForm(forms.Form):
    carrier_name = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input", "id": "carrierNameField"},
        ),
        required=True,
    )
    carrier_code = ChoiceFieldNoValidation(
        widget=forms.Select(
            attrs={"class": "input", "id": "carrierCodeField", "data-width": "100%"},
        ),
        required=True,
    )
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input", "readonly": True, "id": "usernameField"},
        ),
        required=True,
    )
    mission_type = forms.ChoiceField(
        required=True,
        choices=[("L", "Loading"), ("U", "Unloading")],
        widget=forms.Select(
            attrs={"id": "missionTypeField"},
        ),
    )
    commodity = ChoiceFieldNoValidation(
        widget=forms.Select(
            attrs={"class": "input", "id": "commodityField", "data-width": "100%"},
        ),
        required=True,
    )
    station = ChoiceFieldNoValidation(
        widget=forms.Select(
            attrs={"class": "input", "id": "stationField", "data-width": "100%"},
        ),
        required=True,
    )
    worker_profit = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input", "id": "workerProfitField"},
        ),
        required=True,
    )
    units = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "input", "id": "unitsField"},
        ),
        required=True,
    )


class SignupForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": "input"}),
        required=True,
    )
    email = forms.EmailField(
        widget=forms.TextInput(attrs={"class": "input"}),
        required=True,
    )
    password1 = forms.CharField(
        widget=PasswordInput(attrs={"class": "input"}),
        required=True,
    )
    password2 = forms.CharField(
        widget=PasswordInput(attrs={"class": "input"}),
        required=True,
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super(UserCreationForm, self).save(commit=False)
        user.email = self.cleaned_data["email"]
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    # email = forms.EmailField(
    #     widget=forms.TextInput(
    #         attrs={'class': 'input'}
    #     ),
    #     required=False,
    # )
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": "input"}),
        # required=True,
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=PasswordInput(
            attrs={"class": "input", "autocomplete": "current-password"}
        ),
        # required=True,
    )

    class Meta:
        model = User
        fields = ("username", "password")
