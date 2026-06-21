from django.db import migrations


def mark_applied_jobs(apps, schema_editor):
    JobPost = apps.get_model("jobs", "JobPost")
    Application = apps.get_model("applications", "Application")
    applied_job_ids = Application.objects.values_list("job_post_id", flat=True).distinct()
    JobPost.objects.filter(id__in=applied_job_ids).exclude(status="ARCHIVED").update(
        status="APPLIED"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0006_reset_all_job_status_active"),
        ("applications", "0003_application_skill_sets"),
    ]

    operations = [
        migrations.RunPython(mark_applied_jobs, migrations.RunPython.noop),
    ]
