from .models import StatusHistory


def record_status_transition(application, old_status, new_status, user=None):
    return StatusHistory.objects.create(
        application=application,
        old_status=old_status,
        new_status=new_status,
        changed_by=user,
    )
