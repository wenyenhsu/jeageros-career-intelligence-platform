# Project Progress

Last updated: 2026-06-10

This tracker follows the active roadmap for the Django job tracker. Status values:

- ✅ done
- 🔄 in progress
- ⏳ pending

| Step | Roadmap item | Status | Percentage | Note |
| --- | --- | --- | ---: | --- |
| Step 1 | JobSource CRUD | ✅ done | 100% | JobSource model, admin, CRUD pages, and navigation entry are present. |
| Step 2 | Parser Foundation | ✅ done | 100% | Source detection, listing finder, job extractor, parser registry, and generic fallback parser are present and covered by tests. |
| Step 3 | Sync Pipeline | ✅ done | 100% | Company/job upsert, duplicate prevention, missing-job CLOSED handling, one-click company sync, and API sync are implemented and tested. |
| Step 4 | Celery + Scheduled Crawl | ✅ done | 100% | Celery/Redis scheduling, CrawlRun progress tracking, manual trigger, admin visibility, logging, and crawl APIs are implemented and tested. |
| Step 5 | Ollama Extract | ✅ done | 100% | Ollama extraction returns validated, deduplicated `skills` output with source metadata, logging, and import-service integration; no verification, SkillSet mapping, scoring, or attachment yet. |
| Step 6 | Ollama Verify | ✅ done | 100% | Ollama verification consumes Step 5 candidate skills and returns validated accepted/rejected outputs for later SkillSet mapping. |
| Step 7 | SkillSet Mapping | ✅ done | 100% | Verified skills map to canonical SkillSet records by normalized name or alias, with optional auto-create and attach-ready IDs. |
| Step 8 | Scoring & Attach | ✅ done | 100% | Deterministic skill scoring and scored SkillSet attachment to JobPost/Application through models are implemented and tested. |
| Step 9 | Analytics | ✅ done | 100% | Skill demand analytics services, filters, pages, DRF endpoints, trends, company breakdowns, and gap analysis are implemented and tested. |
| Step 10 | Monitoring & Logs | ✅ done | 100% | Persistent pipeline logs, admin visibility, monitoring page, API status/log endpoints, and service instrumentation are implemented and tested. |

## Current Note

Step 10 is complete. The roadmap is implemented through monitoring and logs, with persistent operational visibility across crawl, sync, skill pipeline, analytics, and task execution.
