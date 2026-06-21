from apps.jobs.models import JobPost


def sync_job_status_from_applications(job_post):
    if job_post.status == JobPost.StatusChoices.ARCHIVED:
        return False

    has_applications = job_post.applications.exists()
    if has_applications:
        new_status = JobPost.StatusChoices.APPLIED
    elif job_post.status == JobPost.StatusChoices.APPLIED:
        new_status = JobPost.StatusChoices.ACTIVE
    else:
        return False

    if job_post.status == new_status:
        return False

    job_post.status = new_status
    job_post.save(update_fields=["status", "updated_at"])
    return True


def sync_job_status_for_job_post_id(job_post_id):
    if not job_post_id:
        return False

    job_post = JobPost.objects.filter(pk=job_post_id).first()
    if job_post is None:
        return False

    return sync_job_status_from_applications(job_post)
