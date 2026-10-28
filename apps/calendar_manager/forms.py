from django import forms
from django.utils import timezone

from .models import CalendarEvent, EventReminder

INPUT = "form-input"


class CalendarEventForm(forms.ModelForm):
    start = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": INPUT, "type": "datetime-local"},
                                   format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    end = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": INPUT, "type": "datetime-local"},
                                   format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    reminder_minutes = forms.ChoiceField(
        required=False,
        choices=[("", "No reminder"), ("5", "5 minutes before"), ("15", "15 minutes before"),
                 ("30", "30 minutes before"), ("60", "1 hour before"), ("1440", "1 day before")],
        widget=forms.Select(attrs={"class": INPUT}),
    )

    class Meta:
        model = CalendarEvent
        fields = ["title", "description", "location", "start", "end", "all_day", "recurrence"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT}),
            "description": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
            "location": forms.TextInput(attrs={"class": INPUT}),
            "all_day": forms.CheckboxInput(attrs={"class": "switch-input"}),
            "recurrence": forms.Select(attrs={"class": INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            now = timezone.localtime().replace(second=0, microsecond=0)
            self.initial["start"] = now.strftime("%Y-%m-%dT%H:%M")
            self.initial["end"] = (now + timezone.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        else:
            self.initial["start"] = timezone.localtime(self.instance.start).strftime("%Y-%m-%dT%H:%M")
            self.initial["end"] = timezone.localtime(self.instance.end).strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start"), cleaned.get("end")
        if start and end and end < start:
            self.add_error("end", "End time must be after the start time.")
        return cleaned
