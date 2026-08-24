from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0006_application_materials_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="ats_scan",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Latest Simplify-style ATS keyword scan for this application.",
            ),
        ),
    ]
