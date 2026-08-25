from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0008_application_materials_pack"),
    ]

    operations = [
        migrations.AlterField(
            model_name="application",
            name="priority",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 — Highest"),
                    (2, "2 — High"),
                    (3, "3 — Medium"),
                    (4, "4 — Low"),
                    (5, "5 — Lowest"),
                ],
                default=3,
            ),
        ),
    ]
