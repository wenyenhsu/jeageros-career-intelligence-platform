from django import forms
from .models import Company



class CompanyForm(forms.ModelForm):

    class Meta:
        model = Company
        fields = "__all__"

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),

            "website": forms.URLInput(
                attrs={"class": "form-control"}
            ),

            "industry": forms.TextInput(
                attrs={"class": "form-control"}
            ),

            "location": forms.TextInput(
                attrs={"class": "form-control"}
            ),

            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                }
            ),
        }
