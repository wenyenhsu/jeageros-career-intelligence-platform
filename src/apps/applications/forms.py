from django import forms
from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['user', 'job_post', 'status', 'applied_at', 'priority', 'referral']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'job_post': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'applied_at': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
                format='%Y-%m-%dT%H:%M'
            ),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
            'referral': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.applied_at:
            self.initial['applied_at'] = self.instance.applied_at.strftime('%Y-%m-%dT%H:%M')