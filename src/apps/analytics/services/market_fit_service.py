from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db.models import Count
from pgvector.django import CosineDistance

from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillSet

logger = logging.getLogger(__name__)

MATCHED_SIMILARITY_THRESHOLD = 0.7


@dataclass(frozen=True)
class MarketFitRow:
    resume_skill_id: int
    resume_skill_name: str
    best_match_id: int | None
    best_match_name: str
    similarity: float
    demand: int

    def as_dict(self):
        return {
            "resume_skill_id": self.resume_skill_id,
            "resume_skill": self.resume_skill_name,
            "best_match_id": self.best_match_id,
            "best_match": self.best_match_name,
            "similarity": round(self.similarity, 4),
            "demand": self.demand,
        }


class MarketFitService:
    def __init__(self, matched_similarity_threshold=MATCHED_SIMILARITY_THRESHOLD):
        self.matched_similarity_threshold = matched_similarity_threshold

    def calculate(
        self,
        resume_skill_ids: set[int] | list[int],
        top_demand_limit: int = 10,
    ) -> dict:
        resume_ids = {skill_id for skill_id in (resume_skill_ids or []) if skill_id}
        demand_map = self.active_market_demand()
        market_skill_ids = set(demand_map.keys())

        if not resume_ids or not market_skill_ids:
            return self._empty_result(demand_map, top_demand_limit)

        resume_skills = list(
            SkillSet.objects.filter(id__in=resume_ids, is_active=True).order_by("name")
        )
        market_embedding_ids = set(
            SkillSet.objects.filter(
                id__in=market_skill_ids,
                embedding__isnull=False,
            ).values_list("id", flat=True)
        )

        rows: list[MarketFitRow] = []
        for resume_skill in resume_skills:
            best_match, similarity = self._best_market_match(
                resume_skill,
                market_embedding_ids,
                demand_map,
            )
            demand = demand_map.get(best_match.id, 0) if best_match is not None else 0
            rows.append(
                MarketFitRow(
                    resume_skill_id=resume_skill.id,
                    resume_skill_name=resume_skill.name,
                    best_match_id=best_match.id if best_match is not None else None,
                    best_match_name=best_match.name if best_match is not None else "-",
                    similarity=similarity,
                    demand=demand,
                )
            )

        weighted_scores = [
            (row.demand, row.similarity)
            for row in rows
            if row.demand > 0
        ]
        market_fit_ratio = self._weighted_mean(weighted_scores)
        market_fit_percent = round(market_fit_ratio * 100, 1)

        matched_skills = self._matched_skills(rows)
        missing_skills = self._missing_market_skills(
            resume_skills,
            demand_map,
        )
        top_skill_demand = self._top_skill_demand(demand_map, limit=top_demand_limit)
        debug_rows = [row.as_dict() for row in rows]

        logger.info(
            "Market fit v1 calculated: score=%s resume_skills=%s market_skills=%s rows=%s",
            market_fit_percent,
            len(resume_skills),
            len(market_skill_ids),
            debug_rows,
        )

        return {
            "market_fit": market_fit_percent,
            "fit_percent": market_fit_percent,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "top_skill_demand": top_skill_demand,
            "debug_rows": debug_rows,
            "formula": "demand_weighted_semantic",
            "covered": matched_skills,
            "missing": missing_skills,
        }

    @staticmethod
    def active_market_demand() -> dict[int, int]:
        rows = (
            JobPostSkill.objects.filter(
                job_post__status=JobPost.StatusChoices.ACTIVE,
            )
            .values("skill_set_id")
            .annotate(demand=Count("id"))
            .order_by("-demand", "skill_set_id")
        )
        return {row["skill_set_id"]: row["demand"] for row in rows if row["demand"]}

    def _best_market_match(
        self,
        resume_skill: SkillSet,
        market_embedding_ids: set[int],
        demand_map: dict[int, int],
    ) -> tuple[SkillSet | None, float]:
        if resume_skill.id in demand_map:
            return resume_skill, 1.0

        if resume_skill.embedding is None or not market_embedding_ids:
            return None, 0.0

        best = (
            SkillSet.objects.filter(
                id__in=market_embedding_ids,
                embedding__isnull=False,
            )
            .annotate(distance=CosineDistance("embedding", resume_skill.embedding))
            .order_by("distance", "name")
            .first()
        )
        if best is None:
            return None, 0.0

        similarity = self._similarity_from_distance(float(best.distance))
        return best, similarity

    def _missing_market_skills(
        self,
        resume_skills: list[SkillSet],
        demand_map: dict[int, int],
    ) -> list[dict]:
        resume_ids = {skill.id for skill in resume_skills}
        missing = []

        ranked_market_ids = sorted(
            demand_map.keys(),
            key=lambda skill_id: (-demand_map[skill_id], skill_id),
        )
        market_skills = {
            skill.id: skill
            for skill in SkillSet.objects.filter(id__in=ranked_market_ids)
        }

        for skill_id in ranked_market_ids:
            if skill_id in resume_ids:
                continue

            market_skill = market_skills.get(skill_id)
            if market_skill is None:
                continue

            best_similarity = self._max_similarity_to_market(
                market_skill,
                resume_skills,
                resume_ids,
            )
            if best_similarity >= self.matched_similarity_threshold:
                continue

            missing.append(
                {
                    "skillset_id": market_skill.id,
                    "name": market_skill.name,
                    "demand": demand_map[skill_id],
                    "best_similarity": round(best_similarity, 4),
                }
            )
        return missing

    def _max_similarity_to_market(
        self,
        market_skill: SkillSet,
        resume_skills: list[SkillSet],
        resume_ids: set[int],
    ) -> float:
        if market_skill.id in resume_ids:
            return 1.0
        if not resume_skills:
            return 0.0
        return max(
            self._similarity_between(resume_skill, market_skill)
            for resume_skill in resume_skills
        )

    def _similarity_between(
        self,
        resume_skill: SkillSet,
        market_skill: SkillSet,
    ) -> float:
        if resume_skill.id == market_skill.id:
            return 1.0
        if resume_skill.embedding is None or market_skill.embedding is None:
            return 0.0

        match = (
            SkillSet.objects.filter(id=market_skill.id)
            .annotate(distance=CosineDistance("embedding", resume_skill.embedding))
            .first()
        )
        if match is None:
            return 0.0
        return self._similarity_from_distance(float(match.distance))

    def _matched_skills(self, rows: list[MarketFitRow]) -> list[dict]:
        matched = []
        for row in rows:
            if row.similarity < self.matched_similarity_threshold:
                continue
            matched.append(
                {
                    "skillset_id": row.resume_skill_id,
                    "name": row.resume_skill_name,
                    "best_match_id": row.best_match_id,
                    "best_match": row.best_match_name,
                    "similarity": round(row.similarity, 4),
                    "demand": row.demand,
                }
            )
        return matched

    @staticmethod
    def _top_skill_demand(demand_map: dict[int, int], limit: int = 10) -> list[dict]:
        skill_ids = list(demand_map.keys())
        names = dict(
            SkillSet.objects.filter(id__in=skill_ids).values_list("id", "name")
        )
        rows = []
        for skill_id in sorted(
            skill_ids,
            key=lambda value: (-demand_map[value], names.get(value, "").casefold()),
        )[:limit]:
            rows.append(
                {
                    "skillset_id": skill_id,
                    "name": names.get(skill_id, f"Skill #{skill_id}"),
                    "demand": demand_map[skill_id],
                }
            )
        return rows

    @staticmethod
    def _weighted_mean(scores: list[tuple[int, float]]) -> float:
        total_weight = sum(weight for weight, _ in scores)
        if total_weight <= 0:
            return 0.0
        weighted_sum = sum(weight * similarity for weight, similarity in scores)
        return max(0.0, min(1.0, weighted_sum / total_weight))

    @staticmethod
    def _similarity_from_distance(distance: float) -> float:
        return max(0.0, min(1.0, 1.0 - distance))

    def _empty_result(self, demand_map: dict[int, int], top_demand_limit: int) -> dict:
        return {
            "market_fit": 0.0,
            "fit_percent": 0.0,
            "matched_skills": [],
            "missing_skills": [],
            "top_skill_demand": self._top_skill_demand(
                demand_map,
                limit=top_demand_limit,
            ),
            "debug_rows": [],
            "formula": "demand_weighted_semantic",
            "covered": [],
            "missing": [],
        }


def calculate_market_fit(
    resume_skill_ids: set[int] | list[int],
    top_demand_limit: int = 10,
) -> dict:
    return MarketFitService().calculate(
        resume_skill_ids,
        top_demand_limit=top_demand_limit,
    )
