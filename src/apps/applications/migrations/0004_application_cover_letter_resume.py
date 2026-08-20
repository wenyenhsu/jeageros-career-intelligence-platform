import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0003_application_skill_sets"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="cover_letter",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="application",
            name="resume",
            field=models.FileField(
                blank=True,
                help_text="PDF or DOCX, max 5 MB.",
                upload_to="applications/resumes/%Y/%m/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf", "docx"]
                    )
                ],
            ),
        ),
    ]
