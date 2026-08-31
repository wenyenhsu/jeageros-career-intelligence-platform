# Assistant memory index

Corpus for **assistant-memory RAG** (retrieve matching `memory/*.md`). Separate from SkillSet / ESCO / pgvector skill RAG.

Read this index, then open only the files that match the current task. On a user correction, add a short file and update this list. Do not write secrets or token values.

## Project rules

- [Memory RAG vs skill knowledge base](project_memory-rag-separate.md) — Retrieve `memory/*.md` for assistant rules; never use SkillSet embeddings for this.
- [ATS vs Market Fit](project_ats-vs-market-fit.md) — ATS is literal JD keyword match; not SkillSet, Market Fit, embeddings, or pgvector.
- [Interstride token](project_interstride-token.md) — Token lives only in `.env` as `INTERSTRIDE_AUTH_TOKEN`, never in crawl config.
- [Create Application cover letter](project_create-cover-letter.md) — Create rewrites the copied cover letter; resume is left for ATS scan.

## Feedback (corrected workflow)

- [Docker manage.py](feedback_docker-manage-py.md) — Run `python manage.py` inside Docker (`DB_HOST=db`); host Python hits the wrong DB.

## Reference

- [Materials pack](reference_materials-pack.md) — Pack copies golden templates; it does not move them. Application list hides Drive.

## User preferences

- [Traditional Chinese](user_traditional-chinese.md) — Reply in Traditional Chinese when the user writes in Traditional Chinese. (gitignored)
