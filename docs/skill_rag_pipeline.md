# Skill RAG Pipeline

The skill RAG pipeline maps raw extracted skills to canonical `SkillSet`
records without allowing the model to invent new skill names.

## Architecture

```text
Raw Skill
  -> Alias Resolver
  -> Exact SkillSet Match
  -> Vector Retrieval
  -> Candidate Skills
  -> Ollama Verification
  -> Confidence Validation
  -> Canonical Skill
```

## Resolution Rules

1. `SkillAlias` exact match short-circuits with confidence `1.0`.
2. `SkillSet.normalized_name` exact match short-circuits with confidence `1.0`.
3. pgvector retrieves the top candidate `SkillSet` records by cosine similarity.
4. Ollama receives only the retrieved candidate names and must select from them.
5. Results below confidence `0.80` are rejected with `canonical = None`.

## Prompt Shape

```text
Known Candidate Skills:
["PostgreSQL", "MySQL", "MongoDB", "SQLite"]

Input Skill:
"Postgres"

Rules:
- Select only from Known Candidate Skills.
- Do not invent new canonical skills.
- Return valid JSON only.
- If confidence is low, return canonical as null.
```

Expected JSON:

```json
{
  "original": "Postgres",
  "canonical": "PostgreSQL",
  "confidence": 0.99,
  "reason": "Alias + semantic similarity"
}
```

## Integration Examples

### JobPost Skill Extraction

```python
from apps.skills.services import SkillRAGPipeline

pipeline = SkillRAGPipeline()
mapping_results = pipeline.map_skills(["Postgres", "Django REST API"])
```

### Resume Skill Extraction

```python
from apps.skills.services import SkillRAGPipeline

resume_keywords = ["SQL (MySQL)", "PyTorch", "Linux administration"]
mapping_results = SkillRAGPipeline().map_skills(resume_keywords)
```

### Analytics Modules

```python
from apps.skills.services import SkillRAGPipeline

market_terms = ["cloud function service", "document database"]
canonical_terms = [
    result.canonical
    for result in SkillRAGPipeline().map_skills(market_terms)
    if result.canonical
]
```
