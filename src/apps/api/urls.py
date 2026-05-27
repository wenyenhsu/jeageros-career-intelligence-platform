from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ApplicationViewSet, CompanyViewSet, JobPostViewSet

router = DefaultRouter()
router.register('companies', CompanyViewSet)
router.register('jobs', JobPostViewSet)
router.register('applications', ApplicationViewSet)

urlpatterns = [path('', include(router.urls))]
