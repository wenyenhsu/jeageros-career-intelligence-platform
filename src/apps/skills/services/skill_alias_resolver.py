import re

from apps.skills.models import SkillAlias, SkillSet


def normalize_skill_name(raw_name):
    cleaned_name = re.sub(r"\s+", " ", str(raw_name or "")).strip()
    if not cleaned_name:
        return None

    alias = (
        SkillAlias.objects.select_related("skill")
        .filter(alias__iexact=cleaned_name)
        .first()
    )
    if alias:
        return alias.skill

    normalized_name = SkillSet.normalize_name(cleaned_name)
    return SkillSet.objects.filter(normalized_name=normalized_name).first()
