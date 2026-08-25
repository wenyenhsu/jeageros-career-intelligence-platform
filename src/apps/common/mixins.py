from django.contrib.auth.mixins import LoginRequiredMixin


def scope_queryset_to_user(queryset, user, owner_field="user"):
    """Return all rows for staff and owner-scoped rows for regular users."""
    if user.is_staff:
        return queryset
    return queryset.filter(**{owner_field: user})


class UserOwnedQuerySetMixin(LoginRequiredMixin):
    owner_field = "user"

    def get_queryset(self):
        queryset = super().get_queryset()
        return scope_queryset_to_user(
            queryset,
            self.request.user,
            owner_field=self.owner_field,
        )


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Forbidden')
        return super().dispatch(request, *args, **kwargs)
