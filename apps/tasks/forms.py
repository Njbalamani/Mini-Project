import json

from django import forms
from django.utils import timezone

from .models import SavedTaskFilter, Tag, Task, TaskComment

INPUT = "form-input"


class TaskForm(forms.ModelForm):
    due_date = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"class": INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"],
    )
    recurrence_until = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": INPUT, "type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": INPUT, "placeholder": "work, urgent (comma separated)",
        }),
        help_text="Up to 8 tags.",
    )

    class Meta:
        model = Task
        fields = [
            "title", "description", "status", "priority", "category", "due_date",
            "recurrence", "recurrence_until",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT, "placeholder": "What needs doing?"}),
            "description": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
            "status": forms.Select(attrs={"class": INPUT}),
            "priority": forms.Select(attrs={"class": INPUT}),
            "category": forms.TextInput(attrs={"class": INPUT, "placeholder": "e.g. Work"}),
            "recurrence": forms.Select(attrs={"class": INPUT}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.due_date:
                self.initial["due_date"] = timezone.localtime(self.instance.due_date).strftime("%Y-%m-%dT%H:%M")
            self.initial["tags"] = ", ".join(self.instance.tags.values_list("name", flat=True))
        suggestions = []
        if self.user is not None:
            suggestions = list(
                Tag.objects.filter(owner=self.user).values_list("name", flat=True)
            )
        self.fields["tags"].widget.attrs["data-suggestions"] = json.dumps(suggestions)
        self.fields["tags"].widget.attrs["autocomplete"] = "off"

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 2:
            raise forms.ValidationError("Title must be at least 2 characters.")
        return title


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "class": INPUT, "rows": 2, "placeholder": "Add a comment…",
            }),
        }

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Comment cannot be empty.")
        return body


class SavedTaskFilterForm(forms.ModelForm):
    class Meta:
        model = SavedTaskFilter
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": INPUT, "placeholder": "Save current view as…", "maxlength": 80,
            }),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Give the saved view a name.")
        return name


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": INPUT, "placeholder": "e.g. Urgent", "maxlength": 40,
            }),
            "color": forms.TextInput(attrs={"class": INPUT, "type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Give the tag a name.")
        dupes = Tag.objects.filter(owner=self.user, name__iexact=name)
        if self.instance.pk:
            dupes = dupes.exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("You already have a tag with that name.")
        return name

    def clean_color(self):
        color = (self.cleaned_data.get("color") or "").strip()
        if not color:
            from .services import _tag_color

            return _tag_color(self.cleaned_data.get("name", "tag"))
        if not (len(color) == 7 and color.startswith("#")):
            raise forms.ValidationError("Use a 6-digit hex colour like #d4af37.")
        return color
