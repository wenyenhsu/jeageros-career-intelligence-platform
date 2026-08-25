#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
    --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-100}" \
    --access-logfile - \
    --error-logfile - \
    --capture-output
