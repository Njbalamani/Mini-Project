from django import forms

from .models import CategorizationRule, EmailDraft, EmailSettings

INPUT = "form-input"


class EmailSettingsForm(forms.ModelForm):
    class Meta:
        model = EmailSettings
        fields = ["store_message_bodies", "sending_enabled", "auto_categorize"]
        widgets = {
            "store_message_bodies": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "sending_enabled": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "auto_categorize": forms.CheckboxInput(attrs={"class": "switch-input"}),
        }


class CategorizationRuleForm(forms.ModelForm):
    class Meta:
        model = CategorizationRule
        fields = ["keyword", "category"]
        widgets = {
            "keyword": forms.TextInput(attrs={"class": INPUT, "placeholder": "keyword"}),
            "category": forms.TextInput(attrs={"class": INPUT, "placeholder": "Category"}),
        }


class DraftForm(forms.ModelForm):
    class Meta:
        model = EmailDraft
        fields = ["to", "subject", "body"]
        widgets = {
            "to": forms.TextInput(attrs={"class": INPUT}),
            "subject": forms.TextInput(attrs={"class": INPUT}),
            "body": forms.Textarea(attrs={"class": INPUT, "rows": 8}),
        }
