from django import forms


class MunicipalityConfigurationImportForm(forms.Form):
    configuration_file = forms.FileField(label="JSON конфигурација")
    source_reference = forms.CharField(label="Официјален извор / референца", max_length=255)
    verify = forms.BooleanField(label="Означи како официјално верификувана", required=False)


class MunicipalityConfigurationVerifyForm(forms.Form):
    source_reference = forms.CharField(label="Официјален извор / референца", max_length=255)
