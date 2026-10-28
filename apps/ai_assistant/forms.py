from django import forms

from .models import AIProviderConfiguration


class AIConfigForm(forms.ModelForm):
    class Meta:
        model = AIProviderConfiguration
        fields = ["provider", "model", "temperature", "system_prompt"]
        widgets = {
            "provider": forms.Select(attrs={"class": "form-input"}),
            "model": forms.TextInput(attrs={"class": "form-input",
                                            "placeholder": "e.g. gpt-4o-mini"}),
            "temperature": forms.NumberInput(attrs={"class": "form-input", "step": "0.1",
                                                    "min": "0", "max": "1"}),
            "system_prompt": forms.Textarea(attrs={"class": "form-input", "rows": 4,
                                                   "placeholder": "Optional custom instructions"}),
        }

    def clean_temperature(self):
        value = self.cleaned_data["temperature"]
        if not 0 <= value <= 1:
            raise forms.ValidationError("Temperature must be between 0 and 1.")
        return value
