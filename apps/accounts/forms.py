"""Authentication and profile forms with inline validation."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)

from .models import UserPreference, UserProfile

User = get_user_model()

INPUT = "form-input"


class RegistrationForm(forms.ModelForm):
    full_name = forms.CharField(max_length=160, required=False)
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"}),
    )
    agree = forms.BooleanField(
        label="I agree to the Terms and Privacy Policy", required=True
    )

    class Meta:
        model = User
        fields = ["email", "full_name"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": INPUT, "autocomplete": "email"}),
            "full_name": forms.TextInput(attrs={"class": INPUT, "autocomplete": "name"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        if p1:
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(p1)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.full_name = self.cleaned_data.get("full_name", "")
        user.set_password(self.cleaned_data["password1"])
        user.is_email_verified = False
        if commit:
            user.save()
        return user


class NexaAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"class": INPUT, "autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "current-password"})
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_active:
            raise forms.ValidationError("This account is disabled.", code="inactive")


class NexaPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": INPUT, "autocomplete": "email"})
    )

    def get_users(self, email):
        # Only allow reset for usable, active accounts.
        return User.objects.filter(email__iexact=email, is_active=True)


class NexaSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"})
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"})
    )


class NexaPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "current-password"})
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"})
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"})
    )


class ProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=160, required=False, widget=forms.TextInput(attrs={"class": INPUT}))
    avatar = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"class": INPUT, "accept": "image/*"}))

    class Meta:
        model = UserProfile
        fields = ["avatar", "bio", "job_title", "company", "timezone", "language", "theme"]
        widgets = {
            "bio": forms.Textarea(attrs={"class": INPUT, "rows": 3}),
            "job_title": forms.TextInput(attrs={"class": INPUT}),
            "company": forms.TextInput(attrs={"class": INPUT}),
            "timezone": forms.TextInput(attrs={"class": INPUT}),
            "language": forms.TextInput(attrs={"class": INPUT}),
            "theme": forms.Select(attrs={"class": INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["full_name"].initial = self.instance.user.full_name

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user.full_name = self.cleaned_data.get("full_name", "")
        profile.user.save(update_fields=["full_name"])
        if commit:
            profile.save()
        return profile


class PreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "email_notifications", "in_app_notifications", "task_reminders",
            "workflow_notifications", "integration_alerts", "weekly_digest",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "switch-input"


class TwoFactorVerifyForm(forms.Form):
    code = forms.CharField(
        label="Authentication code", max_length=20,
        widget=forms.TextInput(attrs={
            "class": INPUT, "inputmode": "numeric", "autocomplete": "one-time-code",
            "autofocus": True, "placeholder": "6-digit code or backup code",
        }),
    )


class TwoFactorDisableForm(forms.Form):
    password = forms.CharField(
        label="Confirm your password",
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "current-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user or not self.user.check_password(password):
            raise forms.ValidationError("That password is not correct.")
        return password
