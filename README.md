# JägerOS - Career Intelligence Platform

![Django](docs/logo.png)

JägerOS is a Django-based Career Intelligence Platform designed to help users:

- Track job applications
- Manage interview processes
- Schedule reminders and follow-ups
- Crawl job postings automatically
- Extract skills using LLMs (Ollama)
- Analyze job market trends
- Match resumes against market demand

---

# Architecture

![structure](docs/structure.png)

---

# Current Features

## Job Tracking

- Create / Update / Delete jobs
- Track application status
- Company management
- Job source management

## Application Management

- Applied
- Interview
- Offer
- Rejected
- Withdrawn

## Interview Tracking

- Multiple interview rounds
- Notes
- Scheduling

## Reminder System

- Follow-up reminders
- Interview reminders

## Job Crawling

### Current

- LinkedIn

### Planned

- Greenhouse
- Lever
- Handshake
- Indeed
- Workday

## Skill Intelligence

- Automatic skill extraction
- Ollama-powered processing
- Skill normalization
- SkillSet mapping
- Embedding generation (pgvector)

## Analytics

- Application statistics
- Skill trends
- Market demand analysis

---

# Tech Stack

## Backend

- Django 5
- Django ORM
- Django Admin

## Database

- PostgreSQL 15
- pgvector

## AI / LLM

- Ollama

## Async Processing

- Celery
- Redis

## Infrastructure

- Docker
- Docker Compose
- Nginx

---

# Project Structure

```text
src/
│
├── apps/
│   ├── accounts/
│   ├── analytics/
│   ├── api/
│   ├── applications/
│   ├── companies/
│   ├── imports/
│   ├── interviews/
│   ├── jobs/
│   ├── notifications/
│   ├── reminders/
│   └── skills/
│
├── config/
│
└── manage.py
```

---

# Initial Setup

## 1. Clone Repository

```bash
git clone https://github.com/<your-account>/jeageros-django-job-tracker.git

cd jeageros-django-job-tracker
```

## 2. Create Environment File

```bash
cp .env.example .env
```

Example:

```env
DEBUG=True

POSTGRES_DB=jaegeros
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

DJANGO_SETTINGS_MODULE=config.settings.dev

OLLAMA_BASE_URL=http://host.docker.internal:11434
```

## 3. Verify Docker

```bash
docker info
```

## 4. Build Containers

```bash
docker compose build
```

## 5. Start Services

```bash
docker compose up -d
```

Services:

| Service | Purpose |
|----------|----------|
| web | Django |
| db | PostgreSQL + pgvector |
| redis | Redis |
| celery-worker | Background Jobs |
| celery-beat | Scheduler |
| nginx | Reverse Proxy |

## 6. Run Migrations

```bash
docker compose exec web python manage.py migrate
```

Verify:

```bash
docker compose exec web python manage.py showmigrations
```

## 7. Create Admin User

```bash
docker compose exec web python manage.py createsuperuser
```

Example:

```text
Username: admin
Email: admin@example.com
Password: ********
```

## 8. Access Application

### Website

```text
http://localhost:8000
```

### Django Admin

```text
http://localhost:8000/admin
```

---

# Common Development Commands

## Start Project

```bash
docker compose up -d
```

## Stop Project

```bash
docker compose down
```

## View Logs

```bash
docker compose logs -f web
```

## Enter Django Container

```bash
docker compose exec web bash
```

## Django Shell

```bash
docker compose exec web python manage.py shell
```

---

# Database Commands

## Open PostgreSQL

```bash
docker compose exec db psql -U postgres
```

## List Tables

```sql
\dt
```

## Check Migrations

```bash
docker compose exec web python manage.py showmigrations
```

---

# pgvector Verification

Verify pgvector is installed:

```sql
SELECT * FROM pg_extension;
```

Expected:

```text
vector
```

---

# Skill Embedding Status

```bash
docker compose exec web python manage.py shell
```

```python
from apps.skills.models import SkillSet

total = SkillSet.objects.count()

embedded = SkillSet.objects.filter(
    embedding__isnull=False
).count()

print(f"Total Skills: {total}")
print(f"Embedded Skills: {embedded}")
```

---

# Celery

## Worker Logs

```bash
docker compose logs -f celery-worker
```

## Beat Scheduler Logs

```bash
docker compose logs -f celery-beat
```

---

# Job Crawling

Run crawler manually:

```bash
docker compose exec web python manage.py crawl_jobs
```

---

# Migration Workflow

## Generate Migration

```bash
docker compose exec web python manage.py makemigrations
```

## Apply Migration

```bash
docker compose exec web python manage.py migrate
```

## Check Status

```bash
docker compose exec web python manage.py showmigrations
```

---

# Future Roadmap

## Phase 1

- LinkedIn crawler
- Application tracking
- Skill extraction

## Phase 2

- Greenhouse support
- Lever support
- Handshake support

## Phase 3

- Resume analysis
- Skill gap analysis
- Market fit scoring

## Phase 4

- Open Skills Network integration
- ESCO integration
- Market taxonomy layer

## Phase 5

- Career recommendation engine
- Salary intelligence
- Hiring trend forecasting

---

# License

MIT License

---

# Author

**DR.XX**

JägerOS Career Intelligence Platform

Built with:

- Django
- PostgreSQL
- pgvector
- Docker
- Ollama
- Celery
- Redis