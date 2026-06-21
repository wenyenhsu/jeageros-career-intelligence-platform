from django.db import migrations


def reset_all_job_status_active(apps, schema_editor):
    JobPost = apps.get_model("jobs", "JobPost")
    JobPost.objects.exclude(status="ACTIVE").update(status="ACTIVE")


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_jobpost_job_type_compat"),
    ]

    operations = [
        migrations.RunPython(reset_all_job_status_active, migrations.RunPython.noop),
    ]
