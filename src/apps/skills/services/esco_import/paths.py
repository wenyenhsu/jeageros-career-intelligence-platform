import os
from pathlib import Path

from django.conf import settings

SKILLS_FILE_NAMES = (
    "skills_en.csv",
    "skills.csv",
    "skills_EN.csv",
)
SKILL_GROUPS_FILE_NAMES = (
    "skillGroups_en.csv",
    "skillsGroups_en.csv",
    "skill_groups_en.csv",
    "skills_groups_en.csv",
)
BROADER_RELATIONS_FILE_NAMES = (
    "broaderRelationsSkillPillar.csv",
    "broaderRelationsSkillPillar_en.csv",
    "broaderRealtionsSkillPillar.csv",
)
SKILL_SKILL_RELATIONS_FILE_NAMES = (
    "skillSkillRelations.csv",
    "skillSkillRelations_en.csv",
)

FILE_GROUP_LABELS = {
    "skills": SKILLS_FILE_NAMES,
    "skill_groups": SKILL_GROUPS_FILE_NAMES,
    "broader_relations": BROADER_RELATIONS_FILE_NAMES,
    "skill_skill_relations": SKILL_SKILL_RELATIONS_FILE_NAMES,
}


def default_esco_data_dir() -> Path:
    env_path = os.getenv("ESCO_DATA_DIR")
    if env_path:
        return Path(env_path)
    return Path(settings.ROOT_DIR) / "data" / "esco"


def resolve_esco_file(data_dir: Path, candidates: tuple[str, ...]) -> Path | None:
    if not data_dir.is_dir():
        return None

    for name in candidates:
        path = data_dir / name
        if path.is_file():
            return path

    lowered = {name.casefold(): name for name in candidates}
    for path in sorted(data_dir.rglob("*.csv")):
        if path.name.casefold() in lowered:
            return path

    return None


def discover_esco_files(data_dir: Path) -> dict[str, Path | None]:
    return {
        group: resolve_esco_file(data_dir, names)
        for group, names in FILE_GROUP_LABELS.items()
    }


def format_missing_files(data_dir: Path) -> str:
    discovered = discover_esco_files(data_dir)
    lines = [f"ESCO data directory: {data_dir}"]
    for group, path in discovered.items():
        status = str(path) if path else "NOT FOUND"
        lines.append(f"  {group}: {status}")
    lines.append(
        "Download ESCO v1.2.1 CSV (English, skills pillar + relationships) from "
        "https://esco.ec.europa.eu/en/use-esco/download and extract into the "
        "directory above, or run: python manage.py import_esco --source api"
    )
    return "\n".join(lines)
