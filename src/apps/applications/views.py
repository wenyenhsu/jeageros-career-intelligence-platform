from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    DeleteView,
)
from apps.common.mixins import UserOwnedQuerySetMixin, scope_queryset_to_user
from .forms import ApplicationForm
from .models import Application
from .search import filter_applications_for_search
from .services.ats_scan_service import AtsScanError, AtsScanService
from .services.cover_letter_tailor_service import (
    get_cover_letter_progress,
    normalize_run_id,
    queue_cover_letter_tailor,
)
from .services.materials_pack_service import MaterialsPackError, MaterialsPackService


def _wants_json(request):
    accept = (request.headers.get("Accept") or "").casefold()
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
    )


def _queue_copied_pack_tailor(request, form, application):
    if not getattr(form, "copied_pack", False):
        return ""
    run_id = normalize_run_id(request.POST.get("cover_letter_run_id")) or uuid4().hex
    queue_cover_letter_tailor(application.pk, run_id)
    return run_id


def _queue_job_skill_refresh(request, application):
    from apps.imports.services import JobUrlRefreshService
    from apps.imports.services.skill_attach_service import SkillAttachService
    from apps.imports.tasks import refresh_job_from_url

    job = getattr(application, "job_post", None)
    if job is None:
        return False
    SkillAttachService.copy_job_skills_to_application(job, application)
    if not JobUrlRefreshService.needs_refresh(job):
        return False
    refresh_job_from_url.delay(job.id)
    messages.info(request, "Fetching location and skills from the job URL.")
    return True


def _application_form_success(
    request, form, application, redirect_url, extract_job_skills=False
):
    if extract_job_skills:
        _queue_job_skill_refresh(request, application)
    run_id = _queue_copied_pack_tailor(request, form, application)
    if _wants_json(request):
        return JsonResponse(
            {
                "success": True,
                "cover_letter_run_id": run_id,
                "redirect_url": redirect_url,
            },
            status=202 if run_id else 200,
        )
    return redirect(redirect_url)


class ApplicationListView(UserOwnedQuerySetMixin, ListView):
    model = Application
    template_name = "applications/application_list.html"
    context_object_name = "applications"
    queryset = Application.objects.select_related(
        "job_post__company",
        "user",
    ).prefetch_related(
        "skill_sets",
        "skill_sets__keywords",
        "job_post__skill_sets",
        "job_post__skill_sets__keywords",
    )

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get("q", "").strip()
        if not query:
            return queryset

        return filter_applications_for_search(queryset, query)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "").strip()
        context["materials_pack_choices"] = Application.MaterialsPack.choices
        return context


class ApplicationDetailView(UserOwnedQuerySetMixin, DetailView):
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["materials_pack_choices"] = Application.MaterialsPack.choices
        return context


class ApplicationCreateView(LoginRequiredMixin, CreateView):
    model = Application
    form_class = ApplicationForm
    template_name = "applications/application_form.html"
    success_url = reverse_lazy("application-list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["allow_manual_job"] = True
        kwargs["acting_user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        user = getattr(self.request, "user", None)
        if user is not None and user.is_authenticated:
            initial["user"] = user
        return initial

    def form_valid(self, form):
        self.object = form.save()
        return _application_form_success(
            self.request,
            form,
            self.object,
            self.get_success_url(),
            extract_job_skills=True,
        )

    def form_invalid(self, form):
        if _wants_json(self.request):
            return JsonResponse(
                {"success": False, "error": "Please fix the form errors."},
                status=400,
            )
        return super().form_invalid(form)


class ApplicationUpdateView(UserOwnedQuerySetMixin, UpdateView):
    model = Application
    form_class = ApplicationForm
    template_name = "applications/application_form.html"
    success_url = reverse_lazy("application-list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["acting_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        self.object = form.save()
        return _application_form_success(
            self.request, form, self.object, self.get_success_url()
        )

    def form_invalid(self, form):
        if _wants_json(self.request):
            return JsonResponse(
                {"success": False, "error": "Please fix the form errors."},
                status=400,
            )
        return super().form_invalid(form)


class ApplicationDeleteView(UserOwnedQuerySetMixin, DeleteView):
    model = Application
    success_url = reverse_lazy("application-list")


@login_required
@require_POST
def run_application_ats_scan(request, pk):
    application = get_object_or_404(
        scope_queryset_to_user(
            Application.objects.select_related("job_post__company"),
            request.user,
        ),
        pk=pk,
    )
    try:
        result = AtsScanService().scan(application, write_drafts=True)
    except AtsScanError as exc:
        messages.error(request, str(exc))
        return redirect("application-detail", pk=pk)

    score = result.get("score")
    target = result.get("target") or AtsScanService.target_score
    matched = result.get("matched_count")
    total = result.get("keyword_count")
    if result.get("meets_target"):
        messages.success(
            request,
            f"ATS score {score} ({matched}/{total}) meets the {target}% target.",
        )
    else:
        tailored = result.get("tailored_score")
        extra = ""
        if tailored is not None:
            extra = f" Tailored Resume.pdf scores {tailored}."
        messages.warning(
            request,
            f"ATS score {score} ({matched}/{total}) is below the {target}% target.{extra}",
        )
    return redirect("application-detail", pk=pk)


@login_required
@require_POST
def apply_application_materials_pack(request, pk):
    application = get_object_or_404(
        scope_queryset_to_user(
            Application.objects.select_related("job_post__company"),
            request.user,
        ),
        pk=pk,
    )
    next_url = request.POST.get("next") or ""
    if not (next_url.startswith("/") and not next_url.startswith("//")):
        next_url = reverse("application-list")
    try:
        result = MaterialsPackService().apply_pack(
            application, request.POST.get("pack")
        )
    except MaterialsPackError as exc:
        messages.error(request, str(exc))
        return redirect(next_url)

    copied = ", ".join(result["copied"])
    missing = result.get("missing") or []
    if missing:
        messages.warning(
            request,
            f"Copied {result['pack']} files ({copied}). Missing: {', '.join(missing)}.",
        )
    else:
        messages.success(
            request,
            f"Copied {result['pack']} materials into the local folder.",
        )
    return redirect(next_url)


@login_required
@require_GET
def cover_letter_tailor_status(request):
    run_id = normalize_run_id(request.GET.get("run_id"))
    payload = get_cover_letter_progress(run_id)
    if not payload:
        return JsonResponse(
            {
                "run_id": run_id,
                "status": "PENDING",
                "progress": 8,
                "current_step": {"label": "Waiting for status"},
                "error": "",
            }
        )
    return JsonResponse(payload)
