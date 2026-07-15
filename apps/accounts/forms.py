from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from apps.accounts.models import StaffProfile, StaffRole
from apps.municipalities.models import Department, Municipality


class BootstrapAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class StaffUserCreateForm(forms.Form):
    username = forms.CharField(label="Корисничко име", max_length=150)
    email = forms.EmailField(label="Е-пошта", required=False)
    password = forms.CharField(label="Привремена лозинка", widget=forms.PasswordInput)
    municipality = forms.ModelChoiceField(
        label="Општина",
        queryset=Municipality.objects.filter(is_active=True),
    )
    department = forms.ModelChoiceField(
        label="Одделение",
        queryset=Department.objects.none(),
        required=False,
    )
    role = forms.ChoiceField(label="Улога", choices=StaffRole.choices)

    def __init__(self, *args, municipality=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"
        selected_municipality = municipality or self.data.get("municipality")
        if selected_municipality:
            self.fields["department"].queryset = Department.objects.filter(
                municipality_id=selected_municipality,
                is_active=True,
            )

    def clean_username(self):
        username = self.cleaned_data["username"]
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError("Веќе постои корисник со ова корисничко име.")
        return username

    def save(self):
        user = get_user_model().objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
        )
        StaffProfile.objects.create(
            user=user,
            municipality=self.cleaned_data["municipality"],
            department=self.cleaned_data["department"],
            role=self.cleaned_data["role"],
            must_change_password=True,
        )
        return user
