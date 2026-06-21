from apps.analytics.models import SkillDemand, SkillTrend
from apps.analytics.services.skill_demand_service import SkillDemandService
from apps.skills.models import SkillCategory, SkillSet


class ResumeGapService:
    def __init__(self, demand_service=None):
        self.demand_service = demand_service or SkillDemandService()

    def analyze_resume_gap(
        self,
        resume_skill_ids: set[int] | list[int],
        limit: int = 15,
    ) -> dict:
        resume_ids = set(resume_skill_ids or [])
        market_profile = self.demand_service.build_market_profile()

        demand_rows = list(
            SkillDemand.objects.select_related("skill", "skill__trend")
            .order_by("-demand_score", "skill__name")[:limit * 2]
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

        missing_categories = self._missing_categories(resume_ids, market_profile)
        recommended_skills = self._recommended_skills(
            resume_ids,
            missing_high_demand,
            limit=limit,
        )

        return {
            "market_profile": market_profile,
            "missing_high_demand_skills": missing_high_demand,
            "missing_categories": missing_categories,
            "recommended_skills": recommended_skills,
        }

    def _missing_categories(
        self,
        resume_skill_ids: set[int],
        market_profile: dict[str, int],
    ) -> list[dict]:
        missing = []
        for category_name, job_count in market_profile.items():
            category = SkillCategory.objects.filter(name=category_name).first()
            if category is None:
                continue
            resume_category_count = SkillSet.objects.filter(
                id__in=resume_skill_ids,
                categories=category,
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
