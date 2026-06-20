# Resume Ollama Tuning

Use this workflow when you have one trusted resume and want to tune Ollama prompts,
JSON schema, aliases, or SkillSet keywords without guessing.

## Pipeline

Resume attachment -> text extraction -> Ollama Extract -> Ollama Verify ->
SkillSet mapping -> Job match -> Market fit -> regression report

## 1. Create a gold file

Copy `docs/examples/resume_gold.example.json` and edit it for the resume:

- `expected`: skills Ollama should verify from the resume.
- `expected_mapped`: expected skills that must map to existing `SkillSet` records.
- `optional`: valid resume skills to monitor without failing the regression.
- `expected_any_of`: concept groups where at least one accepted value must appear.
- `reject`: generic or hallucinated terms that must not survive verification.
- `normalize`: raw variants that should become one canonical name.
- `split`: compound strings that must be split into separate skills.
- `minimum`: simple guardrails such as mapped skill count or job match count.

## 2. Run repeated evaluation

```bash
python src/manage.py eval_resume_ollama path/to/resume.pdf path/to/resume_gold.json --runs 3 --output reports/resume_eval.json
```

With the Docker development stack:

```bash
docker compose exec web python manage.py eval_resume_ollama /app/src/path/to/resume.pdf /app/src/path/to/resume_gold.json --runs 3 --output /app/src/reports/resume_eval.json
```

Use `--fail-on-regression` when this becomes part of a CI or release check.

## 3. Tune only one layer at a time

When the report fails, change one thing and rerun:

- Prompt wording in `apps/skills/services/ollama_extractor.py`
- Verification rules in `apps/skills/services/ollama_verifier.py`
- Canonical `SkillSet` names
- `SkillSet.aliases`
- `SkillKeyword` rows
- Gold expectations when the old expectation was wrong

## 4. What "good" looks like

- All `expected` skills appear in every run.
- All `expected_mapped` skills map to SkillSet in every run.
- Every `expected_any_of` group has at least one accepted skill.
- Optional skills are tracked for stability but do not fail the run by themselves.
- `reject` terms never survive verification.
- Compound terms such as `SQL (MySQL)` are split.
- The unstable skills list is small and explainable.

## 5. Freeze it as a regression test

Keep the gold file under version control if it contains no private resume content.
If the resume is private, keep only the gold JSON in the repo and run the command
locally against the private file.
