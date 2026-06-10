from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Company
from .forms import CompanyForm
from apps.imports.services import JobSyncService


@require_POST
def company_sync_jobs(request, pk):
    company = get_object_or_404(Company, pk=pk)
    result = JobSyncService.sync_company(company)
    messages.success(
        request,
        (
            "Job sync completed: "
            f"{result.jobs_created} created, "
            f"{result.jobs_updated} updated, "
            f"{result.jobs_closed} closed."
        ),
    )
    return redirect("company-detail", pk=company.pk)


class CompanyListView(ListView):
    model = Company
    template_name = "companies/company_list.html"
    context_object_name = "companies"


class CompanyDetailView(DetailView):
    model = Company
    template_name = "companies/company_detail.html"
    context_object_name = "company"


class CompanyCreateView(CreateView):
    model = Company
    form_class = CompanyForm
    template_name = "companies/company_form.html"
    success_url = reverse_lazy("company-list")


class CompanyUpdateView(UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = "companies/company_form.html"
    success_url = reverse_lazy("company-list")


class CompanyDeleteView(DeleteView):
    model = Company
    template_name = "companies/company_confirm_delete.html"
    success_url = reverse_lazy("company-list")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        return super().post(request, *args, **kwargs)
