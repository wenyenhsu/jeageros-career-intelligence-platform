from .base import *

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CRAWL_SKILL_PIPELINE_ENABLED = False
COVER_LETTER_TAILOR_RUN_INLINE = True
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = ""
GOOGLE_DRIVE_PARENT_FOLDER_ID = ""
