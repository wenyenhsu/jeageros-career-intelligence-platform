from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0009_esco_knowledge_base"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="skills.businesscategory",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "business categories",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="MarketCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="skills.marketcategory",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "market categories",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="SkillBusinessCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("SEED", "Seed"),
                            ("MANUAL", "Manual"),
                            ("AUTO", "Auto"),
                            ("SUGGESTED", "Suggested"),
                        ],
                        default="AUTO",
                        max_length=20,
                    ),
                ),
                ("is_approved", models.BooleanField(default=False)),
                ("confidence", models.FloatField(blank=True, null=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="skill_links",
                        to="skills.businesscategory",
                    ),
                ),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="business_category_links",
                        to="skills.skillset",
                    ),
                ),
            ],
            options={
                "ordering": ["category__name", "skill__name"],
            },
        ),
        migrations.CreateModel(
            name="SkillMarketCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("SEED", "Seed"),
                            ("MANUAL", "Manual"),
                            ("AUTO", "Auto"),
                            ("SUGGESTED", "Suggested"),
                        ],
                        default="AUTO",
                        max_length=20,
                    ),
                ),
                ("is_approved", models.BooleanField(default=False)),
                ("confidence", models.FloatField(blank=True, null=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="skill_links",
                        to="skills.marketcategory",
                    ),
                ),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="market_category_links",
                        to="skills.skillset",
                    ),
                ),
            ],
            options={
                "ordering": ["category__name", "skill__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="businesscategory",
            constraint=models.UniqueConstraint(
                fields=("parent", "name"),
                name="unique_business_category_per_parent",
            ),
        ),
        migrations.AddConstraint(
            model_name="marketcategory",
            constraint=models.UniqueConstraint(
                fields=("parent", "name"),
                name="unique_market_category_per_parent",
            ),
        ),
        migrations.AddConstraint(
            model_name="skillbusinesscategory",
            constraint=models.UniqueConstraint(
                fields=("skill", "category"),
                name="unique_skill_business_category",
            ),
        ),
        migrations.AddConstraint(
            model_name="skillmarketcategory",
            constraint=models.UniqueConstraint(
                fields=("skill", "category"),
                name="unique_skill_market_category",
            ),
        ),
    ]
