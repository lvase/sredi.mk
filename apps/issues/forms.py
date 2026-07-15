from django import forms
from django.contrib.auth import get_user_model

from apps.issues.models import Issue, IssueAttachment, IssueComment


def apply_bootstrap_widgets(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "form-check-input"
        elif isinstance(widget, forms.Select):
            widget.attrs["class"] = "form-select"
        elif isinstance(widget, forms.HiddenInput):
            continue
        else:
            widget.attrs["class"] = "form-control"


class CitizenIssueForm(forms.ModelForm):
    consent = forms.BooleanField(
        label="Се согласувам мојата пријава да биде обработена од општината.",
        required=True,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    send_receipt = forms.BooleanField(required=False)

    class Meta:
        model = Issue
        fields = [
            "settlement",
            "category",
            "title",
            "description",
            "location_text",
            "citizen_name",
            "citizen_email",
            "citizen_phone",
        ]
        labels = {
            "settlement": "Населено место",
            "category": "Категорија",
            "title": "Краток наслов",
            "description": "Опис на проблемот",
            "location_text": "Локација / адреса / насока",
            "citizen_name": "Име и презиме (незадолжително)",
            "citizen_email": "Е-пошта (незадолжително)",
            "citizen_phone": "Телефон (незадолжително)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Пр. Не работи улично светло"}),
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Опиши што се случува, колку долго трае проблемот и дали има ризик за граѓани.",
                }
            ),
            "location_text": forms.TextInput(attrs={"placeholder": "Пр. улица, маало, близу објект..."}),
            "citizen_name": forms.TextInput(attrs={"placeholder": "Име и презиме"}),
            "citizen_email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
            "citizen_phone": forms.TextInput(attrs={"placeholder": "07x xxx xxx"}),
        }

    def __init__(self, *args, municipality=None, **kwargs):
        super().__init__(*args, **kwargs)
        apply_bootstrap_widgets(self)
        if municipality:
            self.fields["settlement"].queryset = municipality.settlements.filter(is_active=True)
            self.fields["category"].queryset = self.fields["category"].queryset.filter(
                is_active=True
            ).filter(municipality__in=[municipality, None])

    def clean_website(self):
        value = self.cleaned_data.get("website")
        if value:
            raise forms.ValidationError("Spam protection triggered.")
        return value

    def clean_send_receipt(self):
        requested = self.cleaned_data.get("send_receipt", False)
        if requested and not self.cleaned_data.get("citizen_email"):
            raise forms.ValidationError("Внесете е-пошта за да добиете потврда.")
        return requested


class IssueAttachmentForm(forms.ModelForm):
    class Meta:
        model = IssueAttachment
        fields = ["image"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_bootstrap_widgets(self)


class StaffIssueUpdateForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = [
            "priority",
            "assigned_department",
            "assigned_to",
            "internal_note",
            "public_resolution_note",
        ]
        labels = {
            "priority": "Приоритет",
            "assigned_department": "Одделение",
            "assigned_to": "Задолжен вработен",
            "internal_note": "Интерна белешка",
            "public_resolution_note": "Јавна белешка за решавање",
        }
        widgets = {
            "internal_note": forms.Textarea(attrs={"rows": 4}),
            "public_resolution_note": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, issue=None, **kwargs):
        super().__init__(*args, **kwargs)
        apply_bootstrap_widgets(self)
        issue = issue or self.instance
        municipality = getattr(issue, "municipality", None)
        if municipality:
            self.fields["assigned_department"].queryset = municipality.departments.filter(
                is_active=True
            )
            user_model = get_user_model()
            self.fields["assigned_to"].queryset = user_model.objects.filter(
                staffprofile__municipality=municipality,
                is_active=True,
            ).order_by("username")


class IssueCommentForm(forms.ModelForm):
    class Meta:
        model = IssueComment
        fields = ["body", "is_internal"]
        labels = {
            "body": "Коментар",
            "is_internal": "Интерен коментар",
        }
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_bootstrap_widgets(self)
