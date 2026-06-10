# JaegerOS

A Django-based career operations platform for managing job applications, interview workflows, reminders, and analytics.

## Tech Stack
- Django
- PostgreSQL
- Docker
- Celery
- Redis

## Local Run (Docker)
```bash
docker compose up --build
```

- App: http://localhost:8000
- Admin: http://localhost:8000/admin
- API: http://localhost:8000/api/v1/

## Scheduled Crawling
Docker Compose starts the crawler stack with these services:

- `web`
- `db`
- `redis`
- `celery-worker`
- `celery-beat`

Run the full stack:

```bash
docker compose up --build web celery-worker celery-beat redis db
```

Run a manual crawl inside the web container:

```bash
docker compose exec web python manage.py crawl_jobs
```

Trigger a crawl through the authenticated API:

```bash
curl -X POST http://localhost:8000/api/crawl/run/
```

Check crawl status:

```bash
curl http://localhost:8000/api/crawl/<crawl_run_id>/status/
```
