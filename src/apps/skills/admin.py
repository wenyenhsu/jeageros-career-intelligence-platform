from django.contrib import admin

from .models import (
    ApplicationSkill,
    BusinessCategory,
    JobPostSkill,
    MarketCategory,
    SkillAlias,
    SkillBusinessCategory,
    SkillCategory,
    SkillKeyword,
    SkillMarketCategory,
    SkillRelationship,
    SkillSet,
)


class SkillKeywordInline(admin.TabularInline):
    model = SkillKeyword
    extra = 0
    fields = (
        "raw_text",
        "normalized_text",
        "source",
        "status",
        "is_primary",
    )
    readonly_fields = ("normalized_text",)


class SkillAliasInline(admin.TabularInline):
    model = SkillAlias
    extra = 0
    fields = ("alias",)


@admin.register(SkillSet)
class SkillSetAdmin(admin.ModelAdmin):
    inlines = (SkillKeywordInline, SkillAliasInline)
    list_display = (
        "name",
        "normalized_name",
        "has_embedding",
        "is_active",
        "auto_created",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "auto_created")
    search_fields = (
        "name",
        "normalized_name",
        "aliases",
        "skill_aliases__alias",
        "keywords__raw_text",
        "keywords__normalized_text",
    )
    readonly_fields = ("normalized_name", "created_at", "updated_at")

    @admin.display(boolean=True, description="Embedding")
    def has_embedding(self, obj):
        return obj.embedding is not None


@admin.register(SkillKeyword)
class SkillKeywordAdmin(admin.ModelAdmin):
    list_display = (
        "raw_text",
        "normalized_text",
        "skill_set",
        "source",
        "status",
        "is_primary",
        "created_at",
        "updated_at",
    )
    list_filter = ("source", "status", "is_primary")
    search_fields = (
        "raw_text",
        "normalized_text",
        "skill_set__name",
        "skill_set__normalized_name",
    )
    readonly_fields = ("normalized_text", "created_at", "updated_at")
    autocomplete_fields = ("skill_set",)


@admin.register(SkillAlias)
class SkillAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "skill", "created_at", "updated_at")
    search_fields = ("alias", "skill__name", "skill__normalized_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("skill",)


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "parent",
        "esco_uri",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("name", "normalized_name", "esco_uri")
    readonly_fields = ("normalized_name", "created_at", "updated_at")
    autocomplete_fields = ("parent",)


@admin.register(SkillRelationship)
class SkillRelationshipAdmin(admin.ModelAdmin):
    list_display = (
        "source_skill",
        "relationship_type",
        "target_skill",
        "created_at",
        "updated_at",
    )
    list_filter = ("relationship_type",)
    search_fields = (
        "source_skill__name",
        "target_skill__name",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source_skill", "target_skill")


@admin.register(BusinessCategory)
class BusinessCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("parent",)


@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("parent",)


@admin.register(SkillBusinessCategory)
class SkillBusinessCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "skill",
        "category",
        "source",
        "is_approved",
        "confidence",
        "updated_at",
    )
    list_filter = ("source", "is_approved", "category")
    search_fields = ("skill__name", "category__name")
    autocomplete_fields = ("skill", "category")
    actions = ("approve_mappings",)

    @admin.action(description="Approve selected business mappings")
    def approve_mappings(self, request, queryset):
        queryset.update(is_approved=True, source="MANUAL")


@admin.register(SkillMarketCategory)
class SkillMarketCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "skill",
        "category",
        "source",
        "is_approved",
        "confidence",
        "updated_at",
    )
    list_filter = ("source", "is_approved", "category")
    search_fields = ("skill__name", "category__name")
    autocomplete_fields = ("skill", "category")
    actions = ("approve_mappings",)

    @admin.action(description="Approve selected market mappings")
    def approve_mappings(self, request, queryset):
        queryset.update(is_approved=True, source="MANUAL")


@admin.register(JobPostSkill)
class JobPostSkillAdmin(admin.ModelAdmin):
    list_display = (
        "job_post",
        "skill_set",
        "score",
        "source_type",
        "created_at",
        "updated_at",
    )
    list_filter = ("source_type",)
    search_fields = ("job_post__title", "skill_set__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApplicationSkill)
class ApplicationSkillAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "skill_set",
        "score",
        "source_type",
        "created_at",
        "updated_at",
    )
    list_filter = ("source_type",)
    search_fields = ("application__job_post__title", "skill_set__name")
    readonly_fields = ("created_at", "updated_at")
