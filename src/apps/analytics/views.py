from django.db.models import Count
from django.shortcuts import render
from apps.applications.models import Application


def dashboard(request):
    summary = {
        'total_applications': Application.objects.count(),
        'status_counts': Application.objects.values('status').annotate(total=Count('id')),
    }
    return render(request, 'dashboard/index.html', summary)
