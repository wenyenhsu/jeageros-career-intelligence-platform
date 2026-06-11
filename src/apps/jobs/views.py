from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    DeleteView,
)
from apps.skills.models import SkillKeyword
from .forms import JobPostForm
from .models import JobPost
from .search import filter_jobs_for_search


class JobListView(ListView):
    model = JobPost
    template_name = "jobs/job_list.html"
    context_object_name = "jobs"

    def get_queryset(self):
        queryset = JobPost.objects.select_related("company").prefetch_related(
            "skill_sets",
            "skill_sets__keywords",
        )
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset

        return filter_jobs_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class JobDetailView(DetailView):
    model = JobPost
    template_name = "jobs/job_detail.html"
    context_object_name = "job"
    queryset = JobPost.objects.select_related("company").prefetch_related(
        "skill_sets",
        "skill_sets__keywords",
    )


class JobCreateView(CreateView):
    model = JobPost
    form_class = JobPostForm
    template_name = "jobs/job_form.html"
    success_url = reverse_lazy("job-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        _add_existing_keyword_warning(self.request, form)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["skill_keyword_lookup"] = _skill_keyword_lookup()
        return context


class JobUpdateView(UpdateView):
    model = JobPost
    form_class = JobPostForm
    template_name = "jobs/job_form.html"
    success_url = reverse_lazy("job-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        _add_existing_keyword_warning(self.request, form)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["skill_keyword_lookup"] = _skill_keyword_lookup()
        return context


class JobDeleteView(DeleteView):
    model = JobPost
    success_url = reverse_lazy("job-list")


def _skill_keyword_lookup():
    lookup = []
    for keyword in SkillKeyword.objects.select_related("skill_set").order_by(
        "normalized_text",
        "skill_set__name",
    ):
        lookup.append(
            {
                "raw_text": keyword.raw_text,
                "normalized_text": keyword.normalized_text,
                "skill_set_id": keyword.skill_set_id,
                "skill_set_name": keyword.skill_set.name,
                "status": keyword.status,
                "source": keyword.source,
            }
        )
    return lookup


def _add_existing_keyword_warning(request, form):
    warning = form.existing_keyword_warning
    if warning:
        messages.warning(request, warning)
