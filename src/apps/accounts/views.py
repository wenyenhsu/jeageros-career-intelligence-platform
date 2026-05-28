from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import AdminUserCreateForm, AdminUserUpdateForm

User = get_user_model()


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied


class UserListView(StaffRequiredMixin, ListView):
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    ordering = ['username']


class UserCreateView(StaffRequiredMixin, CreateView):
    model = User
    form_class = AdminUserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('user-list')


class UserUpdateView(StaffRequiredMixin, UpdateView):
    model = User
    form_class = AdminUserUpdateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('user-list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if self.object == self.request.user:
            messages.info(self.request, 'Your own admin status and active status stay unchanged.')
        return super().form_valid(form)


class UserDeleteView(StaffRequiredMixin, DeleteView):
    model = User
    template_name = 'accounts/user_confirm_delete.html'
    success_url = reverse_lazy('user-list')

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object == request.user:
            messages.error(request, 'You cannot delete your own account.')
            return HttpResponseRedirect(self.success_url)
        return super().post(request, *args, **kwargs)
