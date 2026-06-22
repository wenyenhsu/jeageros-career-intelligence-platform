# Project Progress

Last updated: 2026-06-21

This tracker follows the active roadmap for the Django job tracker. Status values:

- ✅ done
- 🔄 in progress
- ⏳ pending

| Step | Roadmap item | Status | Percentage | Note |
| --- | --- | --- | ---: | --- |
| Step 1 | JobSource CRUD | ✅ done | 100% | JobSource model, admin, CRUD pages, and navigation entry are present. |
| Step 2 | Parser Foundation | ✅ done | 100% | Source-specific parsers return raw data for LinkedIn, Handshake, Greenhouse, Lever, career sites, RSS, APIs, and generic HTML; JobNormalizer converts them to a canonical payload before sync/LLM. |
| Step 3 | Sync Pipeline | ✅ done | 100% | Company/job upsert, duplicate prevention, missing-job CLOSED handling, one-click company sync, and API sync are implemented and tested. |
| Step 4 | Celery + Scheduled Crawl | ✅ done | 100% | Celery/Redis scheduling, CrawlRun progress tracking, manual trigger, admin visibility, logging, and crawl APIs are implemented and tested. |
| Step 5 | Ollama Extract | ✅ done | 100% | Ollama extraction returns validated, deduplicated `skills` output with source metadata, logging, and import-service integration; no verification, SkillSet mapping, scoring, or attachment yet. |
| Step 6 | Ollama Verify | ✅ done | 100% | Ollama verification consumes Step 5 candidate skills and returns validated accepted/rejected outputs for later SkillSet mapping. |
| Step 7 | SkillSet Mapping | ✅ done | 100% | Verified skills map to canonical SkillSet records by normalized name or alias, with optional auto-create and attach-ready IDs. |
| Step 8 | Scoring & Attach | ✅ done | 100% | Deterministic skill scoring and scored SkillSet attachment to JobPost/Application through models are implemented and tested. |
| Step 9 | Analytics | ✅ done | 100% | Skill demand analytics services, filters, pages, DRF endpoints, trends, company breakdowns, and gap analysis are implemented and tested. |
| Step 10 | Monitoring & Logs | ✅ done | 100% | Persistent pipeline logs, admin visibility, monitoring page, API status/log endpoints, and service instrumentation are implemented and tested. |
| Step 11 | ESCO Knowledge Base Import | ✅ done | 100% | ESCO CSV/API import pipeline is implemented for `SkillSet`, `SkillAlias`, `SkillCategory`, and `SkillRelationship`, including validation tooling and import performance improvements. |
| Step 12 | US Emerging Skills & Demand Intelligence | ✅ done | 100% | US emerging skills seed is in place; `SkillDemand`, `SkillTrend`, and `SkillCandidate` analytics are implemented with update command, crawl hook integration, and demand APIs. |
| Step 13 | Skill Intelligence Layers | ✅ done | 100% | Three-layer model is implemented: Canonical (`SkillSet`), Business (`BusinessCategory`), and Market (`MarketCategory`) with assign/suggest services, seed commands, and manual approval support. |
| Step 14 | Resume/Market Intelligence Expansion | ✅ done | 100% | `build_resume_profile()`, layered market profile aggregation, and enhanced gap analysis are implemented with business/market missing-category outputs and recommendations. |
| Step 15 | Market Fit v1 + Job Status UX | ✅ done | 100% | Demand-weighted semantic Market Fit (pgvector similarity) is implemented with debug rows and UI tooltip; Job status now supports `APPLIED` with application-driven status sync and dashboard visualization updates. |

## Current Note

Core pipeline and intelligence layers are now operational. The end-to-end flow is:

`Source -> SourceDetector -> source parser -> JobNormalizer -> CanonicalJobPayload -> Sync -> Ollama Extract -> Ollama Verify -> SkillSet Mapping -> Scoring -> Analytics`

Additional intelligence layers now sit on top of this pipeline:

- Canonical skill knowledge base (ESCO-backed)
- Business taxonomy layer (JagerOS classification)
- Market taxonomy layer (market classification)
- Demand-weighted semantic Market Fit for resume analysis
