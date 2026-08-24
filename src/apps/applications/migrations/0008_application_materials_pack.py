from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0007_application_ats_scan"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="materials_pack",
            field=models.CharField(
                blank=True,
                help_text="Golden resume pack copied into the local materials folder.",
                max_length=16,
            ),
        ),
    ]
