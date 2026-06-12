# AGENTS.md

## Project Goal

This project is a Django-based job tracking system with the following core direction:

- Scheduled automatic job crawling
- Company as the parent entity
- Job filtering by target companies, keywords, location, and remote
- Auto upsert Company before creating or updating JobPost
- Admin-managed data sources / resources
- One-click sync for already stored jobs
- Shared SkillSet between JobPost and Application
- Manual SkillSet maintenance is allowed
- `tags` are personal notes only and are unrelated to SkillSet
- Skill extraction is fully automated using Ollama
- Extracted keywords are used for technical analysis and analytics

## Current Feature Set

1. Scheduled automatic job crawling
2. Company is the parent entity
3. Job filters for keywords, location, and remote
4. Auto upsert Company
5. Resource/source management is done in admin
6. Existing jobs support one-click refresh/sync
7. JobPost and Application share the same SkillSet system
8. SkillSet must remain manually maintainable
9. `tags` are only personal notes and must not be mixed with SkillSet
10. Skill extraction uses Ollama
11. Keywords are used for technical requirement analysis
12. Skill extraction pipeline is fully automated:
   - Ollama Extract
   - Ollama Verify
   - SkillSet Mapping
   - Automatic scoring
   - Attach to JobPost/Application
   - Analytics consumption
13. Crawl output is normalized into one canonical job payload before sync, LLM, scoring, or analytics.

## Architecture Rules

### Data model rules
- `Company` is the parent entity.
- `JobPost.company` must always exist.
- `Application` is linked to `JobPost`.
- `SkillSet` is a shared master table used by both `JobPost` and `Application`.
- `tags` are personal annotations only.
- Do not conflate `tags` with `SkillSet`.
- Keep `SkillSet` normalized and deduplicated.
- If needed, preserve aliases or alternate names in `SkillSet`.
- Keep extracted skill data separate from raw source text.

### Source / crawling rules
- `JobSource` stores crawl configuration.
- Source/resource selection is an admin-level concern.
- Support multiple source types, not only LinkedIn.
- Parser architecture must support:
  - source detection
  - listing page discovery
  - job detail extraction
  - normalization
  - company upsert
  - job upsert / sync
- Canonical crawl flow:
  - Source
  - SourceDetector
  - Source-specific parser that returns raw source data
  - JobNormalizer
  - CanonicalJobPayload
  - Sync Pipeline
  - Ollama Extract
  - Ollama Verify
  - SkillSet Mapping
  - Scoring
  - Analytics
- Parsers are responsible only for fetch, parse, and extract.
- Do not normalize inside individual parsers.
- Downstream sync, LLM, scoring, and analytics code must consume the canonical job payload instead of source-specific parser output.
- Already stored jobs must support update/sync.
- When a job disappears from the source, mark it inactive/closed instead of deleting it unless explicitly required.

### Skill extraction rules
- Use Ollama as the only extraction mechanism.
- Do not use rule-based keyword matching as the primary extraction method.
- The extraction pipeline should be:
  1. Extract candidate skills with Ollama
  2. Verify with Ollama
  3. Map to existing SkillSet records
  4. Compute automatic score
  5. Save to JobPost / Application
- Do not rely on manual review as part of the default pipeline.
- If a new skill appears, only create it when the automated pipeline is confident enough.
- Keep extracted keywords suitable for later analytics and technical-demand analysis.

### UI / page rules
- The project should include a page for crawl settings / job source settings.
- The user should be able to configure:
  - target companies
  - job categories
  - include keywords
  - exclude keywords
  - location
  - remote-only filters
- Resource/source type itself should be managed at the admin/system level, not as a general user dropdown.

## Development Priorities

When continuing development, work in this order:

### Step 1: Crawl source foundation
- JobSource model
- Source admin
- Source CRUD page
- Base navbar entry
- Source mapping and compatibility with existing DB schema

### Step 2: Parser foundation
- SourceDetector
- ListingFinder
- JobExtractor
- Parser registry
- Generic fallback parser for non-LinkedIn sources
- Source-specific parsers return raw payloads only
- JobNormalizer converts all sources into CanonicalJobPayload before downstream processing

### Step 3: Sync pipeline
- Company upsert
- Job upsert / update
- External ID / source URL matching
- Inactive/closed job handling
- One-click sync action

### Step 4: Skill extraction pipeline
- Ollama extraction
- Ollama verification
- SkillSet mapping
- Automatic scoring
- Attach skills to JobPost and Application

### Step 5: Analytics
- Extracted keyword analysis
- Top skills over time
- Company-level skill trends
- Job-type skill analysis
- Skill gap analysis

## Code Style Rules

- Keep Django app boundaries clear.
- Avoid putting crawler logic inside views.
- Put parsing logic inside services or scraper modules.
- Put long-running work into background tasks.
- Keep models small, explicit, and normalized.
- Do not use `tags` for skill logic.
- Keep naming consistent with existing apps:
  - `companies`
  - `jobs`
  - `applications`
  - `imports`
  - `skills`
  - `api`
  - `analytics`

## Migration Rules

- Before changing models, check existing migrations and current DB schema.
- If schema and migration history diverge, inspect carefully before adding more migrations.
- Do not assume `makemigrations` alone is enough.
- If the environment is development-only and the table is disposable, resetting the affected app may be acceptable.
- Prefer safe schema synchronization over manual DB guessing.

## Testing Rules

For every change, always provide:
1. What code was changed
2. How to test it
3. Expected result
4. Common failure points

Recommended testing workflow:
- `python manage.py makemigrations`
- `python manage.py migrate`
- `python manage.py showmigrations`
- `python manage.py shell`
- open the relevant page in browser
- verify ORM behavior on the modified model

If a page fails, first inspect:
- model fields
- migration state
- DB schema
- template field names
- view queryset / serializer fields

## Important Constraints

- Do not remove existing core features unless explicitly requested.
- Do not merge `tags` with `SkillSet`.
- Do not replace the shared `SkillSet` model with per-model ad hoc keyword strings.
- Do not make manual review the default requirement for skill extraction.
- Keep the system extensible for non-LinkedIn job sources.
- Keep the design compatible with automated scheduled crawling.

## Current Development Status

Already established:
- Django app structure exists
- Company / JobPost / Application core exists
- SkillSet exists and is shared
- `tags` are separate from SkillSet
- Ollama is the chosen skill extraction engine
- Source management entry point exists
- Source-specific parser output is normalized into CanonicalJobPayload before sync and LLM services

Next work should focus on:
1. crawler/parser foundation
2. sync/update pipeline
3. Ollama-based extraction pipeline
4. analytics
