# Production deployment

Production uses the standalone `docker-compose.prod.yml` stack. Do not combine it
with the development `docker-compose.yml`: the development stack intentionally
mounts the source tree, exposes database ports, and runs Django's development
server.

## 1. Prepare production secrets

```bash
cp .env.production.example .env.production
openssl rand -base64 64
openssl rand -base64 36
```

Put distinct generated values in `SECRET_KEY`, `DB_PASSWORD`, and
`REDIS_PASSWORD`. Update both Celery Redis URLs with the same Redis password.
Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to the real HTTPS hostname.

The application refuses to start with a missing, weak, Django-insecure, or
example-placeholder `SECRET_KEY`. It also refuses a missing/example database
password, missing Celery broker configuration, SQLite, non-HTTPS trusted origins,
and malformed security booleans.

Never commit `.env.production`; it is ignored by Git and excluded from Docker
build contexts.

## 2. Provision TLS

Obtain a certificate for the production hostname and set these host paths in
`.env.production`:

```env
TLS_CERTIFICATE_PATH=/absolute/path/to/fullchain.pem
TLS_PRIVATE_KEY_PATH=/absolute/path/to/privkey.pem
```

Nginx redirects port 80 to HTTPS and terminates TLS on port 443. Django also
enforces HTTPS as defense in depth. Restart or reload Nginx after certificate
renewal.

HSTS defaults to one year with `includeSubDomains` and `preload`. Use a dedicated
production hostname whose descendants are all permanently HTTPS-only. If that is
not yet true, stage the rollout with shorter HSTS and the two options disabled;
`check --deploy` will deliberately warn until full hardening is enabled. Reducing
`SECURE_HSTS_SECONDS` does not immediately remove a policy cached by a browser,
and setting `preload` does not itself submit the domain to a browser preload list.

## 3. Validate before startup

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet

PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml build

PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml \
run --rm --no-deps web python manage.py check --deploy
```

Expected result: the Compose configuration is valid, the image builds, and
`check --deploy` reports no issues. A configuration error is intentional when a
required secret, hostname, database password, or certificate path is absent.

## 4. Start and initialize

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml up -d

PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

The Web startup command applies migrations, collects static assets, and then
starts Gunicorn. Celery services wait for the Web health check. PostgreSQL and
Redis are not published to host ports, Redis requires authentication, containers
use `no-new-privileges`, and application containers run on a read-only filesystem
as UID 10001. Application media is persisted but deliberately not served by
Nginx as public content.

Create the first administrator after the stack is healthy:

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml \
exec web python manage.py createsuperuser
```

## 5. Verify the deployed service

```bash
curl -I http://jobs.example.com/
curl -I https://jobs.example.com/accounts/login/

PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml exec web id
```

Expected results:

- HTTP responds with a redirect to HTTPS.
- HTTPS responses include `Strict-Transport-Security`.
- Session and CSRF cookies include `Secure` when issued.
- The Web container reports UID `10001`, not root.

## Common failure points

- A TLS mount path is wrong or unreadable: Nginx will fail its configuration
  check or restart repeatedly.
- Redis password and Celery URLs differ: workers cannot connect to the broker.
- The public hostname is absent from `ALLOWED_HOSTS`: requests return HTTP 400.
- The HTTPS origin is absent from `CSRF_TRUSTED_ORIGINS`: cross-host form posts
  fail CSRF validation.
- HSTS is enabled before HTTPS works on every intended hostname: browsers can
  refuse HTTP access until the cached policy expires.
- Production commands accidentally use `docker-compose.yml`: the app runs with
  development settings and `runserver`.

Back up the `postgres_data`, `application_media`, and `redis_data` volumes before
upgrades. Test restore procedures separately; a backup that has never been
restored is not verified.
