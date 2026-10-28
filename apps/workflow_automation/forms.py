from django import forms

from .models import (
    ActionType,
    ConditionType,
    TriggerType,
    Workflow,
    WorkflowAction,
    WorkflowCondition,
    WorkflowTrigger,
)

INPUT = "form-input"
PRIORITY_CHOICES = [("", "Default (medium)"), ("low", "Low"), ("medium", "Medium"),
                    ("high", "High"), ("urgent", "Urgent")]


class WorkflowForm(forms.ModelForm):
    trigger_type = forms.ChoiceField(
        choices=TriggerType.choices, widget=forms.Select(attrs={"class": INPUT})
    )
    schedule_time = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT, "type": "time"}),
        help_text="Required for scheduled triggers.",
    )
    condition_type = forms.ChoiceField(
        choices=ConditionType.choices,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    action_type = forms.ChoiceField(
        choices=ActionType.choices, widget=forms.Select(attrs={"class": INPUT})
    )
    action_title = forms.CharField(
        required=False, max_length=200,
        widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "Follow-up task title"}),
        help_text="Only used by the create-follow-up-task action.",
    )
    action_priority = forms.ChoiceField(
        required=False, choices=PRIORITY_CHOICES,
        widget=forms.Select(attrs={"class": INPUT}),
        help_text="Priority for the created task.",
    )

    class Meta:
        model = Workflow
        fields = ["name", "description", "is_enabled"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT}),
            "description": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
            "is_enabled": forms.CheckboxInput(attrs={"class": "switch-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            trigger = self.instance.triggers.first()
            condition = self.instance.conditions.first()
            action = self.instance.actions.first()
            if trigger:
                self.initial["trigger_type"] = trigger.trigger_type
                self.initial["schedule_time"] = trigger.schedule_time
            if condition:
                self.initial["condition_type"] = condition.condition_type
            if action:
                self.initial["action_type"] = action.action_type
                self.initial["action_title"] = (action.config or {}).get("title", "")
                self.initial["action_priority"] = (action.config or {}).get("priority", "")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("trigger_type") == TriggerType.SCHEDULED and not cleaned.get("schedule_time"):
            self.add_error("schedule_time", "Provide a time for scheduled workflows.")
        if cleaned.get("action_type") == ActionType.CREATE_TASK and not cleaned.get("action_title"):
            self.add_error("action_title", "Provide a title for the task to create.")
        return cleaned

    @property
    def config_values(self):
        data = self.cleaned_data
        return {
            "trigger_type": data["trigger_type"],
            "schedule_time": data.get("schedule_time", ""),
            "condition_type": data["condition_type"],
            "action_type": data["action_type"],
            "action_config": {
                "title": data.get("action_title", "").strip(),
                "priority": data.get("action_priority", ""),
            },
        }
