from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class UserRoleMixin:
    ROLE_CHOICES = (
        ('guest', 'Guest'),
        ('admin', 'Admin'),
    )

    role = forms.ChoiceField(choices=ROLE_CHOICES, initial='guest', label='Role')

    def _apply_role(self, user):
        role = self.cleaned_data.get('role', 'guest')
        user.is_staff = role == 'admin'
        user.is_superuser = role == 'admin'
        return user


class AdminUserCreateForm(UserRoleMixin, UserCreationForm):
    role = forms.ChoiceField(
        choices=(
            ('admin', 'Admin'),
            ('guest', 'Guest'),
        ),
        required=True,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].widget.attrs['class'] = 'form-select'

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user = self._apply_role(user)
        if commit:
            user.save()
        return user


class AdminUserUpdateForm(UserRoleMixin, StyledModelForm):
    role = forms.ChoiceField(
        choices=(
            ('admin', 'Admin'),
            ('guest', 'Guest'),
        ),
        required=True,
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_user = request_user
        self.is_self_edit = bool(self.request_user and self.instance.pk == self.request_user.pk)

        for name in ('email', 'first_name', 'last_name'):
            self.fields[name].required = False
        self.fields['role'].initial = 'admin' if self.instance.is_staff else 'guest'
        self.fields['role'].widget.attrs['class'] = 'form-select'

        if self.is_self_edit:
            self.fields['role'].disabled = True
            self.fields['is_active'].disabled = True
            self.fields['role'].help_text = 'Your own role cannot be changed from here.'
            self.fields['is_active'].help_text = 'Your own active status stays enabled.'

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')

        if self.is_self_edit:
            user.is_staff = self.instance.is_staff
            user.is_superuser = self.instance.is_superuser
            user.is_active = self.instance.is_active
        else:
            user = self._apply_role(user)

        if commit:
            user.save()
        return user
