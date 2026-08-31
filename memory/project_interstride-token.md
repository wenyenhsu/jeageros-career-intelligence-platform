# Interstride token

Interstride auth belongs only in `.env` as `INTERSTRIDE_AUTH_TOKEN`.

Do not put the token in JobSource `crawl_config`, admin UI, or committed files.

After changing `.env`, restart `web` and `celery-worker`. Base URL is `https://student.interstride.com/`.

Never write the actual token value into memory or docs.
