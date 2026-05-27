from django import forms
from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['user', 'job_post', 'status', 'applied_at', 'priority', 'referral']
