from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    DeleteView,
)
from .forms import ApplicationForm
from .models import Application
from .search import filter_applications_for_search


class ApplicationListView(ListView):
    model = Application
    template_name = "applications/application_list.html"
    context_object_name = "applications"

    def get_queryset(self):
        queryset = Application.objects.select_related(
            "job_post__company",
            "user",
        ).prefetch_related(
            "skill_sets",
            "skill_sets__keywords",
            "job_post__skill_sets",
            "job_post__skill_sets__keywords",
        )
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset

        return filter_applications_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class ApplicationDetailView(DetailView):
    model = Application
    template_name = "applications/application_detail.html"
    context_object_name = "application"
    queryset = Application.objects.select_related(
        "job_post__company",
        "user",
    ).prefetch_related(
        "skill_sets",
        "skill_sets__keywords",
        "job_post__skill_sets",
        "job_post__skill_sets__keywords",
        "history",
    )


class ApplicationCreateView(CreateView):
    model = Application
    form_class = ApplicationForm
    template_name = "applications/application_form.html"
    success_url = reverse_lazy("application-list")


class ApplicationUpdateView(UpdateView):
    model = Application
    form_class = ApplicationForm
    template_name = "applications/application_form.html"
    success_url = reverse_lazy("application-list")


class ApplicationDeleteView(DeleteView):
    model = Application
    success_url = reverse_lazy("application-list")
