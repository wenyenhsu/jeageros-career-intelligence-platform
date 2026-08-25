FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ /app/requirements/
ARG REQUIREMENTS_FILE=base.txt
RUN pip install -r /app/requirements/${REQUIREMENTS_FILE}


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN groupadd --gid 10001 django \
    && useradd --uid 10001 --gid django --create-home --shell /usr/sbin/nologin django \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R django:django /app

COPY --chown=django:django . /app
RUN chmod 755 /app/scripts/start-production.sh

WORKDIR /app/src
USER django

EXPOSE 8000

CMD ["/app/scripts/start-production.sh"]
