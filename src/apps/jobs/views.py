from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from .forms import JobPostForm
from .models import JobPost


class JobListView(ListView):
    model = JobPost
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'


class JobDetailView(DetailView):
    model = JobPost
    template_name = 'jobs/job_detail.html'
    context_object_name = 'job'


class JobCreateView(CreateView):
    model = JobPost
    form_class = JobPostForm
    template_name = 'jobs/job_form.html'
    success_url = reverse_lazy('job-list')


class JobUpdateView(UpdateView):
    model = JobPost
    form_class = JobPostForm
    template_name = 'jobs/job_form.html'
    success_url = reverse_lazy('job-list')
