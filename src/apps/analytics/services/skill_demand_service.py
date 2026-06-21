import logging
from datetime import timedelta

from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from apps.analytics.models import SkillDemand, SkillTrend
from apps.skills.models import (
    BusinessCategory,
    JobPostSkill,
    MarketCategory,
    SkillBusinessCategory,
    SkillCategory,
    SkillMarketCategory,
    SkillSet,
)

logger = logging.getLogger(__name__)

CATEGORY_AI_ML = "AI / ML"
CATEGORY_CLOUD = "Cloud Computing"
CATEGORY_DATA = "Data Engineering"
CATEGORY_DEVOPS = "DevOps"
CATEGORY_BACKEND = "Backend Engineering"

RISING_THRESHOLD = 1.25
DECLINING_THRESHOLD = 0.75


class SkillDemandService:
    review_threshold = 5

    def update_skill_demand(self) -> dict[str, int]:
        now = timezone.now()
        window_30 = now - timedelta(days=30)
        window_90 = now - timedelta(days=90)

        aggregates = (
            JobPostSkill.objects.values("skill_set_id")
            .annotate(
                total_occurrences=Count("id"),
                unique_jobs=Count("job_post_id", distinct=True),
                first_seen=Min("created_at"),
                last_seen=Max("created_at"),
                rolling_30_day_count=Count(
                    "job_post_id",
                    distinct=True,
                    filter=Q(created_at__gte=window_30),
                ),
                rolling_90_day_count=Count(
                    "job_post_id",
                    distinct=True,
                    filter=Q(created_at__gte=window_90),
                ),
            )
        )

        updated = 0
        trends_updated = 0
        skill_ids_seen = set()

        for row in aggregates:
            skill_id = row["skill_set_id"]
            skill_ids_seen.add(skill_id)
            rolling_30 = row["rolling_30_day_count"] or 0
            rolling_90 = row["rolling_90_day_count"] or 0
            unique_jobs = row["unique_jobs"] or 0

            growth_ratio = self._growth_ratio(rolling_30, rolling_90)
            trend_type = self._trend_type(rolling_30, rolling_90, growth_ratio)
            demand_score = self._demand_score(
                unique_jobs=unique_jobs,
                rolling_30=rolling_30,
                growth_ratio=growth_ratio,
            )

            SkillDemand.objects.update_or_create(
                skill_id=skill_id,
                defaults={
                    "total_occurrences": row["total_occurrences"] or 0,
                    "unique_jobs": unique_jobs,
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "rolling_30_day_count": rolling_30,
                    "rolling_90_day_count": rolling_90,
                    "demand_score": demand_score,
                },
            )
            updated += 1

            _, created = SkillTrend.objects.update_or_create(
                skill_id=skill_id,
                defaults={
                    "trend_type": trend_type,
                    "growth_ratio": round(growth_ratio, 4),
                },
            )
            if created or not created:
                trends_updated += 1

        stale = SkillDemand.objects.exclude(skill_id__in=skill_ids_seen).delete()

        logger.info(
            "Skill demand updated: records=%s trends=%s stale_removed=%s",
            updated,
            trends_updated,
            stale[0],
        )
        return {
            "demand_records": updated,
            "trend_records": trends_updated,
            "stale_removed": stale[0],
        }

    def build_market_profile(self, limit: int = 10) -> dict:
        business_counts = self._job_counts_by_business_category()
        market_counts = self._job_counts_by_market_category()
        esco_counts = self._job_counts_by_esco_category()

        return {
            "top_skills": self.top_skills(limit=limit),
            "top_business_categories": self._serialize_category_counts(
                business_counts,
                limit=limit,
            ),
            "top_market_categories": self._serialize_category_counts(
                market_counts,
                limit=limit,
            ),
            "fastest_growing_skills": self.fastest_growing_skills(limit=limit),
            "emerging_skills": self.top_emerging_skills(limit=limit),
            "business_categories": business_counts,
            "market_categories": market_counts,
            "esco_categories": esco_counts,
            # Backward-compatible flat profile used by older gap analysis callers.
            "market_profile": esco_counts,
        }

    def build_legacy_category_profile(self) -> dict[str, int]:
        return self._job_counts_by_esco_category()

    def _job_counts_by_business_category(self) -> dict[str, int]:
        return self._job_counts_for_mapping(
            BusinessCategory,
            SkillBusinessCategory,
        )

    def _job_counts_by_market_category(self) -> dict[str, int]:
        return self._job_counts_for_mapping(
            MarketCategory,
            SkillMarketCategory,
        )

    def _job_counts_by_esco_category(self) -> dict[str, int]:
        profile: dict[str, int] = {}
        categories = SkillCategory.objects.filter(is_active=True).order_by("name")
        for category in categories:
            count = (
                JobPostSkill.objects.filter(skill_set__categories=category)
                .values("job_post_id")
                .distinct()
                .count()
            )
            if count:
                profile[category.name] = count
        return dict(
            sorted(profile.items(), key=lambda item: (-item[1], item[0].casefold()))
        )

    @staticmethod
    def _job_counts_for_mapping(category_model, link_model):
        profile: dict[str, int] = {}
        categories = category_model.objects.filter(is_active=True).order_by("name")
        for category in categories:
            if link_model is SkillBusinessCategory:
                count = (
                    JobPostSkill.objects.filter(
                        skill_set__business_category_links__category=category,
                        skill_set__business_category_links__is_approved=True,
                    )
                    .values("job_post_id")
                    .distinct()
                    .count()
                )
            elif link_model is SkillMarketCategory:
                count = (
                    JobPostSkill.objects.filter(
                        skill_set__market_category_links__category=category,
                        skill_set__market_category_links__is_approved=True,
                    )
                    .values("job_post_id")
                    .distinct()
                    .count()
                )
            else:
                count = 0
            if count:
                profile[category.name] = count
        return dict(
            sorted(profile.items(), key=lambda item: (-item[1], item[0].casefold()))
        )

    @staticmethod
    def _serialize_category_counts(profile: dict[str, int], limit: int = 10) -> list[dict]:
        total = sum(profile.values())
        rows = []
        for name, count in list(profile.items())[:limit]:
            rows.append(
                {
                    "category": name,
                    "job_count": count,
                    "share_percent": SkillDemandService._percentage(count, total),
                }
            )
        return rows

    @staticmethod
    def _percentage(part, total):
        return round((part / total) * 100, 1) if total else 0

    def top_skills(self, limit: int = 10) -> list[dict]:
        rows = SkillDemand.objects.select_related("skill").order_by(
            "-demand_score", "skill__name"
        )[:limit]
        return [self._serialize_demand(row) for row in rows]

    def top_emerging_skills(self, limit: int = 10) -> list[dict]:
        rows = (
            SkillTrend.objects.select_related("skill", "skill__demand")
            .filter(trend_type=SkillTrend.TrendType.RISING)
            .order_by("-growth_ratio", "-skill__demand__rolling_30_day_count")[:limit]
        )
        return [self._serialize_trend(row) for row in rows]

    def fastest_growing_skills(self, limit: int = 10) -> list[dict]:
        rows = SkillTrend.objects.select_related("skill", "skill__demand").order_by(
            "-growth_ratio", "-skill__demand__rolling_30_day_count"
        )[:limit]
        return [self._serialize_trend(row) for row in rows]

    def trending_skills(self, limit: int = 10, trend_type: str | None = None) -> list[dict]:
        qs = SkillTrend.objects.select_related("skill", "skill__demand")
        if trend_type:
            qs = qs.filter(trend_type=trend_type)
        rows = qs.order_by("-growth_ratio", "-skill__demand__demand_score")[:limit]
        return [self._serialize_trend(row) for row in rows]

    def top_categories(self, limit: int = 10) -> list[dict]:
        profile = self.build_legacy_category_profile()
        return [
            {"category": name, "job_count": count}
            for name, count in list(profile.items())[:limit]
        ]

    def skills_for_category(self, category_name: str, limit: int = 10) -> list[dict]:
        category = SkillCategory.objects.filter(name__iexact=category_name).first()
        if category is None:
            return []

        skill_ids = (
            JobPostSkill.objects.filter(skill_set__categories=category)
            .values_list("skill_set_id", flat=True)
            .distinct()
        )
        rows = (
            SkillDemand.objects.select_related("skill")
            .filter(skill_id__in=skill_ids)
            .order_by("-demand_score", "skill__name")[:limit]
        )
        return [self._serialize_demand(row) for row in rows]

    def most_requested_ai_skills(self, limit: int = 10) -> list[dict]:
        return self.skills_for_category(CATEGORY_AI_ML, limit=limit)

    def most_requested_cloud_skills(self, limit: int = 10) -> list[dict]:
        return self.skills_for_category(CATEGORY_CLOUD, limit=limit)

    def most_requested_data_skills(self, limit: int = 10) -> list[dict]:
        return self.skills_for_category(CATEGORY_DATA, limit=limit)

    @classmethod
    def _growth_ratio(cls, rolling_30: int, rolling_90: int) -> float:
        if rolling_90 <= 0:
            return 1.0 if rolling_30 <= 0 else 2.0
        prior_window = max(rolling_90 - rolling_30, 0)
        recent_rate = rolling_30 / 30.0
        if prior_window > 0:
            baseline_rate = prior_window / 60.0
        else:
            baseline_rate = rolling_90 / 90.0
        if baseline_rate <= 0:
            return 2.0 if rolling_30 > 0 else 1.0
        return recent_rate / baseline_rate

    @classmethod
    def _trend_type(cls, rolling_30: int, rolling_90: int, growth_ratio: float) -> str:
        if rolling_30 > 0 and rolling_90 <= rolling_30:
            return SkillTrend.TrendType.RISING
        if growth_ratio >= RISING_THRESHOLD:
            return SkillTrend.TrendType.RISING
        if growth_ratio <= DECLINING_THRESHOLD:
            return SkillTrend.TrendType.DECLINING
        return SkillTrend.TrendType.STABLE

    @classmethod
    def _demand_score(
        cls,
        unique_jobs: int,
        rolling_30: int,
        growth_ratio: float,
    ) -> float:
        score = unique_jobs + (rolling_30 * 2) + (growth_ratio * 10)
        return round(score, 2)

    @staticmethod
    def _serialize_demand(row: SkillDemand) -> dict:
        return {
            "skillset_id": row.skill_id,
            "name": row.skill.name,
            "total_occurrences": row.total_occurrences,
            "unique_jobs": row.unique_jobs,
            "rolling_30_day_count": row.rolling_30_day_count,
            "rolling_90_day_count": row.rolling_90_day_count,
            "demand_score": row.demand_score,
            "first_seen": SkillDemandService._serialize_datetime(row.first_seen),
            "last_seen": SkillDemandService._serialize_datetime(row.last_seen),
        }

    @staticmethod
    def _serialize_datetime(value):
        return value.isoformat() if value is not None else None

    @staticmethod
    def _serialize_trend(row: SkillTrend) -> dict:
        demand = getattr(row.skill, "demand", None)
        payload = {
            "skillset_id": row.skill_id,
            "name": row.skill.name,
            "trend_type": row.trend_type,
            "growth_ratio": row.growth_ratio,
        }
        if demand is not None:
            payload.update(
                {
                    "demand_score": demand.demand_score,
                    "rolling_30_day_count": demand.rolling_30_day_count,
                    "rolling_90_day_count": demand.rolling_90_day_count,
                    "unique_jobs": demand.unique_jobs,
                }
            )
        return payload


def update_skill_demand() -> dict[str, int]:
    return SkillDemandService().update_skill_demand()


def build_market_profile(limit: int = 10) -> dict:
    return SkillDemandService().build_market_profile(limit=limit)
