from django.db import migrations
from django.utils import timezone


LEGACY_TABLES = (
    (
        "jobs_jobpost_skill_sets",
        "JobPostSkill",
        "jobpost_id",
        "job_post_id",
    ),
    (
        "applications_application_skill_sets",
        "ApplicationSkill",
        "application_id",
        "application_id",
    ),
)


def _table_exists(schema_editor, table_name):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        return table_name in connection.introspection.table_names(cursor)


def migrate_legacy_skill_links(apps, schema_editor):
    now = timezone.now()
    quote_name = schema_editor.quote_name

    for legacy_table, through_model_name, legacy_parent_column, parent_field in (
        LEGACY_TABLES
    ):
        if not _table_exists(schema_editor, legacy_table):
            continue

        through_model = apps.get_model("skills", through_model_name)
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT {parent_column}, skillset_id FROM {legacy_table}".format(
                    parent_column=quote_name(legacy_parent_column),
                    legacy_table=quote_name(legacy_table),
                )
            )
            rows = cursor.fetchall()

        for parent_id, skill_set_id in rows:
            through_model.objects.get_or_create(
                **{
                    parent_field: parent_id,
                    "skill_set_id": skill_set_id,
                },
                defaults={
                    "score": 0,
                    "source_type": "MANUAL",
                    "extraction_metadata": {"migrated_from": legacy_table},
                    "created_at": now,
                    "updated_at": now,
                },
            )


def drop_legacy_skill_tables(apps, schema_editor):
    quote_name = schema_editor.quote_name
    cascade = " CASCADE" if schema_editor.connection.vendor == "postgresql" else ""

    for legacy_table, *_ in LEGACY_TABLES:
        if not _table_exists(schema_editor, legacy_table):
            continue
        schema_editor.execute(f"DROP TABLE {quote_name(legacy_table)}{cascade}")


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0003_application_skill_sets"),
        ("jobs", "0005_jobpost_job_type_compat"),
        ("skills", "0005_skillkeyword"),
    ]

    operations = [
        migrations.RunPython(
            migrate_legacy_skill_links,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            drop_legacy_skill_tables,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
