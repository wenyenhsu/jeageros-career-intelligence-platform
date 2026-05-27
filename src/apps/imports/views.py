from django.http import JsonResponse


def job_url_import(request):
    return JsonResponse({'status': 'ready'})
