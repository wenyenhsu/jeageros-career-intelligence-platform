from django.db import migrations, models


def ensure_job_type_column(apps, schema_editor):
    table_name = "jobs_jobpost"
    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }

    if "job_type" not in existing_columns:
        JobPost = apps.get_model("jobs", "JobPost")
        field = models.CharField(blank=True, default="", max_length=100)
        field.set_attributes_from_name("job_type")
        schema_editor.add_field(JobPost, field)

    schema_editor.execute("""
        UPDATE jobs_jobpost
        SET job_type = COALESCE(NULLIF(job_type, ''), NULLIF(employment_type, ''), '')
        """)

    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "ALTER TABLE jobs_jobpost ALTER COLUMN job_type SET DEFAULT ''"
        )
        schema_editor.execute(
            "ALTER TABLE jobs_jobpost ALTER COLUMN job_type SET NOT NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0004_jobpost_skill_sets"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_job_type_column,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="jobpost",
                    name="job_type",
                    field=models.CharField(blank=True, default="", max_length=100),
                ),
            ],
        ),
    ]
