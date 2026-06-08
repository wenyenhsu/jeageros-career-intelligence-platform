from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView,DeleteView
from .forms import ApplicationForm
from .models import Application


class ApplicationListView(ListView):
    model = Application
    template_name = 'applications/application_list.html'
    context_object_name = 'applications'


class ApplicationDetailView(DetailView):
    model = Application
    template_name = 'applications/application_detail.html'
    context_object_name = 'application'


class ApplicationCreateView(CreateView):
    model = Application
    form_class = ApplicationForm
    template_name = 'applications/application_form.html'
    success_url = reverse_lazy('application-list')


class ApplicationUpdateView(UpdateView):
    model = Application
    form_class = ApplicationForm
    template_name = 'applications/application_form.html'
    success_url = reverse_lazy('application-list')

class ApplicationDeleteView(DeleteView):
    model = Application
    success_url = reverse_lazy("application-list")