from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import JobSourceForm
from .models import JobSource


def job_url_import(request):
    return redirect("source-list")


class JobSourceListView(ListView):
    model = JobSource
    template_name = "imports/job_source_list.html"
    context_object_name = "sources"


class JobSourceDetailView(DetailView):
    model = JobSource
    template_name = "imports/job_source_detail.html"
    context_object_name = "source"


class JobSourceCreateView(CreateView):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceUpdateView(UpdateView):
    model = JobSource
    form_class = JobSourceForm
    template_name = "imports/job_source_form.html"
    success_url = reverse_lazy("source-list")


class JobSourceDeleteView(DeleteView):
    model = JobSource
    template_name = "imports/job_source_confirm_delete.html"
    success_url = reverse_lazy("source-list")
