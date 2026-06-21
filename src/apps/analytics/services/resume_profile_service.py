from apps.skills.services.skill_intelligence.business_category_service import (
    BusinessCategoryService,
)
from apps.skills.services.skill_intelligence.market_category_service import (
    MarketCategoryService,
)


class ResumeProfileService:
    def __init__(
        self,
        business_service=None,
        market_service=None,
    ):
        self.business_service = business_service or BusinessCategoryService()
        self.market_service = market_service or MarketCategoryService()

    def build_resume_profile(
        self,
        resume_skill_ids: set[int] | list[int],
    ) -> dict:
        resume_ids = list(resume_skill_ids or [])
        business_counts = self.business_service.category_counts_for_skills(resume_ids)
        market_counts = self.market_service.category_counts_for_skills(resume_ids)

        return {
            "skill_count": len(resume_ids),
            "business_categories": self._to_percentages(business_counts),
            "market_categories": self._to_percentages(market_counts),
            "business_category_counts": business_counts,
            "market_category_counts": market_counts,
        }

    @staticmethod
    def _to_percentages(counts: dict[str, int]) -> dict[str, int]:
        total = sum(counts.values())
        if total <= 0:
            return {}
        percentages = {
            name: round((count / total) * 100)
            for name, count in counts.items()
        }
        remainder = 100 - sum(percentages.values())
        if remainder and percentages:
            top_category = max(percentages, key=percentages.get)
            percentages[top_category] += remainder
        return dict(
            sorted(percentages.items(), key=lambda item: (-item[1], item[0].casefold()))
        )


def build_resume_profile(resume_skill_ids: set[int] | list[int]) -> dict:
    return ResumeProfileService().build_resume_profile(resume_skill_ids)
