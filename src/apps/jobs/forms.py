from django import forms
from .models import JobPost


class JobPostForm(forms.ModelForm):
    class Meta:
        model = JobPost
        fields = ['company', 'title', 'source_url', 'source_type', 'location', 'remote_type', 'salary_min', 'salary_max', 'description', 'tags']
