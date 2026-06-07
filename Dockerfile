# for dev

#FROM python:3.12-slim
#
#ENV PYTHONDONTWRITEBYTECODE=1
#ENV PYTHONUNBUFFERED=1
#
#WORKDIR /app
#
#RUN apt-get update && apt-get install -y --no-install-recommends     build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
#
#COPY requirements/ /app/requirements/
#RUN pip install --no-cache-dir -r /app/requirements/dev.txt
#
#COPY . /app
#WORKDIR /app/src
#
#CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

#for production
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/base.txt && \
    pip install --no-cache-dir gunicorn==23.0.0

COPY . /app
WORKDIR /app/src

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]