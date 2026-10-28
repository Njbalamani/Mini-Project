from django import forms

from .models import Document


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "file"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input",
                                            "placeholder": "Document title"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-input",
                                                    "accept": ".pdf,.txt,.docx"}),
        }

    def clean_file(self):
        from .services import DocumentError, validate_upload
        uploaded = self.cleaned_data["file"]
        try:
            validate_upload(uploaded)
        except DocumentError as exc:
            raise forms.ValidationError(str(exc))
        return uploaded

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            # Fall back to the uploaded filename.
            uploaded = self.cleaned_data.get("file")
            if uploaded:
                return uploaded.name[:200]
            raise forms.ValidationError("A title is required.")
        return title


class QuestionForm(forms.Form):
    question = forms.CharField(
        max_length=400,
        widget=forms.TextInput(attrs={"class": "form-input",
                                      "placeholder": "Ask a question about this document"}),
    )
