from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0005_application_cover_letter_file"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="application",
            name="cover_letter",
        ),
        migrations.RemoveField(
            model_name="application",
            name="resume",
        ),
        migrations.AddField(
            model_name="application",
            name="materials_url",
            field=models.URLField(
                blank=True,
                help_text="Google Drive folder that contains this job's cover letter and resume.",
                max_length=500,
            ),
        ),
    ]
