from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.analytics.services import (
    CompanyAnalyticsService,
    JobAnalyticsService,
    SkillAnalyticsService,
)
from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource
from apps.imports.services import JobSyncService, MonitoringService
from apps.jobs.models import JobPost
from .serializers import (
    ApplicationSerializer,
    CompanySerializer,
    CrawlRunSerializer,
    JobPostSerializer,
    JobSourceSerializer,
)


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

    @action(detail=True, methods=["post"], url_path="sync")
    def sync(self, request, pk=None):
        company = self.get_object()
        jobs = request.data.get("jobs") if isinstance(request.data, dict) else None
        result = JobSyncService.sync_company(company, jobs)
        return Response(result.as_dict())


class JobPostViewSet(viewsets.ModelViewSet):
    queryset = JobPost.objects.select_related("company").all()
    serializer_class = JobPostSerializer


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.select_related("user", "job_post").all()
    serializer_class = ApplicationSerializer


class JobSourceViewSet(viewsets.ModelViewSet):
    queryset = JobSource.objects.all()
    serializer_class = JobSourceSerializer


class CrawlRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CrawlRun.objects.all()
    serializer_class = CrawlRunSerializer

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        crawl_run = self.get_queryset().first()
        if crawl_run is None:
            return Response({"detail": "No crawl runs found."}, status=404)
        return Response(self.get_serializer(crawl_run).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crawl_run(request):
    crawl_run_record = CrawlRun.objects.create(status=CrawlRun.StatusChoices.PENDING)
    try:
        from apps.imports.tasks import crawl_all_sources
    except ModuleNotFoundError as exc:
        if exc.name != "celery":
            raise
        return Response(
            {
                "success": False,
                "detail": (
                    "Celery is not installed in this runtime. Rebuild the "
                    "Docker image or install project requirements."
                ),
                "crawl_run_id": crawl_run_record.id,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    crawl_all_sources.delay(crawl_run_id=crawl_run_record.id)
    return Response(
        {
            "success": True,
            "crawl_run_id": crawl_run_record.id,
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def crawl_status(request, pk):
    try:
        crawl_run_record = CrawlRun.objects.get(pk=pk)
    except CrawlRun.DoesNotExist:
        return Response({"detail": "Crawl run not found."}, status=404)

    return Response(
        {
            "status": crawl_run_record.status,
            "progress": crawl_run_record.progress_percentage,
            "jobs_created": crawl_run_record.jobs_created,
            "jobs_updated": crawl_run_record.jobs_updated,
            "jobs_closed": crawl_run_record.jobs_closed,
            "errors": crawl_run_record.errors,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def run_status(request, pk):
    try:
        payload = MonitoringService.run_status(
            crawl_run_id=pk,
            recent_limit=_limit_from_request(request, default=20),
        )
    except CrawlRun.DoesNotExist:
        return Response({"detail": "Crawl run not found."}, status=404)
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def monitoring_logs(request):
    return Response(
        {
            "results": MonitoringService.recent_logs(
                limit=_limit_from_request(request, default=50),
                status=request.query_params.get("status", ""),
                severity=request.query_params.get("severity", ""),
                step_name=request.query_params.get("step_name", ""),
                source_id=_int_from_request(request, "source_id"),
                crawl_run_id=_int_from_request(request, "crawl_run_id"),
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_skills(request):
    service = SkillAnalyticsService()
    return Response(
        {
            "results": service.top_skills(
                limit=_limit_from_request(request),
                filters=request.query_params,
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_companies(request):
    service = CompanyAnalyticsService()
    company_id = _int_from_request(request, "company_id")
    return Response(
        {
            "results": service.company_skill_breakdown(
                company_id=company_id,
                limit=_limit_from_request(request),
                filters=request.query_params,
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_trends(request):
    service = SkillAnalyticsService()
    return Response(
        {
            "results": service.skill_trends_by_month(
                limit=_limit_from_request(request),
                filters=request.query_params,
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_gaps(request):
    company_id = _int_from_request(request, "company_id")
    if company_id is None:
        return Response({"detail": "company_id is required."}, status=400)
    service = CompanyAnalyticsService()
    return Response(
        {
            "results": service.skill_gap_analysis(
                company_id=company_id,
                limit=_limit_from_request(request),
                filters=request.query_params,
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_job_categories(request):
    service = JobAnalyticsService()
    return Response(
        {
            "results": service.top_skills_by_job_category(
                category_field=request.query_params.get(
                    "category_field",
                    "employment_type",
                ),
                limit=_limit_from_request(request),
                filters=request.query_params,
            )
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def analytics_application_comparison(request, pk):
    service = SkillAnalyticsService()
    return Response(service.application_skill_comparison(application_id=pk))


def _limit_from_request(request, default=10):
    try:
        return max(1, min(100, int(request.query_params.get("limit", default))))
    except (TypeError, ValueError):
        return default


def _int_from_request(request, key):
    try:
        return int(request.query_params.get(key))
    except (TypeError, ValueError):
        return None
