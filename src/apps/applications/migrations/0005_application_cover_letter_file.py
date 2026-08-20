import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0004_application_cover_letter_resume"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="application",
            name="cover_letter",
        ),
        migrations.AddField(
            model_name="application",
            name="cover_letter",
            field=models.FileField(
                blank=True,
                help_text="PDF or DOCX, max 5 MB.",
                upload_to="applications/cover_letters/%Y/%m/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf", "docx"]
                    )
                ],
            ),
        ),
    ]
