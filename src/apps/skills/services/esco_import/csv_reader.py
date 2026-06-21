import csv
import re
from pathlib import Path

COLUMN_ALIASES = {
    "concept_uri": (
        "conceptUri",
        "conceptURI",
        "Concept URI",
        "concept uri",
        "originalSkillUri",
        "originalConceptUri",
    ),
    "preferred_label": (
        "preferredLabel",
        "Concept PT",
        "concept pt",
        "preferredTerm",
        "preferred label",
        "preferred term",
    ),
    "alt_labels": (
        "altLabels",
        "alternativeLabel",
        "alternativeLabels",
        "altLabel",
        "alt labels",
        "alternative labels",
    ),
    "description": (
        "description",
        "definition",
        "Definition",
    ),
    "concept_type": (
        "conceptType",
        "Concept type",
        "concept type",
    ),
    "broader_uri": (
        "broaderUri",
        "broaderURI",
        "broader uri",
    ),
    "related_uri": (
        "relatedSkillUri",
        "relatedUri",
        "relatedConceptUri",
    ),
    "relation_type": (
        "relationType",
        "relation type",
        "relation",
    ),
}

REQUIRED_FIELDS_BY_GROUP = {
    "skills": ("concept_uri", "preferred_label"),
    "skill_groups": ("concept_uri", "preferred_label"),
    "broader_relations": ("concept_uri", "broader_uri"),
    "skill_skill_relations": ("concept_uri", "related_uri"),
}


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def build_header_map(headers: list[str]) -> dict[str, str]:
    alias_lookup = {
        normalize_header(alias): field_name
        for field_name, aliases in COLUMN_ALIASES.items()
        for alias in aliases
    }
    header_map: dict[str, str] = {}
    for header in headers:
        normalized = normalize_header(header)
        field_name = alias_lookup.get(normalized)
        if field_name:
            header_map[field_name] = header
            continue
        for alias_normalized, mapped_name in alias_lookup.items():
            if alias_normalized in normalized or normalized in alias_normalized:
                header_map.setdefault(mapped_name, header)
                break
    return header_map


def read_esco_csv(path: Path, required_fields: tuple[str, ...] | None = None):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        if not reader.fieldnames:
            return [], {}

        headers = [header for header in reader.fieldnames if header]
        header_map = build_header_map(headers)
        if required_fields:
            missing = [field for field in required_fields if field not in header_map]
            if missing:
                raise ValueError(
                    f"{path.name}: missing required columns {missing}. "
                    f"Found headers: {headers}. Mapped: {header_map}"
                )

        rows = [extract_row(row, header_map) for row in reader]
    return rows, header_map


def extract_row(row: dict, header_map: dict[str, str]) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for field_name, header in header_map.items():
        value = row.get(header)
        if value is not None:
            extracted[field_name] = str(value).strip()
    return extracted


def split_alt_labels(value: str) -> list[str]:
    if not value:
        return []
    parts = []
    normalized = value.replace("\r\n", "\n")
    for chunk in normalized.split("\n"):
        for piece in re.split(r"[|;]", chunk):
            text = piece.strip()
            if text:
                parts.append(text)
    return parts
