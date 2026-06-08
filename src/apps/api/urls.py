from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ApplicationViewSet, CompanyViewSet, JobPostViewSet

router = DefaultRouter()
router.register('companies', CompanyViewSet, basename='api-company')
router.register('jobs', JobPostViewSet, basename='api-job')
router.register('applications', ApplicationViewSet, basename='api-application')

urlpatterns = [path('', include(router.urls))]
