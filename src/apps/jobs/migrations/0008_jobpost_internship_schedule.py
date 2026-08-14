from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0007_jobpost_applied_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobpost",
            name="starts_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="ends_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="start_precision",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="end_precision",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="season",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="duration_weeks",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="jobpost",
            name="schedule_raw",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
