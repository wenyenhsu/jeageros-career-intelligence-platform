from django.contrib.auth.mixins import LoginRequiredMixin


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Forbidden')
        return super().dispatch(request, *args, **kwargs)
