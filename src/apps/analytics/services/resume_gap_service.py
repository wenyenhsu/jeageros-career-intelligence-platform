from apps.analytics.models import SkillDemand, SkillTrend
from apps.analytics.services.resume_profile_service import ResumeProfileService
from apps.analytics.services.skill_demand_service import SkillDemandService
from apps.skills.models import (
    BusinessCategory,
    MarketCategory,
    SkillBusinessCategory,
    SkillCategory,
    SkillMarketCategory,
    SkillSet,
)


class ResumeGapService:
    def __init__(self, demand_service=None, profile_service=None):
        self.demand_service = demand_service or SkillDemandService()
        self.profile_service = profile_service or ResumeProfileService()

    def analyze_resume_gap(
        self,
        resume_skill_ids: set[int] | list[int],
        limit: int = 15,
    ) -> dict:
        resume_ids = set(resume_skill_ids or [])
        market_profile = self.demand_service.build_market_profile(limit=limit)
        resume_profile = self.profile_service.build_resume_profile(resume_ids)

        demand_rows = list(
            SkillDemand.objects.select_related("skill", "skill__trend")
            .order_by("-demand_score", "skill__name")[: limit * 2]
        )

        missing_high_demand = []
        for row in demand_rows:
            if row.skill_id in resume_ids:
                continue
            trend = getattr(row.skill, "trend", None)
            missing_high_demand.append(
                {
                    "skillset_id": row.skill_id,
                    "name": row.skill.name,
                    "demand_score": row.demand_score,
                    "unique_jobs": row.unique_jobs,
                    "rolling_30_day_count": row.rolling_30_day_count,
                    "trend_type": trend.trend_type if trend else None,
                }
            )
        missing_high_demand = missing_high_demand[:limit]

        missing_categories = self._missing_layer_categories(
            resume_ids,
            market_profile.get("esco_categories", {}),
            SkillCategory,
            SkillSet.objects.filter(id__in=resume_ids),
            relation_field="categories",
        )
        missing_business_categories = self._missing_layer_categories(
            resume_ids,
            market_profile.get("business_categories", {}),
            BusinessCategory,
            SkillSet.objects.filter(id__in=resume_ids),
            link_model=SkillBusinessCategory,
        )
        missing_market_categories = self._missing_layer_categories(
            resume_ids,
            market_profile.get("market_categories", {}),
            MarketCategory,
            SkillSet.objects.filter(id__in=resume_ids),
            link_model=SkillMarketCategory,
        )
        recommended_skills = self._recommended_skills(
            resume_ids,
            missing_high_demand,
            limit=limit,
        )

        return {
            "resume_profile": resume_profile,
            "market_profile": market_profile,
            "missing_high_demand_skills": missing_high_demand,
            "missing_categories": missing_categories,
            "missing_business_categories": missing_business_categories,
            "missing_market_categories": missing_market_categories,
            "missing_skills": missing_high_demand,
            "recommended_skills": recommended_skills,
        }

    def _missing_layer_categories(
        self,
        resume_skill_ids: set[int],
        layer_profile: dict[str, int],
        category_model,
        resume_skills_queryset,
        relation_field: str | None = None,
        link_model=None,
    ) -> list[dict]:
        missing = []
        for category_name, job_count in layer_profile.items():
            category = category_model.objects.filter(name=category_name).first()
            if category is None:
                continue

            if link_model is not None:
                resume_category_count = link_model.objects.filter(
                    skill_id__in=resume_skill_ids,
                    category=category,
                    is_approved=True,
                ).count()
            else:
                resume_category_count = resume_skills_queryset.filter(
                    **{relation_field: category}
                ).count()

            if resume_category_count == 0 and job_count > 0:
                missing.append(
                    {
                        "category": category_name,
                        "market_job_count": job_count,
                        "resume_skill_count": 0,
                    }
                )
        return sorted(
            missing,
            key=lambda item: (-item["market_job_count"], item["category"].casefold()),
        )

    def _recommended_skills(
        self,
        resume_skill_ids: set[int],
        missing_high_demand: list[dict],
        limit: int,
    ) -> list[dict]:
        rising_ids = set(
            SkillTrend.objects.filter(
                trend_type=SkillTrend.TrendType.RISING,
            ).values_list("skill_id", flat=True)
        )
        recommendations = []
        seen = set()

        for item in missing_high_demand:
            skill_id = item["skillset_id"]
            if skill_id in seen:
                continue
            seen.add(skill_id)
            priority = item["demand_score"]
            if skill_id in rising_ids:
                priority += 25
            recommendations.append(
                {
                    **item,
                    "priority_score": round(priority, 2),
                    "is_rising": skill_id in rising_ids,
                }
            )

        recommendations.sort(
            key=lambda row: (-row["priority_score"], row["name"].casefold())
        )
        return recommendations[:limit]
